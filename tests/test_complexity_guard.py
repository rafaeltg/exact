"""Tests for the complexity guard hook.

The guard is the only enforcement of the complexity budgets. It runs from
Cursor ``preToolUse --pre`` (deny before write), post-edit advisory hooks
(TabWrite), and pre-commit via ``--check``. A regression here silently
either stops blocking real violations or starts blocking valid edits.
These tests are that safety net.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_GUARD_PATH = (
    Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "complexity-guard.py"
)


def _load_guard() -> ModuleType:
    """Import the hook by path: its filename is hyphenated, so it is not a module.

    The module is registered in ``sys.modules`` before execution because
    unregistered modules have a ``__name__`` that some stdlib helpers
    cannot resolve.
    """
    spec = importlib.util.spec_from_file_location("complexity_guard", _GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


# ── Helpers ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the run log at a throwaway file.

    Autouse on purpose: without it every test that calls `main()` appends to
    the repository's own log.
    """
    path = tmp_path / "complexity-guard.jsonl"
    monkeypatch.setattr(guard, "LOG_PATH", path)
    return path


def _measure(source: str, name: str = "f") -> dict[str, int]:
    """Every budget `name` in `source` exceeds, as the guard measures it."""
    tree = ast.parse(source)
    lines = guard._source_lines(source.encode())
    func = next(fn for fn_name, fn in guard._collect_functions(tree) if fn_name == name)
    return guard._over_budget(func, lines)


def _names(source: str) -> list[str]:
    """The qualified names the guard assigns to every function in `source`."""
    return [name for name, _ in guard._collect_functions(ast.parse(source))]


def _run_main(
    monkeypatch: pytest.MonkeyPatch, payload: object, raw: str | None = None
) -> int:
    """Feed `payload` to main() over stdin and return its exit code."""
    import io

    text = raw if raw is not None else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    return guard.main()


def _run_pre(
    monkeypatch: pytest.MonkeyPatch, payload: object, raw: str | None = None
) -> int:
    """Feed `payload` to pre_main() over stdin and return its exit code."""
    import io

    text = raw if raw is not None else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    return guard.pre_main()


def _permission(capsys: pytest.CaptureFixture) -> dict:
    """Parse the preToolUse JSON verdict from stdout."""
    out = capsys.readouterr().out.strip().splitlines()[-1]
    return json.loads(out)


def _records(path: Path) -> list[dict]:
    """Every record the run log holds."""
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _violating_file(tmp_path: Path) -> Path:
    """A file whose only function breaches the parameter budget."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "bad.py"
    target.write_text(f"def f({params}):\n    return 1\n")
    return target


# ── Metric counting ───────────────────────────────────────────────────


def test_simple_function_breaches_nothing() -> None:
    """A trivial function must not be reported; a false positive blocks real work."""
    assert _measure("def f(a):\n    return a\n") == {}


def test_cyclomatic_complexity_counts_branch_points() -> None:
    """Each if/and/or adds one, so 11 branch points exceed the budget of 10."""
    body = "\n".join(f"    if a == {i}:\n        return {i}" for i in range(11))
    over = _measure(f"def f(a):\n{body}\n    return None\n")
    assert over["cyclomatic complexity"] == 12


def test_complexity_at_the_limit_does_not_breach() -> None:
    """The budget is inclusive: exactly MAX_COMPLEXITY is allowed."""
    body = "\n".join(f"    if a == {i}:\n        return {i}" for i in range(9))
    over = _measure(f"def f(a):\n{body}\n    return None\n")
    assert "cyclomatic complexity" not in over


def test_boolean_operators_count_as_branches() -> None:
    """`and`/`or` short-circuit, so each is a branch the budget must see."""
    condition = " and ".join(f"a != {i}" for i in range(12))
    over = _measure(f"def f(a):\n    if {condition}:\n        return 1\n    return 0\n")
    assert over["cyclomatic complexity"] > guard.MAX_COMPLEXITY


def test_function_length_excludes_docstring_blanks_and_comments() -> None:
    """Explaining an invariant at length must not read as complexity."""
    source = 'def f():\n    """Doc.\n\n    More.\n    """\n' + "\n".join(
        f"    # comment {i}\n\n    x = {i}" for i in range(20)
    )
    over = _measure(source + "\n")
    # 20 real code lines plus the `def`, well under the 40-line budget, even
    # though the file spans ~65 physical lines.
    assert "function length" not in over


def test_function_length_counts_real_code_lines() -> None:
    """41 code lines breach the 40-line budget."""
    body = "\n".join(f"    x{i} = {i}" for i in range(41))
    over = _measure(f"def f():\n{body}\n")
    assert over["function length"] == 42


def test_nesting_depth_counts_compound_statements() -> None:
    """Four levels of nesting exceed the depth budget of 3."""
    source = (
        "def f(a):\n"
        "    if a:\n"
        "        for i in a:\n"
        "            while i:\n"
        "                with open('x') as fh:\n"
        "                    return fh\n"
    )
    assert _measure(source)["nesting depth"] > guard.MAX_NESTING_DEPTH


def test_elif_chain_does_not_add_nesting_depth() -> None:
    """An elif chain is flat to a reader, so it must not read as depth."""
    branches = "\n".join(f"    elif a == {i}:\n        return {i}" for i in range(8))
    source = f"def f(a):\n    if a == 0:\n        return 0\n{branches}\n"
    assert "nesting depth" not in _measure(source)


def test_parameter_count_excludes_self() -> None:
    """A bound method's receiver is not a parameter the caller passes."""
    params = ", ".join(f"p{i}" for i in range(6))
    source = f"class C:\n    def f(self, {params}):\n        return 1\n"
    assert "parameters" not in _measure(source, name="C.f")


