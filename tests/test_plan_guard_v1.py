"""Tests for the canonical v1 plan gate."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_GUARD_PATH = (
    Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "plan-guard.py"
)


def _load_guard() -> ModuleType:
    """Load the hyphenated plan guard."""
    spec = importlib.util.spec_from_file_location("plan_guard_v1", _GUARD_PATH)
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

Do the demo behavior.

## Requirements

### R1 — Demo behavior
- **Status:** active
- **Behavior:** The demo behavior works.

## Out of scope

- Other behavior.

## Decisions

### D1 — Keep the existing entry point
- **Status:** active
- **Question:** Which entry point changes?
- **Answer:** The existing entry point.
- **Impact:** The public entry point stays stable.
- **Evidence:** person-decision

## Repository evidence

- E1: person-decision

## Acceptance criteria

- **R1:** The behavior works.

## Open questions

None.
"""


def _git(root: Path, *args: str) -> str:
    """Run Git and return stdout."""
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """Create a clean committed repository for strict plan checks."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".gitignore").write_text(".claude/artifacts/\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_existing.py").write_text(
        "def test_existing() -> None:\n    pass\n", encoding="utf-8"
    )
    spec = tmp_path / "docs/specs/demo.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(_SPEC, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def _plan(repo: Path, commit: str, body: str | None = None) -> Path:
    """Write one canonical plan and its workflow marker."""
    spec = repo / "docs/specs/demo.md"
    plan = repo / ".claude/artifacts/plan/demo/plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    (plan.parent / ".spec-plan-v1").write_bytes(b"version=1\n")
    content = (
        body
        or f"""# Demo — plan

Spec: docs/specs/demo.md
Spec revision: 1
Spec SHA-256: {hashlib.sha256(spec.read_bytes()).hexdigest()}
Repository commit: {commit}
Date: 2026-09-19

## Scope boundaries

- Change only the demo behavior.

## Phases

### Phase 1 — Demo behavior
**Goal:** Deliver the demo behavior.
**Stop condition:** The demo behavior is usable.
**Owns files:** `README.md`, `tests/test_new.py`
**Provides:** The new test.
**Acceptance criteria:**
- [ ] The demo behavior works.
- [ ] Full integration gate passes: `make check`

## Tasks

### Task 1.1 — Add the demo test
**Decisions:** D1
**Do:** Add the test for the demo behavior.
**Files:** create: `tests/test_new.py` | modify: `README.md`
**Provides:** test: `tests/test_new.py::test_new`
**Verify:** `make test TEST=tests/test_new.py K=test_new`
"""
    )
    plan.write_text(content, encoding="utf-8")
    return plan


def test_valid_canonical_plan_passes(repo: tuple[Path, str]) -> None:
    """The canonical plan with a same-task test provider passes."""
    root, commit = repo
    assert guard.strict_audit(_plan(root, commit), root) == []


def test_missing_marker_is_rejected(repo: tuple[Path, str]) -> None:
    """A legacy topic directory cannot enter the new workflow."""
    root, commit = repo
    plan = _plan(root, commit)
    (plan.parent / ".spec-plan-v1").unlink()
    assert any("marker" in finding for finding in guard.strict_audit(plan, root))


def test_provider_is_available_to_a_later_task(repo: tuple[Path, str]) -> None:
    """A later task may modify and verify an earlier task's produced test."""
    root, commit = repo
    plan = _plan(root, commit)
    text = plan.read_text(encoding="utf-8").replace(
        "**Verify:** `make test TEST=tests/test_new.py K=test_new`\n",
        "**Verify:** `make test TEST=tests/test_new.py K=test_new`\n\n"
        "### Task 1.2 — Update the demo test\n"
        "**Decisions:** None\n"
        "**Do:** Update the demo test.\n"
        "**Files:** modify: `tests/test_new.py`\n"
        "**Provides:** None\n"
        "**Verify:** `make test TEST=tests/test_new.py K=test_new`\n",
    )
    plan.write_text(text, encoding="utf-8")
    assert guard.strict_audit(plan, root) == []


def test_unsupported_verify_shell_syntax_is_rejected(repo: tuple[Path, str]) -> None:
    """The guard rejects a command when any shell operator is present."""
    root, commit = repo
    plan = _plan(root, commit)
    text = plan.read_text(encoding="utf-8").replace(
        "`make test TEST=tests/test_new.py K=test_new`",
        "`make test TEST=tests/test_new.py K=test_new && make check`",
    )
    plan.write_text(text, encoding="utf-8")
    assert any("shell syntax" in finding for finding in guard.strict_audit(plan, root))


def test_approved_review_must_match_the_plan(repo: tuple[Path, str]) -> None:
    """An approved review with the current digest passes the optional review gate."""
    root, commit = repo
    plan = _plan(root, commit)
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    (plan.parent / "review.md").write_text(
        f"Reviewer: independent\nPlan SHA-256: {digest}\nDate: 2026-09-19\n"
        "Status: Approved\nTask 1.1 → references → README.md → non-blocking\n",
        encoding="utf-8",
    )
    assert guard.strict_audit(plan, root) == []


def test_blocking_review_fails_the_gate(repo: tuple[Path, str]) -> None:
    """A review with a blocking row cannot approve a plan."""
    root, commit = repo
    plan = _plan(root, commit)
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    (plan.parent / "review.md").write_text(
        f"Reviewer: independent\nPlan SHA-256: {digest}\nDate: 2026-09-19\n"
        "Status: Approved\nTask 1.1 → false claim → README.md → blocking\n",
        encoding="utf-8",
    )
    assert any(
        "blocking finding" in finding for finding in guard.strict_audit(plan, root)
    )


def test_plan_draft_marker_is_rejected(repo: tuple[Path, str]) -> None:
    """A task cannot retain a draft marker."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("Add the test", "TODO: add the test"),
        encoding="utf-8",
    )
    assert any("draft marker" in finding for finding in guard.strict_audit(plan, root))


def test_task_files_must_belong_to_their_phase(repo: tuple[Path, str]) -> None:
    """A task cannot edit a file outside its phase ownership list."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "**Owns files:** `README.md`, `tests/test_new.py`",
            "**Owns files:** `README.md`",
        ),
        encoding="utf-8",
    )
    assert any(
        "outside phase ownership" in finding
        for finding in guard.strict_audit(plan, root)
    )
