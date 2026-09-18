"""Tests for the plan-artifact guard hook.

The guard is the only program that checks a plan's references. `/plan` Phase 6
still asks an LLM reviewer to verify the symbol and semantic rows, but the path,
test-name and make-target rows are this hook's job. A regression here either
stops reporting real dangling references or starts reporting good ones, and a
plan reviewer that gets one false finding stops reading the rest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_GUARD_PATH = (
    Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "plan-guard.py"
)


def _load_guard() -> ModuleType:
    """Import the hook by path: its filename is hyphenated, so it is not a module."""
    spec = importlib.util.spec_from_file_location("plan_guard", _GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


# ── Helpers ───────────────────────────────────────────────────────────


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway repo: a Makefile with one target and one test file."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / "Makefile").write_text(
        "test: ## Run pytest\n\t@pytest\n", encoding="utf-8"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "def test_a_long_scenario_name() -> None: ...\n"
        "async def test_b() -> None: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def _write_plan(tree: Path, body: str) -> Path:
    """Place a plan at the one path the guard audits."""
    folder = tree / ".claude" / "artifacts" / "plan" / "sample"
    folder.mkdir(parents=True, exist_ok=True)
    plan = folder / "plan.md"
    plan.write_text(body, encoding="utf-8")
    return plan


def _audit(tree: Path, body: str) -> list[str]:
    return guard.audit(_write_plan(tree, body), tree)


# ── Verify commands ───────────────────────────────────────────────────


def test_missing_test_path_is_a_finding(tree: Path) -> None:
    findings = _audit(tree, "**Verify:** `make test TEST=tests/test_gone.py`\n")
    assert len(findings) == 1
    assert "TEST=tests/test_gone.py" in findings[0]
    assert "path not found" in findings[0]


def test_test_path_outside_tests_is_a_finding(tree: Path) -> None:
    findings = _audit(tree, "**Verify:** `make test TEST=src/app.py`\n")
    assert len(findings) == 1
    assert "under tests/" in findings[0]


def test_absent_k_name_is_a_finding(tree: Path) -> None:
    findings = _audit(
        tree, "**Verify:** `make test TEST=tests/test_x.py K=test_nope`\n"
    )
    assert len(findings) == 1
    assert "K=test_nope" in findings[0]


def test_k_name_that_is_a_prefix_of_a_longer_test_is_clean(tree: Path) -> None:
    """Pytest `-k` matches substrings, so a prefix of a real name is valid."""
    assert (
        _audit(tree, "**Verify:** `make test TEST=tests/test_x.py K=test_a_long`\n")
        == []
    )


def test_quoted_k_expression_checks_every_identifier(tree: Path) -> None:
    body = "**Verify:** `make test TEST=tests/test_x.py K='test_a_long or test_b'`\n"
    assert _audit(tree, body) == []


def test_quoted_k_expression_reports_only_the_absent_identifier(tree: Path) -> None:
    body = "**Verify:** `make test TEST=tests/test_x.py K='test_b or test_nope'`\n"
    findings = _audit(tree, body)
    assert len(findings) == 1
    assert "K=test_nope" in findings[0]


def test_unknown_make_target_is_a_finding(tree: Path) -> None:
    findings = _audit(tree, "**Verify:** `make lint`\n")
    assert len(findings) == 1
    assert "make lint" in findings[0]


def test_test_selector_suffix_is_stripped_before_the_path_check(tree: Path) -> None:
    """`TEST=path::name` names one test; the path check needs the path alone."""
    assert _audit(tree, "**Verify:** `make test TEST=tests/test_x.py::test_b`\n") == []


def test_test_directory_collects_names_from_every_file(tree: Path) -> None:
    assert _audit(tree, "**Verify:** `make test TEST=tests K=test_b`\n") == []


def test_fenced_verify_block_is_parsed(tree: Path) -> None:
    body = (
        "**Verify:**\n"
        "```bash\n"
        "make test TEST=tests/test_x.py\n"
        "make test TEST=tests/test_gone.py\n"
        "```\n"
    )
    findings = _audit(tree, body)
    assert len(findings) == 1
    assert "test_gone.py" in findings[0]


def test_bullet_verify_list_is_parsed(tree: Path) -> None:
    body = (
        "**Verify:**\n"
        "- `make test TEST=tests/test_x.py` — the unit test\n"
        "- `make test TEST=tests/test_gone.py` — the wiring\n"
        "\nNext paragraph.\n"
    )
    findings = _audit(tree, body)
    assert len(findings) == 1
    assert "test_gone.py" in findings[0]


def test_prose_bullet_does_not_truncate_the_verify_list(tree: Path) -> None:
    """A bullet without a command is a skip: stopping would hide later bullets."""
    body = (
        "**Verify:**\n"
        "- `make test TEST=tests/test_x.py` — the unit test\n"
        "- read the report by hand\n"
        "- `make test TEST=tests/test_gone.py` — the wiring\n"
    )
    findings = _audit(tree, body)
    assert len(findings) == 1
    assert "test_gone.py" in findings[0]


def test_comment_line_in_a_fenced_block_is_not_a_command(tree: Path) -> None:
    body = "**Verify:**\n```bash\n# make sure the tree is clean\nmake test\n```\n"
    assert _audit(tree, body) == []


def test_absent_test_selector_is_a_finding(tree: Path) -> None:
    findings = _audit(tree, "**Verify:** `make test TEST=tests/test_x.py::test_gone`\n")
    assert len(findings) == 1
    assert "test_gone" in findings[0]


def test_test_selector_matches_exactly_not_by_substring(tree: Path) -> None:
    """A node id is exact: a prefix that `-k` would accept is not a node id."""
    findings = _audit(
        tree, "**Verify:** `make test TEST=tests/test_x.py::test_a_long`\n"
    )
    assert len(findings) == 1


@pytest.mark.parametrize(
    "filter_text",
    ["K=test_b", "K='test_b'", 'K="test_b"'],
    ids=["bare", "single-quoted", "double-quoted"],
)
def test_every_k_quoting_form_is_parsed(tree: Path, filter_text: str) -> None:
    body = f"**Verify:** `make test TEST=tests/test_x.py {filter_text}`\n"
    assert _audit(tree, body) == []


def test_parenthesised_k_expression_checks_each_identifier(tree: Path) -> None:
    body = "**Verify:** `make test TEST=tests/test_x.py K='(test_b or test_nope) and test_a'`\n"
    findings = _audit(tree, body)
    assert len(findings) == 1
    assert "K=test_nope" in findings[0]


def test_k_and_expression_checks_both_identifiers(tree: Path) -> None:
    body = "**Verify:** `make test TEST=tests/test_x.py K='test_b and test_nope'`\n"
    assert len(_audit(tree, body)) == 1


def test_k_name_after_not_is_an_exclusion_and_need_not_exist(tree: Path) -> None:
    """`-k 'a and not b'` runs when nothing matches b, so requiring b is false."""
    body = "**Verify:** `make test TEST=tests/test_x.py K='test_b and not test_nope'`\n"
    assert _audit(tree, body) == []


def test_make_flags_and_variables_are_not_read_as_targets(tree: Path) -> None:
    body = "**Verify:**\n```bash\nmake VERBOSE=1 test\n```\n"
    assert _audit(tree, body) == []


# ── Files fields ──────────────────────────────────────────────────────


def test_missing_modify_path_is_a_finding(tree: Path) -> None:
    findings = _audit(tree, "**Files:** modify: `src/gone.py`\n")
    assert len(findings) == 1
    assert "modify: src/gone.py" in findings[0]


def test_existing_create_path_is_a_finding(tree: Path) -> None:
    findings = _audit(tree, "**Files:** create: `src/app.py`\n")
    assert len(findings) == 1
    assert "already exists" in findings[0]


def test_mixed_files_field_checks_every_path(tree: Path) -> None:
    body = "**Files:** create: `src/new.py` | modify: `src/app.py`, `src/gone.py`\n"
    findings = _audit(tree, body)
    assert len(findings) == 1
    assert "modify: src/gone.py" in findings[0]


def test_comma_separated_files_field_keeps_each_kind(tree: Path) -> None:
    """A comma in place of `|` must not fold `modify:` paths into `create:`."""
    assert _audit(tree, "**Files:** create: `src/new.py`, modify: `src/app.py`\n") == []


def test_backticked_note_in_a_files_field_is_not_a_path(tree: Path) -> None:
    body = "**Files:** create: `src/new.py` (via `git mv`)\n"
    assert _audit(tree, body) == []


# ── Report shape and exit codes ───────────────────────────────────────


def test_findings_carry_the_plan_path_and_line(tree: Path) -> None:
    body = "# Plan\n\n**Files:** modify: `src/gone.py`\n"
    findings = _audit(tree, body)
    assert findings == [
        ".claude/artifacts/plan/sample/plan.md:3 → modify: src/gone.py"
        " → path not found in the tree"
    ]


def test_clean_plan_exits_zero(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = "**Files:** modify: `src/app.py`\n**Verify:** `make test TEST=tests/test_x.py`\n"
    plan = _write_plan(tree, body)
    assert guard.main([str(plan)]) == 0
    assert capsys.readouterr().out == ""


def test_plan_with_a_finding_exits_two_and_reports(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _write_plan(tree, "**Files:** modify: `src/gone.py`\n")
    assert guard.main([str(plan)]) == 2
    out = capsys.readouterr().out
    assert "src/gone.py" in out
    # `scripts/hooks/post-plan.sh` greps this line to tell findings from a
    # traceback. Reword it there and the hook fails open on every broken plan.
    assert "plan-check: 1 reference(s) do not resolve" in out


def test_path_outside_the_plan_directory_exits_zero(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tree / "notes.md"
    other.write_text("**Files:** modify: `src/gone.py`\n", encoding="utf-8")
    assert guard.main([str(other)]) == 0
    assert capsys.readouterr().out == ""


def test_missing_plan_fails_open(tree: Path) -> None:
    missing = tree / ".claude" / "artifacts" / "plan" / "sample" / "absent.md"
    missing.parent.mkdir(parents=True, exist_ok=True)
    assert guard.main([str(missing)]) == 0


def test_no_argument_is_a_usage_error(tree: Path) -> None:
    assert guard.main([]) == 1


def test_two_arguments_are_a_usage_error(tree: Path) -> None:
    plan = _write_plan(tree, "# Plan\n")
    assert guard.main([str(plan), str(plan)]) == 1


def test_undecodable_plan_fails_open(tree: Path) -> None:
    """A bad byte is a ValueError, not an OSError — the fail-open must cover it."""
    plan = _write_plan(tree, "# Plan\n")
    plan.write_bytes(b"**Files:** modify: `src/\xff.py`\n")
    assert guard.main([str(plan)]) == 0