def test_parameter_count_breaches_above_budget() -> None:
    """Seven caller-supplied parameters exceed the budget of 6."""
    params = ", ".join(f"p{i}" for i in range(7))
    assert _measure(f"def f({params}):\n    return 1\n")["parameters"] == 7


def test_args_and_kwargs_count_as_one_each() -> None:
    """*args and **kwargs are each one parameter, not unbounded."""
    params = ", ".join(f"p{i}" for i in range(5))
    source = f"def f({params}, *args, **kwargs):\n    return 1\n"
    assert _measure(source)["parameters"] == 7


# ── Nested scopes ─────────────────────────────────────────────────────


def test_nested_and_class_functions_get_qualified_names() -> None:
    """Names are qualified, because reports and HEAD key by them, not by line."""
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
        "class C:\n"
        "    def method(self):\n"
        "        return 2\n"
        "    class D:\n"
        "        def deep(self):\n"
        "            return 3\n"
    )
    assert _names(source) == [
        "outer",
        "outer.inner",
        "C.method",
        "C.D.deep",
    ]


def test_nested_function_body_is_measured_separately() -> None:
    """A nested def is its own function, so its branches do not inflate the parent."""
    branches = "\n".join(
        f"        if a == {i}:\n            return {i}" for i in range(11)
    )
    source = f"def outer(a):\n    def inner(a):\n{branches}\n        return None\n    return inner\n"
    assert _measure(source, name="outer") == {}
    assert _measure(source, name="outer.inner")["cyclomatic complexity"] > 10


def test_async_functions_are_measured() -> None:
    """An async def is a function; skipping it would be a silent hole."""
    params = ", ".join(f"p{i}" for i in range(7))
    assert _measure(f"async def f({params}):\n    return 1\n")["parameters"] == 7


# ── Exemptions ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,exempt",
    [
        ("/repo/src/app/services/run.py", False),
        ("/repo/scripts/register_pipelines.py", False),
        ("/repo/tests/unit/test_run.py", True),
        ("/repo/src/app/test_helper.py", True),
        ("/repo/src/app/helper_test.py", True),
        ("/repo/src/app/conftest.py", True),
        ("/repo/alembic/versions/abc123_add_column.py", True),
        ("/repo/scripts/dev/scratch.py", True),
        # `dev` alone is not the exemption — only `scripts/dev` is.
        ("/repo/dev/tool.py", False),
        ("/repo/src/dev/thing.py", False),
    ],
)
def test_file_exemptions(path: str, exempt: bool) -> None:
    """Exemptions are narrow on purpose; a wide one silently disables the guard."""
    assert guard._is_exempt_file(Path(path)) is exempt


# ── HEAD comparisons ──────────────────────────────────────────────────


