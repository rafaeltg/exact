from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any, NamedTuple

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import (
    ExactState,
    Finding,
    ResearchPayload,
    Source,
    focus_label,
)
from exact.prefs import exa_filters, filter_suffix, state_prefs
from exact.tools.exa import ExaClient
from exact.trace import Tracer, clip_error, crumb, wave_of
from exact.usage import (
    invoke_structured,
    llm_events_from_messages,
    tool_event,
)

# Hard ceiling on strings returned into the create_agent tool loop.
TOOL_TEXT_MAX = 8000

# The lanes whose searches send the domain and date filters.
_FILTERED_LANES = frozenset({"web", "publication"})


def clip_tool_text(text: str) -> str:
    return text if len(text) <= TOOL_TEXT_MAX else text[:TOOL_TEXT_MAX]


class SearchArgs(BaseModel):
    query: str = Field(description="Search query")


class HighlightsArgs(BaseModel):
    url: str = Field(description="URL to extract highlights from")


def _mint(topic_id: str, sources: list[Source], start: int) -> list[dict]:
    out = []
    for i, src in enumerate(sources, start=start):
        data = src.model_dump()
        data["id"] = f"src_{topic_id}_{i}"
        out.append(data)
    return out


def _drop_prior(sources: list[Source], prior: list[str]) -> list[Source]:
    seen = {p.casefold() for p in prior if p}
    return [s for s in sources if s.title.casefold() not in seen]


