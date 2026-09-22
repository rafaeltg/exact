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
**Requirements:** R1
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
        "**Requirements:** None\n"
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


def test_sentence_over_the_word_limit_is_rejected(repo: tuple[Path, str]) -> None:
    """A plan sentence stays inside the ASD-STE100 descriptive limit."""
    root, commit = repo
    plan = _plan(root, commit)
    long_sentence = "Add the test and " + " ".join(f"word{n}" for n in range(24))
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "Add the test for the demo behavior.", long_sentence + "."
        ),
        encoding="utf-8",
    )
    findings = guard.strict_audit(plan, root)
    assert any("sentence is over 25 words" in finding for finding in findings)


def test_comma_separated_code_spans_count_as_one_word(
    repo: tuple[Path, str],
) -> None:
    """A list of code spans is one term. It is not one word per span."""
    root, commit = repo
    plan = _plan(root, commit)
    spans = ", ".join(f"`value{n}`" for n in range(24))
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "Add the test for the demo behavior.", f"Add the values {spans}."
        ),
        encoding="utf-8",
    )
    assert not any(
        "over 25 words" in finding for finding in guard.strict_audit(plan, root)
    )


def test_filler_at_a_sentence_start_is_rejected(repo: tuple[Path, str]) -> None:
    """Filler changes no keystroke for the executor."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "Add the test for the demo behavior.",
            "Add the test. Note that the demo behavior is new.",
        ),
        encoding="utf-8",
    )
    assert any("filler" in finding for finding in guard.strict_audit(plan, root))


def test_filler_words_inside_a_sentence_are_not_filler(
    repo: tuple[Path, str],
) -> None:
    """`note that` mid-sentence is ordinary English, not an opening phrase."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "Add the test for the demo behavior.",
            "Add an exclude note that names the demo behavior.",
        ),
        encoding="utf-8",
    )
    assert not any("filler" in finding for finding in guard.strict_audit(plan, root))


def test_planned_red_language_is_rejected(repo: tuple[Path, str]) -> None:
    """A task that admits a red tree hides a window where bugs live."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "Add the test for the demo behavior.",
            "Add the test. It will fail until task 1.2 lands.",
        ),
        encoding="utf-8",
    )
    assert any("planned-red" in finding for finding in guard.strict_audit(plan, root))


def test_planned_red_inside_a_code_span_is_not_language(
    repo: tuple[Path, str],
) -> None:
    """A test name that reads like planned-red language is a name, not a claim."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "Add the test for the demo behavior.",
            "Add `test_the_request_is_expected_to_fail` for the demo behavior.",
        ),
        encoding="utf-8",
    )
    assert not any(
        "planned-red" in finding for finding in guard.strict_audit(plan, root)
    )


def test_task_requirement_must_be_active(repo: tuple[Path, str]) -> None:
    """A task cites an active requirement of the recorded specification."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "**Requirements:** R1", "**Requirements:** R9"
        ),
        encoding="utf-8",
    )
    findings = guard.strict_audit(plan, root)
    assert any("unknown active requirement R9" in finding for finding in findings)


def test_active_requirement_without_a_task_is_rejected(
    repo: tuple[Path, str],
) -> None:
    """Requirement coverage is deterministic, not a reviewer judgement."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "**Requirements:** R1", "**Requirements:** None"
        ),
        encoding="utf-8",
    )
    findings = guard.strict_audit(plan, root)
    assert any("active requirement R1 has no task" in finding for finding in findings)


def test_missing_requirements_field_is_rejected(repo: tuple[Path, str]) -> None:
    """Every task carries every canonical field."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("**Requirements:** R1\n", ""),
        encoding="utf-8",
    )
    findings = guard.strict_audit(plan, root)
    assert any("missing Requirements" in finding for finding in findings)


def test_init_writes_the_marker_and_reports_the_metadata(
    repo: tuple[Path, str],
) -> None:
    """A new topic gets the marker and the five metadata lines of the head."""
    root, commit = repo
    digest = hashlib.sha256((root / "docs/specs/demo.md").read_bytes()).hexdigest()
    findings, report = guard.plan_init(root, "demo")
    assert findings == []
    assert report[0].endswith("(new)")
    assert f"Spec SHA-256: {digest}" in report
    assert f"Repository commit: {commit}" in report
    assert "Spec revision: 1" in report
    marker = root / ".claude/artifacts/plan/demo/.spec-plan-v1"
    assert marker.read_bytes() == b"version=1\n"
    # `post-bash.sh` gates a shell write to this plan only while the stamp exists.
    assert (root / ".claude/artifacts/plan/demo/.plan-checked").is_file()


def test_init_rejects_an_unsafe_topic(repo: tuple[Path, str]) -> None:
    """An invalid slug writes outside the plan directory."""
    root, _commit = repo
    findings, report = guard.plan_init(root, "../escape")
    assert any("not a safe slug" in finding for finding in findings)
    assert report == []


def test_init_stops_on_a_dirty_tree(repo: tuple[Path, str]) -> None:
    """A dirty tree breaks the Repository commit the plan records."""
    root, _commit = repo
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    findings, _report = guard.plan_init(root, "demo")
    assert "repository is not clean" in findings
    assert not (root / ".claude/artifacts/plan/demo").exists()


def test_init_stops_on_a_draft_specification(repo: tuple[Path, str]) -> None:
    """`/plan` consumes a Ready specification only, and says why it stopped."""
    root, _commit = repo
    spec = root / "docs/specs/demo.md"
    spec.write_text(_SPEC.replace("Status: Ready", "Status: Draft"), encoding="utf-8")
    _git(root, "commit", "-qam", "draft")
    findings, _report = guard.plan_init(root, "demo")
    assert any("requires Status: Ready" in finding for finding in findings)


def test_init_stops_on_a_missing_specification(repo: tuple[Path, str]) -> None:
    """The only specification is the one the topic names."""
    root, _commit = repo
    findings, _report = guard.plan_init(root, "absent")
    assert findings == ["specification does not exist: docs/specs/absent.md"]


def test_init_reports_a_current_plan(repo: tuple[Path, str]) -> None:
    """A plan written for this specification revision is current."""
    root, commit = repo
    _plan(root, commit)
    findings, report = guard.plan_init(root, "demo")
    assert findings == []
    assert report[0].endswith("(current)")


def test_init_reports_a_stale_plan(repo: tuple[Path, str]) -> None:
    """A plan for another revision is a state the user resolves, not a finding."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("Spec SHA-256: ", "Spec SHA-256: a"),
        encoding="utf-8",
    )
    findings, report = guard.plan_init(root, "demo")
    assert findings == []
    assert report[0].endswith("(stale)")