def test_recorded_breach_at_the_same_value_does_not_block() -> None:
    """Pre-existing debt must not make a whole-file refactor a precondition."""
    assert guard._blocking({"parameters": 8}, {"parameters": 8}) == []


def test_recorded_breach_that_improved_does_not_block() -> None:
    """Ratcheting down is always allowed."""
    assert guard._blocking({"parameters": 7}, {"parameters": 8}) == []


def test_worsened_recorded_breach_blocks_and_shows_the_previous_value() -> None:
    """Committed numbers may never go up."""
    messages = guard._blocking({"parameters": 9}, {"parameters": 8})
    assert len(messages) == 1
    assert "was 8" in messages[0]


def test_new_metric_on_a_recorded_function_blocks() -> None:
    """A function already over on one metric may not quietly breach another."""
    messages = guard._blocking({"parameters": 8, "nesting depth": 5}, {"parameters": 8})
    assert len(messages) == 1
    assert "nesting depth" in messages[0]


def test_unrecorded_breach_blocks() -> None:
    """A brand-new violation always blocks."""
    assert len(guard._blocking({"parameters": 9}, {})) == 1


# ── Exit codes ────────────────────────────────────────────────────────


def test_clean_file_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file inside every budget must not block."""
    target = tmp_path / "clean.py"
    target.write_text("def f(a):\n    return a\n")
    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0


def test_violating_file_exits_two_with_a_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 2 is the one deliberate blocking path; the report goes to stderr."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "bad.py"
    target.write_text(f"def f({params}):\n    return 1\n")

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 2

    stderr = capsys.readouterr().err
    assert "Complexity budget violations" in stderr
    assert "parameters 9" in stderr


# The four legitimate repairs and the three forbidden ones the block report
# must state. AGENTS.md carries the same seven statements for the agent to
# read at design time. Nothing pins the two texts to each other: update
# both by hand.
_REPAIR_ADVICE = (
    "Remove a branch. A condition that cannot be false is dead weight.",
    "Replace a nested conditional with an early return.",
    "Move a whole responsibility to a new named unit.",
    "Extract a helper only when the helper has its own reason to exist.",
    "Do not add a boolean parameter to merge two behaviours into one function.",
    "Do not pass a dictionary or an object of state to get below the parameter budget.",
    "Do not split a function into two halves that share most of their local variables.",
)


def test_the_block_report_forbids_the_repairs_that_only_move_a_breach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The advice must name the forbidden repairs, not only the legitimate ones.

    "Extract a helper" on its own splits one over-budget function into two
    that each fit. The budget then reads as met while the complexity stays.
    """
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "bad.py"
    target.write_text(f"def f({params}):\n    return 1\n")

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 2

    # Normalised: the footer wraps by hand, so a statement may span lines.
    report = " ".join(capsys.readouterr().err.split())
    for statement in _REPAIR_ADVICE:
        assert statement in report, f"missing from the block report: {statement}"


def test_exempt_file_exits_zero_without_reading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test file breaching every budget is still exempt."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "test_bad.py"
    target.write_text(f"def f({params}):\n    return 1\n")
    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0


@pytest.mark.parametrize(
    "payload,raw",
    [
        (None, "not json"),
        (None, ""),
        ([], None),
        ({}, None),
        ({"tool_input": {}}, None),
        ({"tool_input": {"file_path": "/nonexistent/file.py"}}, None),
    ],
)
def test_unusable_input_fails_open(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    raw: str | None,
) -> None:
    """A broken hook must never block real work."""
    assert _run_main(monkeypatch, payload, raw) == 0


def test_non_python_file_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only Python has these budgets."""
    target = tmp_path / "notes.md"
    target.write_text("# not python")
    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0


def test_unparseable_python_fails_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Syntax the host interpreter cannot parse must not block the edit."""
    target = tmp_path / "broken.py"
    target.write_text("def f(:\n")
    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0


