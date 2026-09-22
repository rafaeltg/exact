from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage

from exact.config import Runtime, Settings
from exact.models import (
    ClarifyDecision,
    Finding,
    PlanDecision,
    ReflectDecision,
    ResearchBrief,
    Source,
)
from exact.prefs import default_prefs, effective_excludes, start_date
from exact.trace import NullTracer, Tracer

_SCHEMA_ATTR = {
    ClarifyDecision: "clarify",
    ResearchBrief: "brief",
    PlanDecision: "plan",
    ReflectDecision: "reflect",
    Finding: "finding",
}


def source(
    *,
    id: str = "tmp",
    title: str = "Source A",
    url: str = "https://example.com/a",
    provider: str = "exa",
    snippet: str | None = None,
    doi: str | None = None,
    focus: str | None = None,
) -> Source:
    return Source(
        id=id,
        title=title,
        url=url,
        doi=doi,
        focus=focus,
        snippet=snippet or "X is Y according to this page.",
        provider=provider,
        retrieved_at="2026-01-01T00:00:00Z",
    )


def _require_conversation(messages) -> None:
    items = messages if isinstance(messages, (list, tuple)) else [messages]
    if any(getattr(m, "type", None) != "system" for m in items):
        return
    raise ValueError("messages: at least one message is required")


class FakeStructured:
    def __init__(self, owner: FakeLLM, attr: str, *, include_raw: bool = False):
        self.owner = owner
        self.attr = attr
        self.include_raw = include_raw
        self.invocations = 0
        self.last_messages: list = []

    def invoke(self, messages):
        _require_conversation(messages)
        self.invocations += 1
        self.last_messages = messages
        if self.owner.fail_structured:
            if self.include_raw:
                return {
                    "raw": AIMessage(
                        content="",
                        usage_metadata=_usage_meta(self.owner.usage_metadata),
                    ),
                    "parsed": None,
                    "parsing_error": "failed",
                }
            return None
        obj = getattr(self.owner, self.attr)
        if isinstance(obj, list):
            parsed = obj[min(self.invocations - 1, len(obj) - 1)]
        else:
            parsed = obj
        # A real model parses a fresh object per call; parallel workers must
        # not share one that a node then edits.
        parsed = parsed.model_copy(deep=True)
        if not self.include_raw:
            return parsed
        return {
            "raw": AIMessage(
                content="", usage_metadata=_usage_meta(self.owner.usage_metadata)
            ),
            "parsed": parsed,
            "parsing_error": None,
        }


def _usage_meta(meta: dict | None) -> dict | None:
    if not meta:
        return None
    if "total_tokens" in meta:
        return meta
    out = dict(meta)
    out["total_tokens"] = int(meta.get("input_tokens") or 0) + int(
        meta.get("output_tokens") or 0
    )
    return out


def _topic_query(messages) -> str:
    for message in messages:
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.startswith("Research: "):
            return content.removeprefix("Research: ")
    return ""