def _render(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        lines.append(
            f"[{s.get('id')}] {s.get('title')} ({focus_label(s)}) "
            f"{s.get('url') or s.get('doi') or ''}\n{s.get('snippet', '')}"
        )
    return "\n\n".join(lines) or "(none)"


def _compact_sources(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        snippet = (s.get("snippet") or "")[:240]
        lines.append(
            f"[{s.get('id')}] {s.get('title')} ({focus_label(s)}) "
            f"{s.get('url') or s.get('doi') or ''}\n{snippet}"
        )
    return "\n\n".join(lines) or "(none)"


def _call_note(name: str | None, args: dict) -> str:
    if name == "exa_highlights":
        return f"{name}: {args.get('url') or ''}"
    return f"{name}: {args.get('query') or ''}"


class _Ingested(NamedTuple):
    """What one successful attempt added to the bag."""

    text: str
    hit_count: int
    crumbs: list[dict]


class _Bag:
    """Mutable retrieval bag for one research worker."""

    def __init__(self, topic_id: str, prior: list[str], max_hits: int, tracer: Tracer):
        self.topic_id = topic_id
        self.prior = prior
        self.max_hits = max_hits
        self.tracer = tracer
        self.collected: list[dict] = []
        self.errors: list[str] = []
        self.notes: list[str] = []
        self.usage: list[dict] = []
        self.saw_hits = False
        # ToolNode runs the tool calls of one turn in parallel threads.
        self.lock = threading.Lock()

    def urls(self) -> set[str]:
        with self.lock:
            return {s.get("url") for s in self.collected if s.get("url")}

    def note(self, name: str, args: dict) -> None:
        self.notes.append(_call_note(name, args))

    def _inherit(self, minted: list[dict]) -> None:
        """A highlights read carries no lane or DOI; the owning source has both."""
        by_url = {s.get("url"): s for s in self.collected if s.get("url")}
        for row in minted:
            if row.get("focus") or row.get("doi"):
                continue
            owner = by_url.get(row.get("url"))
            if owner is None:
                continue
            row["focus"] = owner.get("focus")
            row["doi"] = owner.get("doi")

    def ingest(self, found: list[Source]) -> _Ingested:
        if found:
            self.saw_hits = True
        fresh = _drop_prior(found, self.prior)
        with self.lock:
            minted = _mint(self.topic_id, fresh, len(self.collected) + 1)
            self._inherit(minted)
            self.collected.extend(minted)
        # ``hit_count`` is the raw count, before the prior-title dedupe.
        return _Ingested(
            _compact_sources(minted), len(found), [crumb(row) for row in minted]
        )

    def _tool_line(self, name: str, args: dict, outcome: str) -> dict:
        """A ``tool`` summary with no result; an ``ok`` attempt adds its own."""
        return {
            "name": name,
            "outcome": outcome,
            "topic_id": self.topic_id,
            "wave": wave_of(self.topic_id),
            "query": args.get("query"),
            "url": args.get("url"),
            "hit_count": None,
            "sources": [],
            "error": None,
        }

    def refuse(self, name: str, args: dict) -> None:
        """Trace an attempt the tool turned away before any vendor call."""
        self.tracer.emit("tool", self._tool_line(name, args, "refused"))

    def call(self, label: str, fetch, args: dict) -> str:
        try:
            got = self.ingest(fetch())
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"{label}: {exc}")
            failed = self._tool_line(label, args, "error")
            self.tracer.emit("tool", {**failed, "error": clip_error(str(exc))})
            return clip_tool_text(f"{label} failed: {exc}")
        ok = self._tool_line(label, args, "ok")
        self.tracer.emit(
            "tool", {**ok, "hit_count": got.hit_count, "sources": got.crumbs}
        )
        self.usage.append(tool_event(label, "research_agent"))
        return clip_tool_text(got.text)


class _Tools:
    """LangChain tool implementations for one research worker."""

    def __init__(self, bag: _Bag, exa: ExaClient, filters: Mapping[str, Any]):
        self.bag = bag
        self.exa = exa
        self.filters = filters

    def exa_search(self, query: str) -> str:
        """Search the web with Exa."""
        args = {"query": query}
        self.bag.note("exa_search", args)
        return self.bag.call(
            "exa_search",
            lambda: self.exa.search(query, num=self.bag.max_hits, filters=self.filters),
            args,
        )

    def exa_people_search(self, query: str) -> str:
        """Search professional people profiles with Exa."""
        args = {"query": query}
        self.bag.note("exa_people_search", args)
        return self.bag.call(
            "exa_people_search",
            lambda: self.exa.search(query, num=self.bag.max_hits, category="people"),
            args,
        )

    def exa_company_search(self, query: str) -> str:
        """Search company profiles with Exa."""
        args = {"query": query}
        self.bag.note("exa_company_search", args)
        return self.bag.call(
            "exa_company_search",
            lambda: self.exa.search(query, num=self.bag.max_hits, category="company"),
            args,
        )

    def exa_highlights(self, url: str) -> str:
        """Get query-relevant highlights for a URL already retrieved."""
        args = {"url": url}
        if url not in self.bag.urls():
            self.bag.refuse("exa_highlights", args)
            return (
                "exa_highlights refused: url is not a retrieved source. "
                "Call it only with a url from the search results above."
            )
        self.bag.note("exa_highlights", args)
        return self.bag.call("exa_highlights", lambda: self.exa.highlights(url), args)

    def exa_publication_search(self, query: str) -> str:
        """Search academic publications with Exa."""
        args = {"query": query}
        self.bag.note("exa_publication_search", args)
        return self.bag.call(
            "exa_publication_search",
            lambda: self.exa.search(
                query,
                num=self.bag.max_hits,
                category="publication",
                filters=self.filters,
            ),
            args,
        )

    def as_list(self, focus: str | None) -> list[StructuredTool]:
        """The search tool of this topic's lane, plus the highlights reader."""
        searches = {
            "web": (self.exa_search, "exa_search"),
            "people": (self.exa_people_search, "exa_people_search"),
            "company": (self.exa_company_search, "exa_company_search"),
            "publication": (self.exa_publication_search, "exa_publication_search"),
        }
        fn, name = searches.get(focus or "web", searches["web"])
        return [
            StructuredTool.from_function(fn, name=name, args_schema=SearchArgs),
            StructuredTool.from_function(
                self.exa_highlights, name="exa_highlights", args_schema=HighlightsArgs
            ),
        ]


def _gap_kind(bag: _Bag, focus: str, suffix: str) -> str:
    """Why a lane returned nothing; the lane names itself so waves stay apart.

    ``suffix`` names the lane's active filters, which may be why it is empty.
    """
    if bag.errors:
        return f"lane {focus}: retrieval failed{suffix}"
    if bag.saw_hits:
        return f"lane {focus}: no new sources{suffix}"
    return f"lane {focus}: no sources{suffix}"


def _gap_suffix(focus: str, filters: Mapping[str, Any]) -> str:
    """The filter tail of a lane gap; only a filtered lane has one."""
    return filter_suffix(filters) if focus in _FILTERED_LANES else ""


def _empty_finding(
    topic_id: str, errors: list[str], gap: str, usage: list
) -> ExactState:
    finding = Finding(topic_id=topic_id, gaps=[gap], claims=[], source_ids=[])
    return {
        "sources": [],
        "findings": [finding.model_dump()],
        "errors": errors,
        "usage": usage,
    }


def _prune(
    runtime: Runtime, topic_id: str, brief: dict, collected, notes, errors
) -> ExactState:
    try:
        finding, usage = invoke_structured(
            runtime.model("compress"),
            Finding,
            [
                SystemMessage(
                    content=prompts.PRUNE.format(
                        topic_id=topic_id,
                        must_cover=brief.get("must_cover") or [],
                        sources=_render(collected),
                        notes="\n".join(notes)[:4000],
                    )
                ),
                HumanMessage(content="Extract the findings."),
            ],
            node="research_agent",
            role="compress",
            model_id=role_model_id(runtime.settings, "compress"),
        )
        finding.topic_id = topic_id
        # The compress model may name an id no attempt minted; the trace joins
        # on minted ids only.
        ids = {s["id"] for s in collected}
        finding.source_ids = [i for i in finding.source_ids if i in ids]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"prune: {exc}")
        finding = Finding(
            topic_id=topic_id,
            claims=[],
            source_ids=[s["id"] for s in collected],
            gaps=["prune failed"],
        )
        usage = []
    return {
        "sources": collected,
        "findings": [finding.model_dump()],
        "errors": errors,
        "usage": usage,
    }