def test_serena_relative_path_input_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """serena passes relative_path; missing it would silently skip serena edits."""
    params = ", ".join(f"p{i}" for i in range(9))
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "bad.py").write_text(f"def f({params}):\n    return 1\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    code = _run_main(monkeypatch, {"tool_input": {"relative_path": "pkg/bad.py"}})
    assert code == 2


def test_cursor_after_file_edit_payload_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor afterFileEdit sends file_path on the payload, not tool_input."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "bad.py"
    target.write_text(f"def f({params}):\n    return 1\n")
    assert _run_main(monkeypatch, {"file_path": str(target)}) == 2


def test_cursor_write_path_input_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor Write/StrReplace send tool_input.path."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "bad.py"
    target.write_text(f"def f({params}):\n    return 1\n")
    assert _run_main(monkeypatch, {"tool_input": {"path": str(target)}}) == 2


# ── Merge gate (--check) ──────────────────────────────────────────────


@pytest.fixture
def measured(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict], None]:
    """Replace the tree measurement, which would otherwise shell out to git."""

    def _set(functions: dict) -> None:
        monkeypatch.setattr(guard, "measure_tree", lambda _root: functions)

    return _set


def test_check_passes_when_the_tree_has_no_debt(
    measured: Callable[[dict], None], capsys: pytest.CaptureFixture
) -> None:
    """A clean tree must merge without ceremony."""
    measured({})

    assert guard.check() == 0
    assert "no over-budget functions" in capsys.readouterr().out


def test_check_fails_and_lists_each_breach(
    measured: Callable[[dict], None], capsys: pytest.CaptureFixture
) -> None:
    """Debt that landed outside a hooked session must block the merge."""
    measured({"a.py": {"f": {"parameters": 9}}})

    assert guard.check() == 1

    out = capsys.readouterr().out
    assert "a.py::f  parameters 9 (max 6)" in out
    assert "over-budget functions" in out


def test_check_lists_every_metric_of_every_function(
    measured: Callable[[dict], None], capsys: pytest.CaptureFixture
) -> None:
    """One function over on two metrics is two findings, not one collapsed line."""
    measured(
        {
            "b.py": {"g": {"nesting depth": 4}},
            "a.py": {"f": {"parameters": 9, "function length": 50}},
        }
    )

    assert guard.check() == 1
    out = capsys.readouterr().out
    assert "a.py::f  function length 50 code lines (max 40)" in out
    assert "a.py::f  parameters 9 (max 6)" in out
    assert "b.py::g  nesting depth 4 (max 3)" in out


def test_check_and_pre_are_the_gate_modes() -> None:
    """`--check` merges; `--pre` denies before write. Both are first-class."""
    assert guard.parse_args(["--check"]).check is True
    assert guard.parse_args(["--pre"]).pre is True
    assert guard.parse_args(["--report", "a.py"]).report == "a.py"


# ── Budget report (--report) ──────────────────────────────────────────


def test_report_prints_every_metric_against_its_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A reader gets the headroom without reading the guard or the budgets."""
    target = tmp_path / "app.py"
    target.write_text(
        "def small(one, two):\n    if one:\n        return two\n    return one\n",
        encoding="utf-8",
    )

    assert guard.report(target) == 0

    out = capsys.readouterr().out
    assert "small (line 1): " in out
    assert "cyclomatic complexity 2/10" in out
    assert "function length 4/40" in out
    assert "nesting depth 1/3" in out
    assert "parameters 2/6" in out


def test_report_names_an_exempt_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A test file has no budget, and silence would read as no debt."""
    target = tmp_path / "test_app.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")

    assert guard.report(target) == 0
    assert "exempt from the budgets" in capsys.readouterr().out


