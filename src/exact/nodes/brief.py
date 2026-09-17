from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.intent import academic_signal
from exact.models import ExactState, ResearchBrief
from exact.usage import StructuredOutputError, invoke_structured


def _scout_text(hits: list[dict]) -> str:
    lines = [
        f"- {h.get('title')} [{h.get('provider')}] {h.get('snippet', '')[:180]}"
        for h in hits[:8]
    ]
    return "\n".join(lines) or "(none)"


def _pick_text(state: ExactState) -> str:
    clarification = state.get("user_clarification") or {}
    if clarification.get("kind") != "pick":
        return ""
    options = {opt.get("id"): opt for opt in (state.get("clarification_options") or [])}
    parts: list[str] = []
    for option_id in clarification.get("option_ids") or []:
        opt = options.get(option_id) or {}
        parts.append(f"{opt.get('label') or ''} {opt.get('description') or ''}")
    return " ".join(parts)


def _user_chat(state: ExactState) -> str:
    """The user-authored side of the clarify thread.

    ``user_clarification`` is a LastValue channel, so it holds the latest turn
    only. The thread keeps every turn, but it also holds the question the
    router asked; that wording must not decide the intent.
    """
    return "\n".join(
        str(getattr(m, "content", "") or "")
        for m in state.get("messages") or []
        if getattr(m, "type", None) == "human"
    )


def _has_academic_signal(query: str, state: ExactState) -> bool:
    """Spec §5: query, clarification text, or a picked option only."""
    clarification = state.get("user_clarification") or {}
    text = clarification.get("text") or ""
    return bool(
        academic_signal(query)
        or academic_signal(text)
        or academic_signal(_pick_text(state))
        or academic_signal(_user_chat(state))
    )


def _normalize(brief: ResearchBrief, query: str, state: ExactState) -> ResearchBrief:
    if brief.intent == "web" and _has_academic_signal(query, state):
        brief.intent = "academic"
    if not brief.must_cover:
        brief.must_cover = [brief.question or query]
    return brief


def _fallback_brief(query: str, state: ExactState) -> ResearchBrief:
    intent = "academic" if _has_academic_signal(query, state) else "web"
    return _normalize(
        ResearchBrief(question=query, intent=intent, must_cover=[query]),
        query,
        state,
    )


def generate_brief(state: ExactState, runtime: Runtime) -> ExactState:
    """Compress query, scout, and chat into the research brief."""
    query = state["initial_query"]
    try:
        brief, usage = invoke_structured(
            runtime.model("compress"),
            ResearchBrief,
            [
                SystemMessage(
                    content=prompts.BRIEF.format(
                        query=query,
                        scout=_scout_text(state.get("scout_hits") or []),
                        chat=prompts.chat_block(state.get("messages")),
                    )
                ),
                HumanMessage(content="Produce the brief."),
            ],
            node="generate_brief",
            role="compress",
            model_id=role_model_id(runtime.settings, "compress"),
        )
        errors: list[str] = []
    except StructuredOutputError as exc:
        brief = _fallback_brief(query, state)
        usage = []
        errors = [str(exc)]
    return {
        "brief": _normalize(brief, query, state).model_dump(),
        "iteration": 0,
        "errors": errors,
        "usage": usage,
    }
