#!/usr/bin/env python3
"""`.cursor/hooks/plan-guard.py` — check that a plan artifact's references resolve.

A plan that names a file, a test or a `make` target that does not exist ships a
bug no gate catches: the implementer follows the plan and the command fails.
`/plan` Phase 6 asks an LLM reviewer to verify those rows with Glob and Grep.
A program does the mechanical half faster and never skips a row.

Checked, per `**Verify:**` command:

- every `make <target>` is a target in `Makefile`
- a `TEST=` path is `tests` or under `tests/`, and exists
- a `path::name` selector names a test under that path, matched exactly
- every identifier in `K=` is a **substring** of at least one `def test_*` name
  under the `TEST=` path. Pytest `-k` is a substring match, so
  `K=test_academic_signal` is satisfied by
  `test_academic_signal_is_true_for_spec_heuristics`.

Checked, per `**Files:**` field: a `modify:` path exists, a `create:` path does
not.

Not checked: the symbols a Do field names, and the semantics of any row. Those
stay with the `/plan` Phase 6 reviewer.

Known limit: `create:` paths exist once execution starts. Re-running the guard
against a plan whose Phase 1 has landed reports those paths as findings. The
hook reports; it never denies. Read the report against execution state.

Exit codes: 0 clean, 0 when the file is not under `.claude/artifacts/plan/` or
cannot be read or decoded (fail open — a broken advisory hook must not freeze the
session), 1 on a usage error, 2 when a reference does not resolve. Findings go
to stdout, one per line, as `path:line → claim → evidence`.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Only a file under this directory is a plan artifact. Anything else exits 0:
# the hook fires on every Write, and most writes are not plans.
PLAN_DIR = ".claude/artifacts/plan/"

_VERIFY_INLINE = re.compile(r"^\*\*Verify:\*\*\s+`([^`]+)`")
_VERIFY_OPEN = re.compile(r"^\*\*Verify:\*\*\s*$")
_BULLET = re.compile(r"^-\s+")
_BULLET_COMMAND = re.compile(r"^-\s+`([^`]+)`")
_FENCE = re.compile(r"^```")

_FILES_LINE = re.compile(r"^\*\*Files:\*\*\s*(.+)$")
# Segments are separated by `|`, and a plan sometimes writes a comma instead.
# A zero-width split before each keyword handles both.
_FILES_SPLIT = re.compile(r"(?=\b(?:create|modify)\s*:)")
_FILES_KIND = re.compile(r"^\s*(create|modify)\s*:\s*(.*)$", re.DOTALL)
_BACKTICKED = re.compile(r"`([^`]+)`")

# The target is the first token after `make` that is neither a flag nor a
# variable assignment. Requiring it to open with an alphanumeric keeps
# `make -C "$proj" plan-check` from reporting `-C` as a missing target.
_MAKE_CALL = re.compile(
    r"\bmake\s+(?:(?:-\S+|[A-Z0-9_]+=\S+)\s+)*([a-zA-Z0-9_.][a-zA-Z0-9_.-]*)"
)
_TEST_ASSIGN = re.compile(r"\bTEST=(\S+)")
# `K=` may be bare or quoted: the Makefile wraps it in single quotes, so a
# filter with spaces (`a or b`) only survives the shell when the plan quotes it.
_K_ASSIGN = re.compile(r"""\bK=(?:'([^']*)'|"([^"]*)"|(\S+))""")
_K_TOKENS = re.compile(r"\band\b|\bor\b|\bnot\b|[^\s()]+")

# `:=` is a variable assignment, not a target.
_MAKE_TARGET = re.compile(r"^([a-zA-Z0-9_.-]+):(?!=)")
_DEF_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.MULTILINE)


@dataclass(frozen=True)
class PlanRef:
    """One reference the plan makes to something in the tree."""

    kind: str  # "verify" | "create" | "modify"
    value: str
    line: int


def _finding(ref: PlanRef, claim: str, evidence: str) -> str:
    """One report line, without the plan path the caller prefixes."""
    return f"{ref.line} → {claim} → {evidence}"