def test_report_fails_on_a_file_it_cannot_measure(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A parse error is a failure, never an empty report that reads as clean."""
    target = tmp_path / "broken.py"
    target.write_text("def f(:\n", encoding="utf-8")

    assert guard.report(target) == 1
    assert "cannot measure" in capsys.readouterr().err


def test_check_and_pre_cannot_combine() -> None:
    """One process, one mode — combining them is a misconfiguration."""
    with pytest.raises(SystemExit) as excinfo:
        guard.parse_args(["--check", "--pre"])
    assert excinfo.value.code == 1


# ── Run log ───────────────────────────────────────────────────────────


def test_hook_pass_appends_one_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_file: Path
) -> None:
    """A clean edit must still leave a trace; silence is what the audit found."""
    target = tmp_path / "clean.py"
    target.write_text("def f(a):\n    return a\n")

    payload = {
        "session_id": "s1",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
    }
    assert _run_main(monkeypatch, payload) == 0

    (record,) = _records(log_file)
    assert record["result"] == "pass"
    assert record["session_id"] == "s1"
    assert record["tool_name"] == "Edit"


def test_hook_block_record_carries_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_file: Path
) -> None:
    """The log must hold the block reason a subagent might not report."""
    target = _violating_file(tmp_path)

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 2

    (record,) = _records(log_file)
    assert record["result"] == "block"
    assert "parameters 9 (max 6)" in record["detail"]


def test_hook_block_still_prints_the_report_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    log_file: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """Logging must not replace the feedback the agent acts on."""
    target = _violating_file(tmp_path)

    _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}})

    assert "parameters 9 (max 6)" in capsys.readouterr().err


def test_hook_exempt_record_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_file: Path
) -> None:
    """An exemption is a decision, so it must be auditable too."""
    target = tmp_path / "test_thing.py"
    target.write_text("def f(a):\n    return a\n")

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0

    (record,) = _records(log_file)
    assert record["result"] == "exempt"
    assert record["file"].endswith("test_thing.py")


def test_hook_fail_open_logs_and_emits_additional_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    log_file: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """A fail-open must be visible; otherwise it reads as a clean pass."""

    def _boom(_path: Path) -> str:
        raise RuntimeError("guard is broken")

    monkeypatch.setattr(guard, "_analyze", _boom)
    target = _violating_file(tmp_path)

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0

    (record,) = _records(log_file)
    assert record["result"] == "fail-open"
    emitted = json.loads(capsys.readouterr().out)
    assert "failed open" in emitted["hookSpecificOutput"]["additionalContext"]


def test_hook_unreadable_stdin_is_logged(
    monkeypatch: pytest.MonkeyPatch, log_file: Path
) -> None:
    """Garbage stdin still fails open, but no longer silently."""
    assert _run_main(monkeypatch, None, raw="not json") == 0

    (record,) = _records(log_file)
    assert record["result"] == "fail-open"
    assert record["detail"] == "unreadable stdin"


def test_hook_log_write_failure_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unwritable log must never cost an edit."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(guard, "LOG_PATH", blocker / "sub" / "guard.jsonl")
    target = tmp_path / "clean.py"
    target.write_text("def f(a):\n    return a\n")

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0


# ── HEAD anchor ───────────────────────────────────────────────────────


def test_head_anchor_entries_from_source_measures_bytes_the_file_lacks() -> None:
    """HEAD bytes never touch the disk, so the measurement must not need a file."""
    source = f"def f({', '.join(f'p{i}' for i in range(9))}):\n    return 1\n"

    assert guard._entries_from_source(source.encode(), "bad.py") == {
        "f": {"parameters": 9}
    }


def test_head_anchor_entries_from_source_returns_empty_on_syntax_error() -> None:
    """Unparseable committed bytes must not raise on the hook path."""
    assert guard._entries_from_source(b"def f(:\n", "bad.py") == {}


def test_head_anchor_head_entries_is_empty_without_head_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new or renamed file has no HEAD version; that must not raise."""
    monkeypatch.setattr(guard, "_head_source", lambda _key: None)

    assert guard._head_entries(tmp_path / "new.py") == {}


def test_head_anchor_breach_present_at_head_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Debt already on HEAD must stop blocking later edits to that file."""
    target = _violating_file(tmp_path)
    monkeypatch.setattr(guard, "_head_entries", lambda _path: {"f": {"parameters": 9}})

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 0


def test_head_anchor_breach_worse_than_head_blocks_with_head_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Making committed debt worse is exactly what must still block."""
    target = _violating_file(tmp_path)
    monkeypatch.setattr(guard, "_head_entries", lambda _path: {"f": {"parameters": 8}})

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 2
    assert "parameters 9 (max 6, was 8)" in capsys.readouterr().err


def test_head_anchor_new_function_absent_from_head_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A function HEAD never held is this session's debt."""
    target = _violating_file(tmp_path)
    monkeypatch.setattr(
        guard, "_head_entries", lambda _path: {"other": {"parameters": 9}}
    )

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 2


def test_head_anchor_empty_head_blocks_every_breach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no HEAD version every current breach is this session's debt."""
    target = _violating_file(tmp_path)
    monkeypatch.setattr(guard, "_head_entries", lambda _path: {})

    assert _run_main(monkeypatch, {"tool_input": {"file_path": str(target)}}) == 2


# ── Gate-mode strictness ──────────────────────────────────────────────


def test_gate_entries_from_source_raises_when_strict() -> None:
    """A gate must not read an unparseable file as a file with no debt."""
    with pytest.raises(SyntaxError):
        guard._entries_from_source(b"def f(:\n", "bad.py", strict=True)


def test_gate_measure_tree_fails_on_a_file_it_cannot_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise every breach in that file reads as a clean tree."""
    (tmp_path / "new.py").write_text("def f(:\n")
    monkeypatch.setattr(guard, "tracked_python_files", lambda _root: ["new.py"])

    with pytest.raises(SyntaxError):
        guard.measure_tree(tmp_path)


def test_gate_measure_tree_keys_by_git_path_and_skips_exempt_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one function the whole gate rests on, measured end to end."""
    over = f"def f({', '.join(f'p{i}' for i in range(9))}):\n    return 1\n"
    for folder in ("src", "tests", "alembic"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "a.py").write_text(over)
    names = ["src/a.py", "tests/a.py", "alembic/a.py"]
    monkeypatch.setattr(guard, "tracked_python_files", lambda _root: names)

    assert guard.measure_tree(tmp_path) == {"src/a.py": {"f": {"parameters": 9}}}


def test_gate_measure_tree_exempts_on_the_repo_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout under a directory named `tests` must not exempt the whole repo."""
    root = tmp_path / "tests" / "pipeline-engine" / "src"
    root.mkdir(parents=True)
    over = f"def f({', '.join(f'p{i}' for i in range(9))}):\n    return 1\n"
    (root / "a.py").write_text(over)
    monkeypatch.setattr(guard, "tracked_python_files", lambda _root: ["a.py"])

    assert guard.measure_tree(root) == {"a.py": {"f": {"parameters": 9}}}


def test_gate_stray_argument_does_not_wear_the_block_code() -> None:
    """Exit 2 is the PostToolUse block code; a usage error must never use it."""
    with pytest.raises(SystemExit) as excinfo:
        guard.parse_args(["--nonsense"])

    assert excinfo.value.code == 1


def test_gate_measure_tree_fails_on_a_file_it_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable file must not measure as debt-free in a gate."""
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "a.py").write_text("def f(a):\n    return a\n")
    folder.chmod(0o000)
    monkeypatch.setattr(guard, "tracked_python_files", lambda _root: ["src/a.py"])

    try:
        with pytest.raises(PermissionError):
            guard.measure_tree(tmp_path)
    finally:
        folder.chmod(0o755)


