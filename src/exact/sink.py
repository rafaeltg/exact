"""Derive trace events from the ``stream_mode=updates`` chunks the CLI prints.

The sink reads only what a node returns on state, so it needs no node binding.
Each payload holds the raw chunk value; ``plan.wave`` is the one derived value.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from exact.trace import Tracer, wave_of

# The ``docs/spec.md`` usage event fields, in that order.
_USAGE_KEYS = (
    "kind",
    "node",
    "role",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read",
    "cache_creation",
    "calls",
)


def _decision_clarify(data: dict) -> dict:
    return {"stage": "clarify", "needed": data.get("clarify_needed")}


def _decision_reflect(data: dict) -> dict:
    # The done and cap-exit paths omit ``followups``: none is known, not unknown.
    return {
        "stage": "reflect",
        "continue": data.get("continue_research"),
        "followups": data.get("followups", []),
        "uncovered": data.get("uncovered"),
    }


def _brief(data: dict) -> dict:
    brief = data.get("brief") or {}
    return {
        "intent": brief.get("intent"),
        "must_cover": brief.get("must_cover"),
        "question": brief.get("question"),
    }


def _plan(data: dict) -> dict:
    topics = data.get("topics") or []
    wave = data.get("iteration")
    if wave is None and topics:
        wave = wave_of(topics[0].get("id"))
    return {
        "wave": wave,
        "topics": [
            {"id": t.get("id"), "query": t.get("query"), "focus": t.get("focus")}
            for t in topics
        ],
    }


def _finding(data: dict) -> dict:
    # One ``Send`` worker yields one chunk with exactly one finding.
    finding = data["findings"][0]
    topic_id = finding.get("topic_id")
    return {
        "topic_id": topic_id,
        "wave": wave_of(topic_id),
        "claims": len(finding.get("claims") or []),
        "source_ids": finding.get("source_ids"),
        "gaps": finding.get("gaps"),
    }


_STAGE: dict[str, tuple[str, Callable[[dict], dict]]] = {
    "decide_clarify": ("decision", _decision_clarify),
    "reflect": ("decision", _decision_reflect),
    "generate_brief": ("brief", _brief),
    "plan_topics": ("plan", _plan),
    "research_agent": ("finding", _finding),
}


def _usage_topic(node: str, data: dict) -> str | None:
    if node == "research_agent":
        return data["findings"][0].get("topic_id")
    if node == "scout":
        return "scout"
    return None


def _usage_lines(node: str, data: dict) -> list[dict]:
    """One payload per usage event; a key the event omits is ``None``, never 0."""
    topic_id = _usage_topic(node, data)
    wave = wave_of(topic_id)
    return [
        {
            **{key: event.get(key) for key in _USAGE_KEYS},
            "topic_id": topic_id,
            "wave": wave,
        }
        for event in data.get("usage") or []
    ]


def emit_chunk(tracer: Tracer, node: str, update: Any) -> None:
    """Emit every trace event of one ``stream_mode=updates`` chunk.

    It never raises: a chunk of unexpected shape counts as one dropped emit, so
    tracing cannot fail a run that would otherwise finish.
    """
    if str(node).startswith("__"):
        return
    data = update if isinstance(update, dict) else {}
    try:
        stage = _STAGE.get(node)
        if stage is not None:
            kind, build = stage
            tracer.emit(kind, build(data))
        for line in _usage_lines(node, data):
            tracer.emit("usage", line)
    except Exception as exc:  # noqa: BLE001
        tracer.record_drop(exc)