def _fenced_commands(lines: list[str], start: int) -> list[PlanRef]:
    """Commands inside a fenced block, up to its closing fence."""
    found: list[PlanRef] = []
    for index in range(start, len(lines)):
        text = lines[index].strip()
        if _FENCE.match(text):
            break
        if text and not text.startswith("#"):
            found.append(PlanRef("verify", text, index + 1))
    return found


def _bullet_commands(lines: list[str], start: int) -> list[PlanRef]:
    """Commands in the bullet list that follows, up to the first non-bullet.

    A bullet carrying prose instead of a command is skipped, never a stop:
    stopping there would drop every later bullet and report the plan clean.
    Silence is this guard's worst failure — `/plan` step 6 reads it as a pass.
    """
    found: list[PlanRef] = []
    for index in range(start, len(lines)):
        text = lines[index].strip()
        if not _BULLET.match(text):
            break
        match = _BULLET_COMMAND.match(text)
        if match is not None:
            found.append(PlanRef("verify", match.group(1), index + 1))
    return found


def _verify_block(lines: list[str], start: int) -> list[PlanRef]:
    """Commands under a `**Verify:**` line that carries none itself."""
    if start + 1 < len(lines) and _FENCE.match(lines[start + 1].strip()):
        return _fenced_commands(lines, start + 2)
    return _bullet_commands(lines, start + 1)


def iter_verify_commands(text: str) -> Iterator[PlanRef]:
    """Every Verify command in the plan: inline, bullet list, or fenced block."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        inline = _VERIFY_INLINE.match(line)
        if inline is not None:
            yield PlanRef("verify", inline.group(1), index + 1)
        elif _VERIFY_OPEN.match(line):
            yield from _verify_block(lines, index)


def _segment_paths(chunk: str) -> list[str]:
    """The paths in one Files segment.

    A backticked span holding whitespace is a note, not a path — a plan writes
    `(via `git mv`)` beside a real path, and reporting that as a reference is a
    false finding.
    """
    return [
        span
        for span in _BACKTICKED.findall(chunk)
        if not any(char.isspace() for char in span)
    ]


def _files_paths(field: str) -> Iterator[tuple[str, str]]:
    """The (kind, path) pairs inside one `**Files:**` field."""
    for segment in _FILES_SPLIT.split(field):
        match = _FILES_KIND.match(segment)
        if match is None:
            continue
        for path in _segment_paths(match.group(2)):
            yield match.group(1), path


def iter_files_refs(text: str) -> Iterator[PlanRef]:
    """Every `create:` and `modify:` path in the plan."""
    for index, line in enumerate(text.splitlines()):
        match = _FILES_LINE.match(line)
        if match is None:
            continue
        for kind, path in _files_paths(match.group(1)):
            yield PlanRef(kind, path, index + 1)


def _k_identifiers(raw: str) -> list[str]:
    """The names a `-k` expression requires to exist.

    A name after `not` is an exclusion. Pytest accepts it when nothing matches,
    so requiring it would be a false finding.
    """
    keep: list[str] = []
    negated = False
    for token in _K_TOKENS.findall(raw):
        if token == "not":
            negated = True
            continue
        if token not in ("and", "or") and not negated:
            keep.append(token)
        negated = False
    return keep


def parse_test_command(command: str) -> tuple[str | None, list[str]]:
    """The raw `TEST=` value and the `K=` names one command requires.

    The value keeps any `::name` selector; `_check_test_path` splits it, because
    a node id is matched exactly while a `K=` name is matched as a substring.
    """
    test = _TEST_ASSIGN.search(command)
    value = test.group(1) if test is not None else None
    keys = _K_ASSIGN.search(command)
    if keys is None:
        return value, []
    raw = next(group for group in keys.groups() if group is not None)
    return value, _k_identifiers(raw)


def make_targets(makefile: Path) -> set[str]:
    """Every target name declared at column 0 of the Makefile."""
    if not makefile.is_file():
        return set()
    lines = makefile.read_text(encoding="utf-8").splitlines()
    matches = (_MAKE_TARGET.match(line) for line in lines)
    return {match.group(1) for match in matches if match is not None}


def test_names(path: Path) -> set[str]:
    """Every `def test_*` name in a file, or in the `*.py` under a directory."""
    files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
    names: set[str] = set()
    for file in files:
        names.update(_DEF_TEST.findall(file.read_text(encoding="utf-8")))
    return names


def _check_make_targets(ref: PlanRef, targets: set[str]) -> list[str]:
    """Findings for the `make` targets one command names."""
    return [
        _finding(ref, f"make {name}", "no such target in Makefile")
        for name in _MAKE_CALL.findall(ref.value)
        if name not in targets
    ]


def _check_selector(ref: PlanRef, names: set[str], selector: str) -> list[str]:
    """The finding for a `path::name` node id, which names one test exactly."""
    name = selector.rsplit("::", 1)[-1]
    if not name or name in names:
        return []
    return [_finding(ref, f"TEST=…::{name}", "no test of that name under the path")]


def _check_test_path(ref: PlanRef, root: Path, test: str, keys: list[str]) -> list[str]:
    """Findings for one command's `TEST=` value and its `K=` names."""
    path, _, selector = test.partition("::")
    if path != "tests" and not path.startswith("tests/"):
        return [_finding(ref, f"TEST={path}", "a TEST path is tests or under tests/")]
    target = root / path
    if not target.exists():
        return [_finding(ref, f"TEST={path}", "path not found in the tree")]
    names = test_names(target)
    return _check_selector(ref, names, selector) + [
        _finding(ref, f"K={key}", f"no test name under {path} contains it")
        for key in keys
        if not any(key in name for name in names)
    ]


