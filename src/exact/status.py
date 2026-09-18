from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from exact.models import JsonMapping
from exact.usage import tool_counts


def format_update(node: str, update: Any) -> list[str]:
    """Turn a LangGraph ``stream_mode=updates`` item into CLI status lines."""
    if str(node).startswith("__"):
        return []
    data = update if isinstance(update, dict) else {}
    handler = _HANDLERS.get(node)
    if handler:
        return handler(data)
    return [f"[{node}]"]


def format_effort(snapshot: Mapping[str, Any]) -> str:
    """Render one run's resolved caps as the run-start echo line."""
    return (
        f"effort={snapshot['effort']} "
        f"waves={snapshot['max_iterations']} "
        f"topics={snapshot['max_topics_first_wave']}/"
        f"{snapshot['max_topics_followup']} "
        f"rounds={snapshot['max_tool_rounds']} "
        f"hits={snapshot['max_hits']} "
        f"clarify={snapshot['max_clarify_turns']} "
        f"concurrency={snapshot['max_concurrency']}"
    )


def format_plan(topics: Sequence[JsonMapping], *, wave: int | None = None) -> list[str]:
    n = len(topics)
    label = f"wave {wave}" if wave is not None else "next"
    noun = "topic" if n == 1 else "topics"
    lines = [f"[plan] {label} — {n} {noun}"]
    for topic in topics:
        tid = topic.get("id") or "?"
        # A checkpoint written before topics carried a lane reads as web.
        focus = topic.get("focus") or "web"
        query = (topic.get("query") or "").strip()
        lines.append(f"  {tid} [{focus}]  {query}")
    return lines


def _is_paper(hit: dict) -> bool:
    """A publication lane hit, or an Elicit row from a pre-focus checkpoint."""
    return hit.get("focus") == "publication" or hit.get("provider") == "elicit"


def _is_web(hit: dict) -> bool:
    """A web lane hit; a focus-less Exa row is a pre-focus checkpoint."""
    if hit.get("focus") is None:
        return hit.get("provider") == "exa"
    return hit.get("focus") == "web"


def _scout(data: dict) -> list[str]:
    hits = data.get("scout_hits") or []
    web = sum(1 for h in hits if _is_web(h))
    papers = sum(1 for h in hits if _is_paper(h))
    return [f"[scout] {web} web · {papers} papers"]


def _decide_clarify(data: dict) -> list[str]:
    if data.get("clarify_needed"):
        return ["[clarify] asking"]
    return ["[clarify] skip"]


def _ask_user(data: dict) -> list[str]:
    kind = (data.get("user_clarification") or {}).get("kind") or "recorded"
    return [f"[clarify] {kind}"]


def _brief(data: dict) -> list[str]:
    brief = data.get("brief") or {}
    intent = brief.get("intent") or "web"
    n = len(brief.get("must_cover") or [])
    question = (brief.get("question") or "").strip()
    lines = [f"[brief] intent={intent}  must_cover={n}"]
    if question:
        lines.append(f"  {question}")
    return lines


def _plan(data: dict) -> list[str]:
    topics = data.get("topics") or []
    wave = data.get("iteration")
    if wave is None and topics:
        wave = _wave_from_topics(topics)
    return format_plan(topics, wave=wave)


# Display order for the research suffix. ``EXA_SEARCH_KINDS`` drives membership
# and totals, but a frozenset has no iteration order and this line is pinned.
_TOOL_DISPLAY_ORDER = (
    "exa_search",
    "exa_people_search",
    "exa_company_search",
    "exa_publication_search",
    "exa_highlights",
    "elicit_search",
)


def _research_tool_suffix(usage: list) -> str:
    counts = tool_counts(usage)
    parts = []
    for kind in _TOOL_DISPLAY_ORDER:
        n = counts.get(kind)
        if n:
            parts.append(f"{n} {kind}")
    if not parts:
        return ""
    return "  · " + " · ".join(parts)


def _research(data: dict) -> list[str]:
    findings = data.get("findings") or []
    topic_id = (findings[0].get("topic_id") if findings else None) or "t"
    n = len(data.get("sources") or [])
    noun = "source" if n == 1 else "sources"
    line = f"[research {topic_id}] {n} {noun}"
    # Waves repeat a failure verbatim; the count is of distinct failures.
    errors = set(data.get("errors") or [])
    if errors:
        line += f"  ({len(errors)} error{'s' if len(errors) != 1 else ''})"
    line += _research_tool_suffix(data.get("usage") or [])
    return [line]


def _reflect(data: dict) -> list[str]:
    if data.get("continue_research"):
        lines = ["[reflect] continue"]
        for query in data.get("followups") or []:
            if query:
                lines.append(f"  {query}")
        return lines
    return ["[reflect] write"]


def _write(_data: dict) -> list[str]:
    return ["[write]"]


def _audit(data: dict) -> list[str]:
    dangling = [
        item
        for item in (data.get("uncovered") or [])
        if isinstance(item, str) and item.startswith("dangling:")
    ]
    if dangling:
        n = len(dangling)
        noun = "citation" if n == 1 else "citations"
        return [f"[audit] {n} unresolved {noun}"]
    return ["[audit] ok"]


def _wave_from_topics(topics: list[dict]) -> int | None:
    tid = (topics[0].get("id") or "") if topics else ""
    if tid.startswith("t") and "_" in tid:
        part = tid[1:].split("_", 1)[0]
        if part.isdigit():
            return int(part)
    return None


_HANDLERS = {
    "scout": _scout,
    "decide_clarify": _decide_clarify,
    "ask_user": _ask_user,
    "generate_brief": _brief,
    "plan_topics": _plan,
    "research_agent": _research,
    "reflect": _reflect,
    "write_report": _write,
    "audit_citations": _audit,
}