def _with_degraded(out: ExactState, exa: ExaClient) -> ExactState:
    """A degraded capability is an error line, not a retrieval gap."""
    if exa.degraded:
        out["errors"] = [*(out.get("errors") or []), exa.degraded]
    return out


def _client(runtime: Runtime, settings) -> ExaClient:
    extras = runtime.extras
    return extras.get("exa") or ExaClient(settings.exa_api_key, settings.http_timeout)


def _begin_tool_session(model) -> None:
    """Optional seam: fakes reset per-worker round counts before create_agent."""
    begin = getattr(model, "begin_tool_session", None)
    if callable(begin):
        begin()


def _agent_messages(result) -> list:
    if isinstance(result, dict):
        return list(result.get("messages") or [])
    return []


def _run_agent(
    runtime: Runtime, tools: _Tools, topic: dict, brief: dict, prior, prefs: dict
) -> list:
    settings = runtime.settings
    model = runtime.model("research")
    model_id = role_model_id(settings, "research")
    query = topic.get("query") or ""
    focus = topic.get("focus") or "web"
    _begin_tool_session(model)
    agent = create_agent(
        model=model,
        tools=tools.as_list(focus),
        system_prompt=prompts.RESEARCH_SYS.format(
            topic=query,
            focus=focus,
            must_cover=brief.get("must_cover") or [],
            prior=prior or "(none)",
            bias=prompts.research_bias(prefs),
        ),
        middleware=[
            ModelCallLimitMiddleware(
                run_limit=settings.max_tool_rounds,
                exit_behavior="end",
            )
        ],
    )
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=f"Research: {query}")]}
        )
    except Exception as exc:  # noqa: BLE001
        tools.bag.errors.append(f"research loop: {exc}")
        return []
    return llm_events_from_messages(
        _agent_messages(result),
        node="research_agent",
        role="research",
        model=model_id,
    )


def research_agent(state: ResearchPayload, runtime: Runtime) -> ExactState:
    """Isolated worker: search, prune to a Finding, never return raw tool I/O."""
    settings = runtime.settings
    topic = state["topic"]
    brief = state.get("brief") or {}
    topic_id = topic.get("id") or "t"
    bag = _Bag(
        topic_id, state.get("prior_titles") or [], settings.max_hits, runtime.tracer
    )
    exa = _client(runtime, settings)
    prefs = state_prefs(state)
    filters = exa_filters(prefs)
    tools = _Tools(bag, exa, filters)
    loop_usage = _run_agent(runtime, tools, topic, brief, bag.prior, prefs)
    if not bag.collected:
        focus = topic.get("focus") or "web"
        return _with_degraded(
            _empty_finding(
                topic_id,
                bag.errors,
                _gap_kind(bag, focus, _gap_suffix(focus, filters)),
                loop_usage + bag.usage,
            ),
            exa,
        )
    out = _prune(runtime, topic_id, brief, bag.collected, bag.notes, bag.errors)
    out["usage"] = loop_usage + bag.usage + list(out.get("usage") or [])
    return _with_degraded(out, exa)