def check_verify(ref: PlanRef, root: Path, targets: set[str]) -> list[str]:
    """Every finding for one Verify command."""
    findings = _check_make_targets(ref, targets)
    test, keys = parse_test_command(ref.value)
    if test is None:
        return findings
    return findings + _check_test_path(ref, root, test, keys)


def check_files(ref: PlanRef, root: Path) -> list[str]:
    """The finding for one `create:` or `modify:` path, if it has one."""
    exists = (root / ref.value).exists()
    if ref.kind == "modify" and not exists:
        return [_finding(ref, f"modify: {ref.value}", "path not found in the tree")]
    if ref.kind == "create" and exists:
        return [_finding(ref, f"create: {ref.value}", "path already exists")]
    return []


def _label(plan: Path, root: Path) -> str:
    """The plan path as the report prints it: relative to the root when it can be."""
    try:
        return plan.resolve().relative_to(root).as_posix()
    except ValueError:
        return plan.as_posix()


def audit(plan: Path, root: Path) -> list[str]:
    """Every unresolved reference in the plan, as report lines."""
    text = plan.read_text(encoding="utf-8")
    targets = make_targets(root / "Makefile")
    findings = [
        line
        for ref in iter_verify_commands(text)
        for line in check_verify(ref, root, targets)
    ]
    findings += [
        line for ref in iter_files_refs(text) for line in check_files(ref, root)
    ]
    label = _label(plan, root)
    return [f"{label}:{line}" for line in findings]


def _repo_root() -> Path:
    """Resolved, because `_label` compares it against a resolved path.

    Mirrors `complexity-guard._repo_root`: an unresolved CLAUDE_PROJECT_DIR
    that traverses a symlink (on macOS /var and /tmp both do) makes
    `relative_to` raise, and the report then carries absolute paths.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR", "")
    return Path(root).resolve() if root else Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    """Audit one plan. See the module docstring for the exit codes."""
    if len(argv) != 1:
        print("usage: plan-guard.py <plan.md>", file=sys.stderr)
        return 1
    plan = Path(argv[0])
    if PLAN_DIR not in plan.resolve().as_posix():
        return 0
    try:
        findings = audit(plan, _repo_root())
    except (OSError, UnicodeDecodeError):
        return 0
    if not findings:
        return 0
    print("\n".join(findings))
    print(f"plan-check: {len(findings)} reference(s) do not resolve")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
