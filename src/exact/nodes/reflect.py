from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import ExactState, ReflectDecision, render_prior_queries
from exact.usage import StructuredOutputError, invoke_structured

type ReflectRoute = Literal["plan_topics", "write_report"]


def _titles(sources: list) -> list[str]:
    return [s["title"] for s in sources if s.get("title")]


def _gaps(findings: list) -> list[str]:
    out = []
    for finding in findings:
        out.extend(finding.get("gaps") or [])
    return out


def _cap_exit(iteration: int, titles: list[str], findings: list) -> ExactState:
    return {
        "prior_titles": titles,
        "uncovered": _gaps(findings),
        "continue_research": False,
        "iteration": iteration,
    }


def _followups(decision: ReflectDecision, cap: int) -> list[str]:
    return [q for q in decision.followups if q.strip()][:cap]


def _decision_update(decision: ReflectDecision, iteration: int, cap: int) -> ExactState:
    followups = _followups(decision, cap)
    if decision.done or not followups:
        return {
            "uncovered": decision.uncovered,
            "continue_research": False,
            "iteration": iteration,
        }
    return {
        "uncovered": decision.uncovered,
        "continue_research": True,
        "iteration": iteration + 1,
        "followups": followups,
    }


def _ask(
    runtime: Runtime, state: ExactState, cap: int
) -> tuple[ReflectDecision, list[dict]]:
    return invoke_structured(
        runtime.model("router"),
        ReflectDecision,
        [
            SystemMessage(
                content=prompts.REFLECT.format(
                    brief=state.get("brief") or {},
                    findings=prompts.findings_block(state.get("findings")),
                    prior=render_prior_queries(
                        state.get("prior_queries") or (state.get("topics") or [])
                    )
                    or "(none)",
                    followup_cap=cap,
                )
            ),
            HumanMessage(content="Decide whether to continue."),
        ],
        node="reflect",
        role="router",
        model_id=role_model_id(runtime.settings, "router"),
    )


def reflect(state: ExactState, runtime: Runtime) -> ExactState:
    """Decide whether another research wave is warranted within iteration caps."""
    iteration = int(state.get("iteration") or 0)
    max_iter = int(state.get("max_iterations") or runtime.settings.max_iterations)
    titles = _titles(state.get("sources") or [])
    findings = state.get("findings") or []
    cap = int(state.get("max_topics_followup") or runtime.settings.max_topics_followup)
    if iteration + 1 >= max_iter:
        return _cap_exit(iteration, titles, findings)
    try:
        decision, usage = _ask(runtime, state, cap)
    except StructuredOutputError as exc:
        out = _cap_exit(iteration, titles, findings)
        out["errors"] = [str(exc)]
        return out
    out = _decision_update(decision, iteration, cap)
    out["prior_titles"] = titles
    out["usage"] = usage
    return out


def route_after_reflect(state: ExactState) -> ReflectRoute:
    if not state.get("continue_research"):
        return "write_report"
    return "plan_topics"
