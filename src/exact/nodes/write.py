from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from exact import prompts
from exact.config import Runtime, role_model_id
from exact.models import ExactState, JsonMapping, focus_label
from exact.prefs import state_prefs
from exact.usage import invoke_text


def _location(source: JsonMapping, label: str) -> str:
    """Where the source lives; a paper shows its DOI beside its URL."""
    url = str(source.get("url") or "")
    doi = str(source.get("doi") or "")
    # A doi.org resolver url already spells the DOI; do not print it twice.
    # A DOI is case-insensitive and publishers mix case, so fold both sides.
    if label == "publication" and url and doi and doi.casefold() not in url.casefold():
        return f"{url} — doi:{doi}"
    return url or doi


def _reference_line(source: JsonMapping) -> str:
    label = focus_label(source)
    title = source.get("title") or "untitled"
    sid = source.get("id") or "?"
    loc = _location(source, label)
    extra = f" — {loc}" if loc else ""
    tag = f" ({label})" if label else ""
    return f"[{sid}] {title}{extra}{tag}"


def format_references(sources: Sequence[JsonMapping] | None) -> list[str]:
    """CLI ``## References`` lines from retrieved sources (stable, not LLM text)."""
    items = sources or []
    if not items:
        return []
    return ["## References", *(_reference_line(s) for s in items)]


def _all_gaps(state: ExactState) -> list[str]:
    gaps = list(state.get("uncovered") or [])
    for finding in state.get("findings") or []:
        gaps.extend(finding.get("gaps") or [])
    return list(dict.fromkeys(gaps))


def _bib_block(sources: Sequence[JsonMapping]) -> str:
    lines = format_references(sources)
    if not lines:
        return "(none)"
    return "\n".join(lines[1:])


def write_report(state: ExactState, runtime: Runtime) -> ExactState:
    """Draft the Markdown report; bibliography is appended by the CLI, not the LLM."""
    text, usage = invoke_text(
        runtime.model("write"),
        [
            SystemMessage(
                content=prompts.WRITE.format(
                    brief=state.get("brief") or {},
                    findings=prompts.findings_block(state.get("findings")),
                    bib=_bib_block(state.get("sources") or []),
                    style=prompts.write_style(
                        state_prefs(state), state.get("initial_query") or ""
                    ),
                )
            ),
            HumanMessage(content="Write the report."),
        ],
        node="write_report",
        role="write",
        model_id=role_model_id(runtime.settings, "write"),
    )
    return {"final_report": text, "uncovered": _all_gaps(state), "usage": usage}
