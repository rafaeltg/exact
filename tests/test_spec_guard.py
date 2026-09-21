"""Tests for the complete-document specification gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_GUARD_PATH = (
    Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "spec-guard.py"
)


def _load_guard() -> ModuleType:
    """Load the hyphenated guard as a test module."""
    spec = importlib.util.spec_from_file_location("spec_guard", _GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


_SPEC = """# Demo specification

Topic: demo
Revision: 1
Status: Ready
Superseded by: None

## Goal

Provide one observable behavior.

## Requirements

### R1 — The behavior is available
- **Status:** active
- **Behavior:** The command returns the requested result.

## Out of scope

- Unrelated behavior.

## Decisions

### D1 — Use the existing command
- **Status:** active
- **Question:** Which command should change?
- **Answer:** The existing command.
- **Impact:** The command keeps its public entry point.
- **Evidence:** E1

## Repository evidence

- E1: repo:README.md#L1

## Acceptance criteria

- **R1:** The command returns the requested result.

## Open questions

None.
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a committed repository containing one valid specification."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / "README.md").write_text("Demo repository\n", encoding="utf-8")
    spec = tmp_path / "docs" / "specs" / "demo.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(_SPEC, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add specification")
    return tmp_path


def _git(root: Path, *args: str) -> None:
    """Run one Git command in a fixture repository."""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_valid_working_tree_specification_passes(repo: Path) -> None:
    """A complete specification passes the normal working-tree gate."""
    assert guard.check_file(repo / "docs/specs/demo.md") == []


def test_ready_requires_clean_committed_bytes(repo: Path) -> None:
    """Ready mode accepts the committed unchanged document."""
    assert guard.check_file(repo / "docs/specs/demo.md", "ready") == []


def test_missing_evidence_path_fails(repo: Path) -> None:
    """Repository evidence must resolve in the selected snapshot."""
    path = repo / "docs/specs/demo.md"
    path.write_text(_SPEC.replace("README.md", "missing.md"), encoding="utf-8")
    findings = guard.check_file(path)
    assert any("evidence path not found" in finding for finding in findings)


def test_direct_decision_evidence_is_checked(repo: Path) -> None:
    """Evidence written directly on a decision is also repository-grounded."""
    path = repo / "docs/specs/demo.md"
    changed = _SPEC.replace("**Evidence:** E1", "**Evidence:** repo:missing.md")
    path.write_text(changed, encoding="utf-8")
    assert any(
        "evidence path not found" in finding for finding in guard.check_file(path)
    )


def test_fenced_draft_marker_is_ignored(repo: Path) -> None:
    """Examples in a fenced block do not make a specification invalid."""
    path = repo / "docs/specs/demo.md"
    path.write_text(
        _SPEC.replace("## Goal", "```text\nTBD\n```\n\n## Goal"), encoding="utf-8"
    )
    assert not any("draft marker" in finding for finding in guard.check_file(path))


def test_index_mode_reads_staged_evidence(repo: Path) -> None:
    """Index mode does not mix an unstaged evidence edit into staged validation."""
    spec = repo / "docs/specs/demo.md"
    changed = _SPEC.replace("Revision: 1", "Revision: 2")
    spec.write_text(changed, encoding="utf-8")
    _git(repo, "add", "docs/specs/demo.md")
    (repo / "README.md").write_text("Unstaged replacement\n", encoding="utf-8")
    assert guard.check_file(spec, "index") == []


def test_invalid_status_open_questions_fails(repo: Path) -> None:
    """A ready specification cannot retain an open question."""
    path = repo / "docs/specs/demo.md"
    path.write_text(
        _SPEC.replace(
            "None.", "### Q1 — Need a choice\n- **Affects:** R1\n- **Evidence:** E1"
        ),
        encoding="utf-8",
    )
    assert any("Open questions" in finding for finding in guard.check_file(path))


def test_parent_symlink_evidence_is_rejected(repo: Path) -> None:
    """Evidence cannot use a directory symlink to leave the repository."""
    outside = repo.parent / "outside-evidence"
    outside.mkdir()
    (outside / "evidence.md").write_text("outside\n", encoding="utf-8")
    link = repo / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")
    path = repo / "docs/specs/demo.md"
    path.write_text(_SPEC.replace("README.md", "linked/evidence.md"), encoding="utf-8")
    assert any("symlink" in finding for finding in guard.check_file(path))


def test_duplicate_acceptance_reference_is_rejected(repo: Path) -> None:
    """One acceptance criterion cannot repeat one requirement ID."""
    path = repo / "docs/specs/demo.md"
    path.write_text(_SPEC.replace("**R1:**", "**R1, R1:**"), encoding="utf-8")
    assert any("repeats a requirement" in finding for finding in guard.check_file(path))


def test_superseded_requirement_cannot_be_accepted(repo: Path) -> None:
    """Acceptance criteria must target active requirements."""
    path = repo / "docs/specs/demo.md"
    changed = _SPEC.replace(
        "### R1 — The behavior is available\n- **Status:** active",
        "### R1 — The behavior is available\n- **Status:** superseded by R2\n"
        "- **Behavior:** The old command returns the requested result.\n\n"
        "### R2 — The replacement behavior\n- **Status:** active",
    )
    path.write_text(changed, encoding="utf-8")
    assert any(
        "superseded requirement" in finding for finding in guard.check_file(path)
    )


def test_question_affects_references_are_validated(repo: Path) -> None:
    """Open-question Affects references must name real requirements or decisions."""
    path = repo / "docs/specs/demo.md"
    changed = _SPEC.replace("Status: Ready", "Status: Draft", 1).replace(
        "None.", "### Q1 — Need a choice\n- **Affects:** R999\n- **Evidence:** E1"
    )
    path.write_text(changed, encoding="utf-8")
    assert any("unknown Affects" in finding for finding in guard.check_file(path))


def test_revision_increase_compares_numbers(repo: Path) -> None:
    """A revision bump from 9 to 10 is an increase, not a lexical decrease."""
    spec = repo / "docs/specs/demo.md"
    spec.write_text(_SPEC.replace("Revision: 1", "Revision: 9"), encoding="utf-8")
    _git(repo, "commit", "-qam", "revision 9")
    spec.write_text(_SPEC.replace("Revision: 1", "Revision: 10"), encoding="utf-8")
    assert guard.check_file(spec) == []
