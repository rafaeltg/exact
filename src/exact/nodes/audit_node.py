from __future__ import annotations

from exact.audit import audit_report
from exact.models import ExactState


def audit_citations(state: ExactState) -> ExactState:
    """Code-only citation check; record dangling ids under ``uncovered``."""
    report, dangling = audit_report(
        state.get("final_report") or "", state.get("sources") or []
    )
    uncovered = list(state.get("uncovered") or [])
    if dangling:
        uncovered = uncovered + [f"dangling:{d}" for d in dangling]
    return {"final_report": report, "uncovered": uncovered}
