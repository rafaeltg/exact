from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import ExactState, Finding, ResearchPayload, Source
from exact.tools.elicit import ElicitClient
from exact.tools.exa import ExaClient
from exact.usage import (
    invoke_structured,
    llm_events_from_messages,
    tool_event,
)

# Hard ceiling on strings returned into the create_agent tool loop.
TOOL_TEXT_MAX = 8000


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
            f"[{s.get('id')}] {s.get('title')} ({s.get('provider')}) "
            f"{s.get('url') or s.get('doi') or ''}\n{s.get('snippet', '')}"
        )
    return "\n\n".join(lines) or "(none)"


def _compact_sources(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        snippet = (s.get("snippet") or "")[:240]
        lines.append(
            f"[{s.get('id')}] {s.get('title')} "
            f"{s.get('url') or s.get('doi') or ''}\n{snippet}"
        )
    return "\n\n".join(lines) or "(none)"


def _call_note(name: str | None, args: dict) -> str:
    if name == "exa_highlights":
        return f"{name}: {args.get('url') or ''}"
    return f"{name}: {args.get('query') or ''}"


class _Bag:
    """Mutable retrieval bag for one research worker."""

    def __init__(self, topic_id: str, prior: list[str], max_hits: int):
        self.topic_id = topic_id
        self.prior = prior
        self.max_hits = max_hits
        self.collected: list[dict] = []
        self.errors: list[str] = []
        self.notes: list[str] = []
        self.usage: list[dict] = []
        self.saw_hits = False

    def note(self, name: str, args: dict) -> None:
        self.notes.append(_call_note(name, args))

    def ingest(self, found: list[Source]) -> str:
        if found:
            self.saw_hits = True
        minted = _mint(
            self.topic_id, _drop_prior(found, self.prior), len(self.collected) + 1
        )
        self.collected.extend(minted)
        return _compact_sources(minted)

    def call(self, label: str, fetch) -> str:
        try:
            out = self.ingest(fetch())
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"{label}: {exc}")
            return clip_tool_text(f"{label} failed: {exc}")
        self.usage.append(tool_event(label, "research_agent"))
        return clip_tool_text(out)


class _Tools:
    """LangChain tool implementations for one research worker."""

    def __init__(self, bag: _Bag, exa: ExaClient, elicit: ElicitClient, intent: str):
        self.bag = bag
        self.exa = exa
        self.elicit = elicit
        self.intent = intent

    def exa_search(self, query: str) -> str:
        """Search the web with Exa."""
        self.bag.note("exa_search", {"query": query})
        return self.bag.call(
            "exa_search", lambda: self.exa.search(query, num=self.bag.max_hits)
        )

    def exa_people_search(self, query: str) -> str:
        """Search professional people profiles with Exa."""
        self.bag.note("exa_people_search", {"query": query})
        return self.bag.call(
            "exa_people_search",
            lambda: self.exa.search(query, num=self.bag.max_hits, category="people"),
        )

    def exa_company_search(self, query: str) -> str:
        """Search company profiles with Exa."""
        self.bag.note("exa_company_search", {"query": query})
        return self.bag.call(
            "exa_company_search",
            lambda: self.exa.search(query, num=self.bag.max_hits, category="company"),
        )

    def exa_highlights(self, url: str) -> str:
        """Get query-relevant highlights for a URL via Exa."""
        self.bag.note("exa_highlights", {"url": url})
        return self.bag.call("exa_highlights", lambda: self.exa.highlights(url))

    def elicit_search(self, query: str) -> str:
        """Search academic papers with Elicit."""
        self.bag.note("elicit_search", {"query": query})
        allowed = self.intent in ("academic", "mixed") and self.elicit.enabled
        if not allowed:
            return "elicit_search disabled (no key or non-academic brief)."
        return self.bag.call(
            "elicit_search",
            lambda: self.elicit.search(query, num=self.bag.max_hits),
        )

    def as_list(self) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(
                self.exa_search, name="exa_search", args_schema=SearchArgs
            ),
            StructuredTool.from_function(
                self.exa_people_search,
                name="exa_people_search",
                args_schema=SearchArgs,
            ),
            StructuredTool.from_function(
                self.exa_company_search,
                name="exa_company_search",
                args_schema=SearchArgs,
            ),
            StructuredTool.from_function(
                self.exa_highlights, name="exa_highlights", args_schema=HighlightsArgs
            ),
            StructuredTool.from_function(
                self.elicit_search, name="elicit_search", args_schema=SearchArgs
            ),
        ]


def _gap_kind(bag: _Bag) -> str:
    if bag.errors:
        return "retrieval failed"
    if bag.saw_hits:
        return "no new sources"
    return "no sources"


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
    model_id = role_model_id(runtime.settings, "compress")
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
            model_id=model_id,
        )
        finding.topic_id = topic_id
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


def _clients(runtime: Runtime, settings) -> tuple[ExaClient, ElicitClient]:
    extras = runtime.extras
    exa = extras.get("exa") or ExaClient(settings.exa_api_key, settings.http_timeout)
    elicit = extras.get("elicit") or ElicitClient(
        settings.elicit_api_key, settings.http_timeout
    )
    return exa, elicit


def _begin_tool_session(model) -> None:
    """Optional seam: fakes reset per-worker round counts before create_agent."""
    begin = getattr(model, "begin_tool_session", None)
    if callable(begin):
        begin()


def _agent_messages(result) -> list:
    if isinstance(result, dict):
        return list(result.get("messages") or [])
    return []


def _run_agent(runtime: Runtime, tools: _Tools, query: str, brief: dict, prior) -> list:
    settings = runtime.settings
    model = runtime.model("research")
    model_id = role_model_id(settings, "research")
    _begin_tool_session(model)
    agent = create_agent(
        model=model,
        tools=tools.as_list(),
        system_prompt=prompts.RESEARCH_SYS.format(
            topic=query,
            must_cover=brief.get("must_cover") or [],
            prior=prior or "(none)",
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
    query = topic.get("query") or ""
    bag = _Bag(topic_id, state.get("prior_titles") or [], settings.max_hits)
    exa, elicit = _clients(runtime, settings)
    tools = _Tools(bag, exa, elicit, brief.get("intent") or "web")
    loop_usage = _run_agent(runtime, tools, query, brief, bag.prior)
    if not bag.collected:
        return _empty_finding(
            topic_id, bag.errors, _gap_kind(bag), loop_usage + bag.usage
        )
    out = _prune(runtime, topic_id, brief, bag.collected, bag.notes, bag.errors)
    out["usage"] = loop_usage + bag.usage + list(out.get("usage") or [])
    return out
