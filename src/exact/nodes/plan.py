from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Send

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import PlanDecision, Topic
from exact.usage import StructuredOutputError, invoke_structured


def _planned_queries(
    decision: PlanDecision, brief: dict, query: str, wave: int
) -> list[str]:
    queries = [q.strip() for q in decision.topics if q and q.strip()][:3]
    if not queries:
        queries = [brief.get("question") or query]
    if wave > 0:
        return queries[:2]
    return queries


def _followup_queries(raw) -> list[str]:
    return [q.strip() for q in raw if q and q.strip()][:2]


def _wave_queries(suggested: list[str], planned: list[str], prior: list) -> list[str]:
    seen = {p.lower() for p in prior if p}
    fresh = [q for q in suggested if q.lower() not in seen]
    if fresh:
        return fresh
    return planned


def _prior_queries(state: dict) -> list[str]:
    prior: list[str] = []
    seen: set[str] = set()
    for q in list(state.get("prior_queries") or []) + [
        t.get("query") for t in (state.get("topics") or [])
    ]:
        key = (q or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        prior.append(q)
    return prior


def _unique_topics(queries: list[str], prior: list, wave: int) -> list[dict]:
    seen = {p.lower() for p in prior if p}
    topics = []
    for i, q in enumerate(queries, start=1):
        if q.lower() in seen:
            continue
        topics.append(Topic(id=f"t{wave}_{i}", query=q, status="pending").model_dump())
    return topics


def _plan_decision(
    state: dict, runtime: Runtime, brief: dict, prior: list[str]
) -> tuple[PlanDecision, list[dict]]:
    return invoke_structured(
        runtime.model("router"),
        PlanDecision,
        [
            SystemMessage(
                content=prompts.PLAN.format(
                    brief=brief,
                    prior=prior or "(none)",
                    followups=state.get("followups") or "(none)",
                )
            ),
            HumanMessage(content="Plan sub-topics."),
        ],
        node="plan_topics",
        role="router",
        model_id=role_model_id(runtime.settings, "router"),
    )


def plan_topics(state: dict, runtime: Runtime) -> dict:
    brief = state.get("brief") or {}
    prior = _prior_queries(state)
    wave = int(state.get("iteration") or 0)
    errors: list[str] = []
    try:
        decision, usage = _plan_decision(state, runtime, brief, prior)
    except StructuredOutputError as exc:
        decision = PlanDecision(
            topics=[brief.get("question") or state["initial_query"]],
            reason="structured output fallback",
        )
        usage = []
        errors = [str(exc)]
    queries = _wave_queries(
        _followup_queries(state.get("followups") or []),
        _planned_queries(decision, brief, state["initial_query"], wave),
        prior,
    )
    topics = _unique_topics(queries, prior, wave)
    out = {
        "topics": topics,
        "iteration": wave,
        "prior_queries": prior + [t["query"] for t in topics],
        "followups": [],
        "usage": usage,
    }
    if errors:
        out["errors"] = errors
    return out


def route_research(state: dict):
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
