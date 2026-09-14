from __future__ import annotations

from exact.audit import audit_report
from exact.nodes.audit_node import audit_citations


def test_every_src_citation_resolves_when_ids_match():
    report, dangling = audit_report("Hello [src_t0_1_1].", [{"id": "src_t0_1_1"}])
    assert dangling == []
    assert report == "Hello [src_t0_1_1]."
    assert "## Audit" not in report


def test_dangling_src_citation_appends_audit_section():
    report, dangling = audit_report("Hello [src_9].", [{"id": "src_1"}])
    assert dangling == ["src_9"]
    assert "## Audit" in report
    assert "`[src_9]`" in report


def test_empty_report_has_no_dangling_citations():
    report, dangling = audit_report("", [{"id": "src_t0_1_1"}])
    assert dangling == []
    assert report == ""


def test_none_report_is_treated_as_empty():
    report, dangling = audit_report(None, [{"id": "src_t0_1_1"}])
    assert dangling == []
    assert report == ""


def test_duplicate_dangling_citations_are_listed_once():
    _, dangling = audit_report("[src_a] and [src_a].", [])
    assert dangling == ["src_a"]


def test_multiple_dangling_citations_are_sorted():
    _, dangling = audit_report("[src_b] [src_a].", [])
    assert dangling == ["src_a", "src_b"]


def test_source_without_id_does_not_resolve_a_citation():
    _, dangling = audit_report("Hi [src_t0_1_1].", [{"title": "Source A"}])
    assert dangling == ["src_t0_1_1"]


def test_dangling_citations_are_recorded_in_uncovered():
    out = audit_citations(
        {
            "final_report": "Hi [src_missing].",
            "sources": [{"id": "src_t0_1_1"}],
            "uncovered": ["existing gap"],
        }
    )
    assert out["uncovered"] == ["existing gap", "dangling:src_missing"]
    assert "## Audit" in out["final_report"]


def test_resolved_citations_leave_uncovered_unchanged():
    out = audit_citations(
        {
            "final_report": "Hi [src_t0_1_1].",
            "sources": [{"id": "src_t0_1_1"}],
            "uncovered": ["existing gap"],
        }
    )
    assert out["uncovered"] == ["existing gap"]
    assert out["final_report"] == "Hi [src_t0_1_1]."