class FakeBound:
    """Bound research model for create_agent.

    create_agent rebinds every model step. Round counts live on the owning
    FakeLLM's thread-local. `FakeLLM.begin_tool_session` resets them at the
    start of each research worker so rebinds and parallel Send stay correct
    without inspecting message history.
    """

    def __init__(
        self,
        owner: FakeLLM,
        tools,
        *,
        tool_name: str = "exa_search",
        tool_args: dict | None = None,
        max_calls: int = 1,
        script: list[tuple[str, dict]] | None = None,
        echo_topic: bool = False,
    ):
        self.owner = owner
        self.tools = tools
        self.tool_name = tool_name
        self.tool_args = tool_args or {"query": "test"}
        self.script = script or []
        self.max_calls = len(self.script) or max_calls
        self.echo_topic = echo_topic

    def _step(self, round_no: int, messages) -> tuple[str, dict]:
        """One (tool name, args) pair per round; ``script`` wins when set.

        ``echo_topic`` searches the worker's own topic query, so parallel
        workers stay apart.
        """
        if self.script:
            return self.script[round_no - 1]
        if self.echo_topic:
            return self.tool_name, {"query": _topic_query(messages)}
        return self.tool_name, self.tool_args

    @property
    def calls(self) -> int:
        return int(getattr(self.owner._local, "calls", 0))

    def invoke(self, messages, **_kwargs):
        local = self.owner._local
        local.calls = getattr(local, "calls", 0) + 1
        self.owner.last_tool_loop_messages = list(messages)
        meta = _usage_meta(self.owner.tool_usage_metadata)
        if local.calls <= self.max_calls:
            name, args = self._step(local.calls, messages)
            return AIMessage(
                content="",
                usage_metadata=meta,
                tool_calls=[
                    {
                        "name": name,
                        "args": args,
                        "id": f"call_{local.calls}",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="enough", usage_metadata=meta)


class FakeLLM:
    def __init__(
        self,
        *,
        clarify: ClarifyDecision | None = None,
        brief: ResearchBrief | None = None,
        plan: PlanDecision | list[PlanDecision] | None = None,
        reflect: ReflectDecision | list[ReflectDecision] | None = None,
        finding: Finding | None = None,
        report: str = "X is Y [src_t0_1_1].",
        tool_name: str = "exa_search",
        tool_args: dict | None = None,
        tool_rounds: int = 1,
        tool_script: list[tuple[str, dict]] | None = None,
        usage_metadata: dict | None = None,
        tool_usage_metadata: dict | None = None,
        fail_structured: bool = False,
        echo_topic: bool = False,
    ):
        self.clarify = clarify or ClarifyDecision(needed=False, question="", options=[])
        self.brief = brief or ResearchBrief(
            question="What is X?",
            intent="web",
            must_cover=["define X"],
        )
        self.plan = plan or PlanDecision(topics=["define X"], reason="simple")
        self.reflect = reflect or ReflectDecision(done=True, followups=[], uncovered=[])
        self.finding = finding or Finding(
            topic_id="t0_1",
            claims=["X is Y"],
            source_ids=["src_t0_1_1"],
            gaps=[],
            covered=["define X"],
        )
        self.report = report
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.tool_rounds = tool_rounds
        self.tool_script = tool_script
        self.usage_metadata = usage_metadata
        self.tool_usage_metadata = tool_usage_metadata
        self.fail_structured = fail_structured
        self.echo_topic = echo_topic
        self.bound: FakeBound | None = None
        self._structured: dict = {}
        self._local = threading.local()
        self.last_tool_loop_messages: list = []
        self.last_text_messages: list = []

    def begin_tool_session(self) -> None:
        """Reset per-thread tool-round counts for one research worker run."""
        self._local.calls = 0

    def with_structured_output(self, schema, **kwargs):
        include_raw = bool(kwargs.get("include_raw"))
        if schema not in self._structured:
            self._structured[schema] = FakeStructured(
                self, _SCHEMA_ATTR[schema], include_raw=include_raw
            )
        else:
            self._structured[schema].include_raw = include_raw
        return self._structured[schema]

    def bind_tools(self, tools, **_kwargs):
        self.bound = FakeBound(
            self,
            tools,
            tool_name=self.tool_name,
            tool_args=self.tool_args,
            max_calls=self.tool_rounds,
            script=self.tool_script,
            echo_topic=self.echo_topic,
        )
        return self.bound

    def invoke(self, messages, **_kwargs):
        _require_conversation(messages)
        self.last_text_messages = list(messages)
        return AIMessage(
            content=self.report, usage_metadata=_usage_meta(self.usage_metadata)
        )


class FakeExa:
    def __init__(
        self,
        hits: list[Source] | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
        failing: dict[str | None, Exception] | None = None,
    ):
        self._hits = hits
        self._error = error
        # Keyed by search query or by category: one lane or one topic fails.
        self._failing = failing or {}
        self.delay = delay
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()
        self.degraded: str | None = None
        self.search_nums: list[int] = []
        self.search_categories: list[str | None] = []
        self.search_filters: list[dict] = []
        self.highlight_urls: list[str] = []

    def _results(self) -> list[Source]:
        if self._error:
            raise self._error
        if self._hits is not None:
            return list(self._hits)
        return [source()]

    def search(
        self,
        query: str,
        num: int = 5,
        *,
        category: str | None = None,
        filters: dict | None = None,
    ) -> list[Source]:
        self._enter()
        try:
            time.sleep(self.delay)
        finally:
            self._leave()
        self.search_nums.append(num)
        self.search_categories.append(category)
        self.search_filters.append(dict(filters or {}))
        for key in (query, category):
            if key in self._failing:
                raise self._failing[key]
        return [
            h.model_copy(update={"focus": category or "web"}) for h in self._results()
        ]

    def _enter(self) -> None:
        """Record one more in-flight search and the high-water mark."""
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def _leave(self) -> None:
        with self._lock:
            self.active -= 1

    def highlights(self, url: str) -> list[Source]:
        self.highlight_urls.append(url)
        # The real client cannot know a lane or a DOI from a bare URL read.
        return [
            h.model_copy(update={"focus": None, "doi": None}) for h in self._results()
        ]


class FakeElicit:
    def __init__(
        self,
        hits: list[Source] | None = None,
        error: Exception | None = None,
        enabled: bool = False,
    ):
        self._hits = hits or []
        self._error = error
        self.enabled = enabled
        self.search_nums: list[int] = []

    def search(self, query: str, num: int = 5) -> list[Source]:
        self.search_nums.append(num)
        if self._error:
            raise self._error
        return list(self._hits)


def read_trace(path: Path) -> list[dict]:
    """Parse one sidecar file into its envelope objects."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class RecordingTracer(Tracer):
    """The ``Tracer`` fake: it keeps every emit instead of writing a file."""

    def __init__(self) -> None:
        self.run_id = "fake"
        self.dropped = 0
        self.events: list[tuple[str, dict]] = []
        self.closed = False

    def emit(self, kind: str, data: dict) -> None:
        self.events.append((kind, data))

    def record_drop(self, exc: Exception) -> None:
        self.dropped += 1

    def close(self) -> None:
        self.closed = True

    def kinds(self) -> list[str]:
        """The kind of each recorded event, in emit order."""
        return [kind for kind, _ in self.events]

    def payloads(self, kind: str) -> list[dict]:
        """Every payload recorded under ``kind``, in emit order."""
        return [data for recorded, data in self.events if recorded == kind]


def runtime(
    *,
    llm: FakeLLM | None = None,
    exa: FakeExa | None = None,
    elicit: FakeElicit | None = None,
    llms: dict | None = None,
    tracer: Tracer | None = None,
    **setting_kwargs,
) -> Runtime:
    settings = dict(exa_api_key="test", anthropic_api_key="test")
    settings.update(setting_kwargs)
    primary = llm or FakeLLM()
    extras: dict = {"exa": exa or FakeExa(), "elicit": elicit or FakeElicit()}
    if llms is not None:
        extras["llms"] = llms
    return Runtime(
        settings=Settings(_env_file=None, **settings),
        llm=primary,
        extras=extras,
        tracer=tracer or NullTracer(),
    )


# The instant every fake thread is seeded at, so start dates are fixed.
SEED_INSTANT = datetime(2026, 9, 21, 1, tzinfo=UTC)


def seed_prefs(**overrides) -> dict:
    """A ``prefs`` dict as the CLI seeds it, with the derived keys filled in."""
    prefs = {**default_prefs(), **overrides}
    if "effective_exclude_domains" not in overrides:
        prefs["effective_exclude_domains"] = effective_excludes(
            prefs["exclude_domains"], prefs["denylist"]
        )
    if "start_published_date" not in overrides:
        prefs["start_published_date"] = start_date(prefs["recency"], SEED_INSTANT)
    return prefs


def graph_seed(**overrides) -> dict:
    seed = {
        "initial_query": "What is X?",
        "prefs": seed_prefs(clarify_mode="skip"),
        "effort": "normal",
        "max_iterations": 3,
        "max_clarify_turns": 3,
        "max_topics_first_wave": 3,
        "max_topics_followup": 2,
        "clarify_turns": 0,
        "iteration": 0,
        "messages": [],
        "sources": [],
        "findings": [],
        "errors": [],
        "usage": [],
        "prior_titles": [],
        "prior_queries": [],
        "followups": [],
        "uncovered": [],
        "topics": [],
        "scout_hits": [],
    }
    seed.update(overrides)
    return seed
