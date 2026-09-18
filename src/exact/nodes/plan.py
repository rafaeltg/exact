from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Send

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import (
    ExactState,
    PlanDecision,
    PlannedTopic,
    Topic,
    TopicFocus,
    render_prior_queries,
)
from exact.usage import StructuredOutputError, invoke_structured

type ResearchRoute = Literal["write_report"] | list[Send]


def _fallback_focus(brief: dict) -> TopicFocus:
    """The lane to research when the planner produced nothing usable."""
    return "publication" if brief.get("intent") in ("academic", "mixed") else "web"


def _fallback_topics(state: ExactState, brief: dict) -> list[PlannedTopic]:
    """Topics for a wave the planner could not supply.

    Unused follow-ups are the reason a later wave exists, so they become its
    topics. A wave with none falls back to the brief question.
    """
    focus = _fallback_focus(brief)
    queries = [q.strip() for q in state.get("followups") or [] if q and q.strip()][:2]
    if not queries:
        queries = [brief.get("question") or state["initial_query"]]
    return [PlannedTopic(query=q, focus=focus) for q in queries]


def _planned_queries(decision: PlanDecision, wave: int) -> list[PlannedTopic]:
    """Usable planner topics within this wave's cap; empty when it gave none."""
    topics = [t for t in decision.topics if t.query and t.query.strip()][:3]
    if wave > 0:
        return topics[:2]
    return topics


def _focus_errors(topics: list[PlannedTopic]) -> list[str]:
    return [
        f"plan: dropped unknown topic focus {t.raw_focus!r}; used web"
        for t in topics
        if t.raw_focus
    ]


def _as_prior(entry: object) -> dict | None:
    """One ``prior_queries`` row; a bare string is a pre-lane checkpoint."""
    if isinstance(entry, str):
        return {"query": entry.strip(), "focus": "web"} if entry.strip() else None
    if not isinstance(entry, dict):
        return None
    # A pre-lane checkpoint holds unstripped queries; the dedup key needs both
    # sides normalized the same way.
    query = str(entry.get("query") or "").strip()
    if not query:
        return None
    return {"query": query, "focus": entry.get("focus") or "web"}


def _prior_queries(state: ExactState) -> list[dict]:
    rows = list(state.get("prior_queries") or []) + list(state.get("topics") or [])
    prior: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        row = _as_prior(raw)
        if row is None:
            continue
        key = (row["query"].lower(), row["focus"])
        if key in seen:
            continue
        seen.add(key)
        prior.append(row)
    return prior


def _unique_topics(
    planned: list[PlannedTopic], prior: list[dict], wave: int
) -> list[dict]:
    """Mint ids for topics the waves before this one did not already cover.

    The key is the query and the lane together: the same question asked of
    papers and of the web are two different topics.
    """
    seen = {(row["query"].lower(), row["focus"]) for row in prior}
    topics = []
    for i, t in enumerate(planned, start=1):
        key = (t.query.lower(), t.focus)
        if key in seen:
            continue
        seen.add(key)
        topics.append(
            Topic(
                id=f"t{wave}_{i}", query=t.query, focus=t.focus, status="pending"
            ).model_dump()
        )
    return topics


def _wave_topics(
    planned: list[PlannedTopic],
    fallback: list[PlannedTopic],
    prior: list[dict],
    wave: int,
) -> list[dict]:
    """Mint this wave's topics from the planner, or from the follow-ups.

    Planner topics dedup against the waves before this one. Fallback topics do
    not: the wave exists because of its follow-ups, and ``prior_queries``
    records what was *attempted*, so a retry after a failed lane would
    otherwise be dropped and the wave would end with nothing.
    """
    if planned:
        return _unique_topics(planned, prior, wave)
    return _unique_topics(fallback, [], wave)


def _plan_decision(
    state: ExactState, runtime: Runtime, brief: dict, prior: list[dict]
) -> tuple[PlanDecision, list[dict]]:
    return invoke_structured(
        runtime.model("router"),
        PlanDecision,
        [
            SystemMessage(
                content=prompts.PLAN.format(
                    brief=brief,
                    prior=render_prior_queries(prior) or "(none)",
                    followups=state.get("followups") or "(none)",
                )
            ),
            HumanMessage(content="Plan sub-topics."),
        ],
        node="plan_topics",
        role="router",
        model_id=role_model_id(runtime.settings, "router"),
    )


def plan_topics(state: ExactState, runtime: Runtime) -> ExactState:
    """Plan up to three wave topics.

    The planner is the only source of topics on every wave; unused follow-ups
    reach it through the prompt and come back as topics with a lane. A wave the
    planner could not supply -- a parse failure, or a plan with no usable topic
    -- researches those follow-ups directly instead.
    """
    brief = state.get("brief") or {}
    prior = _prior_queries(state)
    wave = int(state.get("iteration") or 0)
    fallback = _fallback_topics(state, brief)
    errors: list[str] = []
    try:
        decision, usage = _plan_decision(state, runtime, brief, prior)
    except StructuredOutputError as exc:
        # Empty, not ``fallback``: ``_wave_topics`` substitutes the fallback.
        # ``PlanDecision``'s before-validator coerces str and dict only, so a
        # ``PlannedTopic`` passed here would be blanked to an empty query.
        decision = PlanDecision(topics=[], reason="structured output fallback")
        usage = []
        errors = [str(exc)]
    planned = _planned_queries(decision, wave)
    errors += _focus_errors(planned)
    topics = _wave_topics(planned, fallback, prior, wave)
    out: ExactState = {
        "topics": topics,
        "iteration": wave,
        "prior_queries": prior
        + [{"query": t["query"], "focus": t["focus"]} for t in topics],
        "followups": [],
        "usage": usage,
    }
    if errors:
        out["errors"] = errors
    return out


def route_research(state: ExactState) -> ResearchRoute:
    """Fan out one ``Send`` per topic, or skip straight to write when empty."""
    topics = state.get("topics") or []
    if not topics:
        return "write_report"
    brief = state.get("brief") or {}
    prior = state.get("prior_titles") or []
    return [
        Send(
            "research_agent",
            {"topic": t, "brief": brief, "prior_titles": prior},
        )
        for t in topics
    ]