def test_hook_exempts_on_the_repo_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_file: Path
) -> None:
    """A checkout under a directory named `tests` must not disable the hook."""
    root = tmp_path / "tests" / "pipeline-engine"
    (root / "src").mkdir(parents=True)
    params = ", ".join(f"p{i}" for i in range(9))
    (root / "src" / "bad.py").write_text(f"def f({params}):\n    return 1\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))

    code = _run_main(monkeypatch, {"tool_input": {"relative_path": "src/bad.py"}})

    assert code == 2
    assert _records(log_file)[0]["result"] == "block"


def test_gate_help_still_exits_zero(capsys: pytest.CaptureFixture) -> None:
    """Rewriting argparse's exit code must not turn --help into a failure."""
    with pytest.raises(SystemExit) as excinfo:
        guard.parse_args(["--help"])

    assert excinfo.value.code == 0


def test_gate_requires_a_mode_flag() -> None:
    """No mode flag is a misconfiguration. Exit 1, never the hook's block code."""
    with pytest.raises(SystemExit) as excinfo:
        guard.parse_args([])
    assert excinfo.value.code == 1


@pytest.mark.parametrize(
    "flag",
    ["--write-baseline", "--check-baseline", "--check-frozen", "--accept"],
)
def test_removed_baseline_flags_are_rejected(flag: str) -> None:
    """The JSON ratchet is gone; its flags must not keep selecting a gate."""
    with pytest.raises(SystemExit) as excinfo:
        guard.parse_args([flag])
    assert excinfo.value.code == 1


def test_gate_measure_tree_skips_a_path_the_worktree_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unstaged delete must not crash the gate."""
    monkeypatch.setattr(guard, "tracked_python_files", lambda _root: ["gone.py"])

    assert guard.measure_tree(tmp_path) == {}


def test_gate_refuses_an_interpreter_older_than_the_project_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """An old python cannot parse this repo, so its measurement is worthless."""
    monkeypatch.setattr(guard.sys, "version_info", (3, 9, 6, "final", 0))

    with pytest.raises(SystemExit) as excinfo:
        guard._require_gate_interpreter()

    assert excinfo.value.code == 1
    assert "need python >= 3.12" in capsys.readouterr().err


def test_gate_accepts_the_running_interpreter() -> None:
    """The tests run on the project target, so the guard must stay quiet."""
    assert guard._require_gate_interpreter() is None


# ── preToolUse (--pre) ────────────────────────────────────────────────


def test_pre_write_allows_clean_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """A Write under budget must be allowed before any disk write."""
    target = tmp_path / "ok.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "path": str(target),
            "contents": "def f(a):\n    return a\n",
        },
    }

    assert _run_pre(monkeypatch, payload) == 0
    assert _permission(capsys)["permission"] == "allow"
    assert not target.exists()


def test_pre_write_denies_over_budget_contents_before_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    log_file: Path,
) -> None:
    """Over-budget Write must deny and leave the path untouched."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "bad.py"
    payload = {
        "session_id": "pre1",
        "tool_name": "Write",
        "tool_input": {
            "path": str(target),
            "contents": f"def f({params}):\n    return 1\n",
        },
    }

    assert _run_pre(monkeypatch, payload) == 2
    verdict = _permission(capsys)
    assert verdict["permission"] == "deny"
    assert "parameters 9 (max 6)" in verdict["agent_message"]
    assert not target.exists()
    assert _records(log_file)[0]["result"] == "block"


def test_pre_str_replace_denies_when_result_breaches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """StrReplace is measured on the prospective file, not the prior disk bytes."""
    target = tmp_path / "edit.py"
    target.write_text("def f(a):\n    return a\n")
    params = ", ".join(f"p{i}" for i in range(9))
    payload = {
        "tool_name": "StrReplace",
        "tool_input": {
            "path": str(target),
            "old_string": "def f(a):\n    return a\n",
            "new_string": f"def f({params}):\n    return 1\n",
        },
    }

    assert _run_pre(monkeypatch, payload) == 2
    assert _permission(capsys)["permission"] == "deny"
    assert target.read_text() == "def f(a):\n    return a\n"


def test_pre_str_replace_allows_when_result_is_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """A StrReplace that stays under budget must be allowed."""
    target = tmp_path / "edit.py"
    target.write_text("def f(a):\n    return a\n")
    payload = {
        "tool_name": "StrReplace",
        "tool_input": {
            "path": str(target),
            "old_string": "return a",
            "new_string": "return a + 1",
        },
    }

    assert _run_pre(monkeypatch, payload) == 0
    assert _permission(capsys)["permission"] == "allow"


def test_pre_fails_closed_on_unreadable_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    log_file: Path,
) -> None:
    """--pre must deny when stdin is garbage; fail-open would let debt land."""
    assert _run_pre(monkeypatch, None, raw="{") == 2
    assert _permission(capsys)["permission"] == "deny"
    assert _records(log_file)[0]["result"] == "fail-closed"


def test_pre_denies_when_prospective_source_cannot_be_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Missing Write contents cannot be measured, so the edit is denied."""
    target = tmp_path / "empty.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {"path": str(target)},
    }

    assert _run_pre(monkeypatch, payload) == 2
    assert "could not build prospective source" in _permission(capsys)["agent_message"]


def test_pre_exempts_test_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Exempt paths stay writable under --pre the same as post-edit mode."""
    params = ", ".join(f"p{i}" for i in range(9))
    target = tmp_path / "test_thing.py"
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "path": str(target),
            "contents": f"def f({params}):\n    return 1\n",
        },
    }

    assert _run_pre(monkeypatch, payload) == 0
    assert _permission(capsys)["permission"] == "allow"