def test_init_stops_on_an_older_plan_format(repo: tuple[Path, str]) -> None:
    """A directory without the marker holds a plan of the older format."""
    root, commit = repo
    plan = _plan(root, commit)
    (plan.parent / ".spec-plan-v1").unlink()
    findings, _report = guard.plan_init(root, "demo")
    assert any("older plan format" in finding for finding in findings)


def test_init_exit_codes(
    repo: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean gate exits 0 and prints the report; a finding exits 2."""
    root, _commit = repo
    assert guard.main(["--init", "demo"]) == 0
    assert (
        "Plan directory: .claude/artifacts/plan/demo/ (new)" in capsys.readouterr().out
    )
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    assert guard.main(["--init", "demo"]) == 2
    printed = capsys.readouterr().out
    assert "repository is not clean" in printed
    # The specification gate's own finding reaches the agent, not a bare verdict.
    assert "specification fails spec-check-ready: ready specification" in printed


def test_usage_error_without_a_mode(repo: tuple[Path, str]) -> None:
    """The guard has two modes, and neither is the default."""
    root, commit = repo
    assert guard.main([str(_plan(root, commit))]) == 1


def test_init_rejects_a_symlinked_topic_directory(repo: tuple[Path, str]) -> None:
    """The marker and the stamp must not be written outside the repository."""
    root, _commit = repo
    outside = root.parent / "outside-plan"
    outside.mkdir()
    link = root / ".claude/artifacts/plan/demo"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")
    findings, report = guard.plan_init(root, "demo")
    assert any("must not be a symlink" in finding for finding in findings)
    assert report == []
    assert not (outside / ".spec-plan-v1").exists()


def test_unclosed_fence_is_rejected(repo: tuple[Path, str]) -> None:
    """An unclosed fence would mask every sentence after it."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8") + "\n```text\nnot closed\n", encoding="utf-8"
    )
    assert any(
        "unclosed code fence" in finding for finding in guard.strict_audit(plan, root)
    )


def test_a_table_row_is_not_prose(repo: tuple[Path, str]) -> None:
    """A table row carries no sentence, so its cells are not counted as one."""
    root, commit = repo
    plan = _plan(root, commit)
    row = "| " + " | ".join(f"cell{n} value{n}" for n in range(14)) + " |"
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "- Change only the demo behavior.",
            f"- Change only the demo behavior.\n\n{row}",
        ),
        encoding="utf-8",
    )
    assert not any("over 25 words" in f for f in guard.strict_audit(plan, root))


def test_a_provided_test_resolves_under_a_tests_subdirectory(
    repo: tuple[Path, str],
) -> None:
    """A `TEST=` directory sees a test an earlier task provides inside it."""
    root, commit = repo
    (root / "tests/sub").mkdir()
    (root / "tests/sub/test_existing.py").write_text(
        "def test_existing() -> None:\n    pass\n", encoding="utf-8"
    )
    _git(root, "add", "tests/sub")
    _git(root, "commit", "-qm", "subdirectory")
    commit = _git(root, "rev-parse", "HEAD")
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8")
        .replace("tests/test_new.py", "tests/sub/test_new.py")
        .replace("TEST=tests/sub/test_new.py", "TEST=tests/sub"),
        encoding="utf-8",
    )
    assert guard.strict_audit(plan, root) == []


def test_a_malformed_files_field_reports_one_defect(repo: tuple[Path, str]) -> None:
    """A segment that does not parse is one finding, never a repeated kind."""
    root, commit = repo
    plan = _plan(root, commit)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "create: `tests/test_new.py`", "create `tests/test_new.py`"
        ),
        encoding="utf-8",
    )
    findings = guard.strict_audit(plan, root)
    assert any("invalid Files field" in finding for finding in findings)
    assert not any("kinds must occur once" in finding for finding in findings)


def test_a_stale_repository_commit_stops_the_task_pass(
    repo: tuple[Path, str],
) -> None:
    """Every task reference resolves against HEAD, so another commit cascades."""
    root, base = repo
    (root / "EXTRA.md").write_text("later\n", encoding="utf-8")
    _git(root, "add", "EXTRA.md")
    _git(root, "commit", "-qm", "extra")
    later = _git(root, "rev-parse", "HEAD")
    plan = _plan(root, later)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("README.md", "EXTRA.md"),
        encoding="utf-8",
    )
    _git(root, "reset", "-q", "--hard", base)

    findings = guard.strict_audit(plan, root)

    assert findings == ["Repository commit does not match HEAD"]
