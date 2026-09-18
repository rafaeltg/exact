from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import (
    ClarificationOption,
    ClarifyDecision,
    ExactState,
    JsonMapping,
    UserClarification,
    focus_label,
)
from exact.usage import StructuredOutputError, invoke_structured

type DecideRoute = Literal["ask_user", "generate_brief"]
type AskRoute = Literal["decide_clarify", "generate_brief"]


def _scout_block(hits: list[dict]) -> str:
    if not hits:
        return "(no scout hits)"
    lines = []
    for h in hits[:8]:
        lines.append(
            f"- {h.get('title')} [{focus_label(h)}] {h.get('snippet', '')[:200]}"
        )
    return "\n".join(lines)


def _from_dict(raw: dict) -> UserClarification:
    kind = raw.get("kind")
    if kind not in ("skip", "pick", "text"):
        return UserClarification(kind="skip")
    return UserClarification(
        kind=kind,
        option_ids=raw.get("option_ids") or [],
        text=raw.get("text"),
    )


def _from_text(text: str, options: list[dict]) -> UserClarification:
    if not text or text.lower() in {"skip", "s", "n", "no"}:
        return UserClarification(kind="skip")
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(options):
            oid = options[idx].get("id") or f"opt_{idx + 1}"
            return UserClarification(kind="pick", option_ids=[oid])
        return UserClarification(kind="skip")
    return UserClarification(kind="text", text=text)


def parse_resume(raw: object, options: Sequence[JsonMapping]) -> UserClarification:
    """Parse an interrupt resume value into skip, pick, or free-text clarification."""
    if raw is None or raw == "":
        return UserClarification(kind="skip")
    if isinstance(raw, dict):
        return _from_dict(raw)
    return _from_text(str(raw).strip(), list(options))


def _clarify_cap(state: ExactState, default: int = 3) -> int:
    return int(state.get("max_clarify_turns") or default)


def _cites_scout(question: str, hits: list[dict]) -> bool:
    for hit in hits:
        title = (hit.get("title") or "").strip()
        if title and title in question:
            return True
    return False


def _options(decision: ClarifyDecision) -> list[dict]:
    options = [o.model_dump() for o in decision.options]
    if options:
        return options
    return [ClarificationOption(id="opt_1", label="Proceed as stated").model_dump()]


def _skip_clarify(
    usage: list[dict] | None = None, *, errors: list[str] | None = None
) -> ExactState:
    out: ExactState = {
        "clarify_needed": False,
        "clarification_options": [],
        "usage": usage or [],
    }
    if errors:
        out["errors"] = errors
    return out


def _ask_decision(
    state: ExactState, runtime: Runtime, hits: list[dict]
) -> tuple[ClarifyDecision, list[dict]]:
    return invoke_structured(
        runtime.model("router"),
        ClarifyDecision,
        [
            SystemMessage(
                content=prompts.DECIDE_CLARIFY.format(
                    query=state["initial_query"],
                    scout=_scout_block(hits),
                    chat=prompts.chat_block(state.get("messages")),
                )
            ),
            HumanMessage(content="Decide whether to clarify."),
        ],
        node="decide_clarify",
        role="router",
        model_id=role_model_id(runtime.settings, "router"),
    )


def decide_clarify(state: ExactState, runtime: Runtime) -> ExactState:
    """Decide whether to interrupt; skip when scout titles are not cited."""
    if state.get("skip_clarify"):
        return {"clarify_needed": False}
    turns = int(state.get("clarify_turns") or 0)
    cap = _clarify_cap(state, runtime.settings.max_clarify_turns)
    if turns >= cap:
        return {"clarify_needed": False}
    hits = state.get("scout_hits") or []
    try:
        decision, usage = _ask_decision(state, runtime, hits)
    except StructuredOutputError as exc:
        return _skip_clarify(errors=[str(exc)])
    if not decision.needed:
        return _skip_clarify(usage)
    if hits and not _cites_scout(decision.question, hits):
        return _skip_clarify(usage)
    return {
        "clarify_needed": True,
        "clarify_question": decision.question,
        "clarification_options": _options(decision),
        "usage": usage,
    }


def ask_user(state: ExactState) -> ExactState:
    """Interrupt for user clarification and record the resume payload."""
    options = state.get("clarification_options") or []
    question = state.get("clarify_question") or "Clarify the research angle."
    raw = interrupt(
        {
            "question": question,
            "options": options,
            "scout_preview": [
                h.get("title") for h in (state.get("scout_hits") or [])[:5]
            ],
        }
    )
    parsed = parse_resume(raw, options)
    turns = int(state.get("clarify_turns") or 0) + 1
    note = parsed.text or ",".join(parsed.option_ids) or parsed.kind
    needed = parsed.kind != "skip" and turns < _clarify_cap(state)
    return {
        "user_clarification": parsed.model_dump(),
        "clarify_turns": turns,
        "clarify_needed": needed,
        "messages": [
            AIMessage(content=question),
            HumanMessage(content=f"User clarification ({parsed.kind}): {note}"),
        ],
    }


def route_after_decide(state: ExactState) -> DecideRoute:
    return "ask_user" if state.get("clarify_needed") else "generate_brief"


def route_after_ask(state: ExactState) -> AskRoute:
    if (state.get("user_clarification") or {}).get("kind") == "skip":
        return "generate_brief"
    if int(state.get("clarify_turns") or 0) >= _clarify_cap(state):
        return "generate_brief"
    if state.get("clarify_needed"):
        return "decide_clarify"
    return "generate_brief"
