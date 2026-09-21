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

import hashlib
import os
import re
import shlex
import subprocess
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


_V1_MARKER = ".spec-plan-v1"
_SAFE_PATH = re.compile(r"^[^/\s:]+(?:/[^/\s:]+)*$")
_META = {
    "Spec": re.compile(r"^Spec: (docs/specs/[a-z0-9][a-z0-9._-]*\.md)$"),
    "Spec revision": re.compile(r"^Spec revision: ([1-9][0-9]*)$"),
    "Spec SHA-256": re.compile(r"^Spec SHA-256: ([0-9a-f]{64})$"),
    "Repository commit": re.compile(r"^Repository commit: ([0-9a-f]{40})$"),
    "Date": re.compile(r"^Date: ([0-9]{4}-[0-9]{2}-[0-9]{2})$"),
}
_TASK_HEADING = re.compile(r"^### Task ([1-9][0-9]*)\.([1-9][0-9]*) — (.+)$")
_PHASE_HEADING = re.compile(r"^### Phase ([1-9][0-9]*) — (.+)$")
_FIELD = re.compile(r"^\*\*(Decisions|Do|Files|Provides|Verify):\*\* ?(.*)$")
_PHASE_FIELD = re.compile(r"^\*\*(Goal|Stop condition|Owns files|Provides):\*\* ?(.*)$")
_VERIFY = re.compile(r"^`([^`]+)`$")
_PROVIDED_TEST = re.compile(r"^tests/[^` ]+::test_[A-Za-z0-9_]+$")
_PROVIDED_TARGET = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class StrictTask:
    """One canonical plan task."""

    number: tuple[int, int]
    line: int
    decisions: str
    files: str
    provides: str
    verify: str


@dataclass(frozen=True)
class StrictPlan:
    """The metadata, phase ownership, and tasks in a canonical plan."""

    metadata: dict[str, str]
    phases: list[int]
    phase_owns: dict[int, set[str]]
    tasks: list[StrictTask]


def _strict_path(root: Path, path: Path) -> tuple[str | None, list[str]]:
    """Validate the canonical plan location."""
    candidate = path if path.is_absolute() else root / path
    if candidate.is_symlink():
        return None, ["plan must not be a symlink"]
    try:
        relative = candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return None, ["plan is outside the repository"]
    parts = relative.split("/")
    if len(parts) != 5 or parts[:3] != [".claude", "artifacts", "plan"]:
        return None, ["plan must be .claude/artifacts/plan/<topic>/plan.md"]
    if parts[4] != "plan.md" or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", parts[3]):
        return None, ["plan topic or filename is unsafe"]
    return relative, []


def _strict_marker(root: Path, relative: str) -> list[str]:
    """Require the new workflow marker in the topic directory."""
    marker = root / Path(relative).parent / _V1_MARKER
    try:
        valid = marker.read_bytes() == b"version=1\n"
    except OSError:
        valid = False
    return [] if valid else ["missing or invalid .spec-plan-v1 marker"]


def _git_text(root: Path, args: list[str]) -> str | None:
    """Run a read-only Git query and return text on success."""
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _git_bytes(root: Path, revision: str, path: str) -> bytes | None:
    """Read one Git blob from the baseline tree."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _strict_clean(root: Path) -> bool:
    """Require no staged, modified, or non-ignored untracked files."""
    status = _git_text(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    return status is not None and all(
        line.startswith("!!") for line in status.splitlines()
    )


def _metadata_match(line: str) -> tuple[str, str] | None:
    """Return the metadata field matched by one line."""
    for name, pattern in _META.items():
        if match := pattern.match(line):
            return name, match.group(1)
    return None


def _strict_metadata(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """Parse canonical plan metadata."""
    errors: list[str] = []
    if not lines or not lines[0].startswith("# "):
        errors.append("plan needs a level-one title")
    values: dict[str, str] = {}
    for line in lines[1:]:
        matched = _metadata_match(line)
        if matched:
            name, value = matched
            if name in values:
                errors.append(f"duplicate plan metadata: {name}")
            values[name] = value
        if line.startswith("## "):
            break
    errors.extend(
        f"missing or invalid plan metadata: {name}"
        for name in _META
        if name not in values
    )
    return values, errors


def _strict_fields(
    lines: list[str], pattern: re.Pattern[str]
) -> tuple[dict[str, str], list[str]]:
    """Parse one set of one-line fields."""
    fields: dict[str, str] = {}
    errors: list[str] = []
    for line in lines:
        match = pattern.match(line)
        if match is None:
            if line and not line.startswith("- ["):
                errors.append(f"invalid field: {line}")
            continue
        name, value = match.groups()
        if name in fields:
            errors.append(f"duplicate field: {name}")
        if not value:
            errors.append(f"empty field: {name}")
        fields[name] = value
    return fields, errors


def _strict_sections(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Split the canonical plan into required sections."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    errors: list[str] = []
    for line in text.splitlines()[1:]:
        if line.startswith("## "):
            current = line[3:]
            if current in sections:
                errors.append(f"duplicate section: {current}")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    required = ["Scope boundaries", "Phases", "Tasks"]
    if [name for name in sections if name in required] != required:
        errors.append("plan sections are missing or out of order")
    return sections, errors


def _phase_owns(raw: str) -> list[str]:
    """Read the backticked paths owned by one phase."""
    return re.findall(r"`([^`]+)`", raw)


def _phase_field_errors(
    label: str, block: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Validate required fields in one phase."""
    fields, findings = _strict_fields(
        [line for line in block if line != "**Acceptance criteria:**"], _PHASE_FIELD
    )
    missing = {"Goal", "Stop condition", "Owns files", "Provides"} - fields.keys()
    findings.extend(f"phase {label} missing {name}" for name in sorted(missing))
    return fields, findings


def _phase_gate_error(label: str, block: list[str]) -> str | None:
    """Validate the final integration criterion in one phase."""
    criteria = [line for line in block if line.startswith("- [")]
    expected = "- [ ] Full integration gate passes: `make check`"
    valid = all(re.fullmatch(r"- \[ \] .+", line) for line in criteria)
    valid = valid and "**Acceptance criteria:**" in block
    valid = valid and bool(criteria) and criteria[-1] == expected
    return None if valid else f"phase {label} has an invalid integration gate"


def _phase_owned_errors(
    label: str, raw: str, owned: set[str]
) -> tuple[set[str], list[str]]:
    """Validate and collect one phase's owned paths."""
    findings: list[str] = []
    updated = set(owned)
    for path in _phase_owns(raw):
        if not _safe_strict_path(path):
            findings.append(f"phase {label} has unsafe owned path: {path}")
        if path in updated:
            findings.append(f"phase {label} reuses owned path: {path}")
        updated.add(path)
    return updated, findings


def _strict_phase_blocks(
    lines: list[str],
) -> tuple[list[int], dict[int, set[str]], list[str]]:
    """Validate phase fields, acceptance gates, and ownership."""
    starts = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _PHASE_HEADING.match(line))
    ]
    phases = [int(match.group(1)) for _, match in starts]
    findings: list[str] = []
    owned: set[str] = set()
    phase_owns: dict[int, set[str]] = {}
    for position, (index, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        block = lines[index + 1 : end]
        fields, found = _phase_field_errors(match.group(1), block)
        findings.extend(found)
        if gate_error := _phase_gate_error(match.group(1), block):
            findings.append(gate_error)
        phase_owns[int(match.group(1))] = set(_phase_owns(fields.get("Owns files", "")))
        owned, found = _phase_owned_errors(
            match.group(1), fields.get("Owns files", ""), owned
        )
        findings.extend(found)
    if phases != list(range(1, len(phases) + 1)):
        findings.append("phase numbers are not contiguous")
    return phases, phase_owns, findings


def _strict_tasks(lines: list[str]) -> tuple[list[StrictTask], list[str]]:
    """Read canonical task headings and fields."""
    tasks: list[StrictTask] = []
    errors: list[str] = []
    starts = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _TASK_HEADING.match(line))
    ]
    for position, (index, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        fields, found = _strict_fields(lines[index + 1 : end], _FIELD)
        errors.extend(found)
        missing = (
            set(("Decisions", "Do", "Files", "Provides", "Verify")) - fields.keys()
        )
        errors.extend(
            f"task {match.group(1)}.{match.group(2)} missing {name}"
            for name in sorted(missing)
        )
        if not missing:
            tasks.append(
                StrictTask(
                    (int(match.group(1)), int(match.group(2))),
                    index + 1,
                    fields["Decisions"],
                    fields["Files"],
                    fields["Provides"],
                    fields["Verify"],
                )
            )
    grouped: dict[int, list[int]] = {}
    for task in tasks:
        grouped.setdefault(task.number[0], []).append(task.number[1])
    for phase, numbers in grouped.items():
        if numbers != list(range(1, len(numbers) + 1)):
            errors.append(f"task numbers are not contiguous in phase {phase}")
    return tasks, errors


def _task_structure_errors(
    tasks: list[StrictTask], phases: list[int], phase_owns: dict[int, set[str]]
) -> list[str]:
    """Require task coverage and phase file ownership."""
    counts = {phase: 0 for phase in phases}
    errors: list[str] = []
    for task in tasks:
        phase = task.number[0]
        counts[phase] = counts.get(phase, 0) + 1
        refs, _ = _strict_file_refs(task.files)
        errors.extend(
            f"task {task.number} file is outside phase ownership: {path}"
            for _, path in refs
            if path not in phase_owns.get(phase, set())
        )
    errors.extend(
        f"phase {phase} has no task" for phase, count in counts.items() if count == 0
    )
    errors.extend(
        f"task {task.number} belongs to an undeclared phase"
        for task in tasks
        if task.number[0] not in phases
    )
    return errors


def _strict_scope_errors(lines: list[str]) -> list[str]:
    """Require specific scope-boundary bullets."""
    boundaries = [line for line in lines if line]
    return (
        []
        if boundaries and all(line.startswith("- ") for line in boundaries)
        else ["scope boundaries must contain bullets"]
    )


def _strict_draft_errors(text: str) -> list[str]:
    """Reject unresolved plan markers and task placeholders."""
    markers = re.compile(r"\b(?:TBD|TODO|to be decided)\b|<!--\s*tasks:", re.IGNORECASE)
    return (
        ["plan contains a draft marker or task placeholder"]
        if markers.search(text)
        else []
    )


def _strict_plan(text: str) -> tuple[StrictPlan | None, list[str]]:
    """Parse the canonical plan document."""
    sections, errors = _strict_sections(text)
    errors.extend(_strict_draft_errors(text))
    errors.extend(_strict_scope_errors(sections.get("Scope boundaries", [])))
    metadata, found = _strict_metadata(text.splitlines())
    errors.extend(found)
    if errors:
        return None, errors
    phases, phase_owns, found = _strict_phase_blocks(sections["Phases"])
    errors.extend(found)
    tasks, found = _strict_tasks(sections["Tasks"])
    errors.extend(found)
    errors.extend(_task_structure_errors(tasks, phases, phase_owns))
    if not tasks:
        errors.append("plan needs at least one task")
    return StrictPlan(metadata, phases, phase_owns, tasks), errors


def _safe_strict_path(path: str) -> bool:
    """Check a plan path token."""
    parts = path.split("/")
    return bool(
        _SAFE_PATH.fullmatch(path)
        and not path.startswith("/")
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _strict_file_refs(raw: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse the canonical Files field."""
    refs: list[tuple[str, str]] = []
    errors: list[str] = []
    for segment in raw.split(" | "):
        match = re.fullmatch(r"(create|modify): ((?:`[^`]+`)(?:, `[^`]+`)*)", segment)
        if match is None:
            errors.append(f"invalid Files field: {raw}")
            continue
        kind = match.group(1)
        for path in re.findall(r"`([^`]+)`", match.group(2)):
            if not _safe_strict_path(path):
                errors.append(f"unsafe Files path: {path}")
            refs.append((kind, path))
    if len({kind for kind, _ in refs}) != len(raw.split(" | ")):
        errors.append("Files kinds must occur once")
    if len({path for _, path in refs}) != len(refs):
        errors.append("Files paths must be unique")
    return refs, errors


def _provided_value_valid(kind: str, value: str) -> bool:
    """Validate one provided test or Make target."""
    if kind == "make-target":
        return bool(_PROVIDED_TARGET.fullmatch(value))
    path, separator, selector = value.partition("::")
    return bool(
        separator
        and path.startswith("tests/")
        and _safe_strict_path(path)
        and re.fullmatch(r"test_[A-Za-z0-9_]+", selector)
    )


def _strict_provides(raw: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse the canonical Provides field."""
    if raw == "None":
        return [], []
    refs: list[tuple[str, str]] = []
    errors: list[str] = []
    for segment in raw.split(" | "):
        match = re.fullmatch(
            r"(test|make-target): ((?:`[^`]+`)(?:, `[^`]+`)*)", segment
        )
        if match is None:
            errors.append(f"invalid Provides field: {raw}")
            continue
        kind = match.group(1)
        for value in re.findall(r"`([^`]+)`", match.group(2)):
            if not _provided_value_valid(kind, value):
                errors.append(f"invalid provided {kind}: {value}")
            refs.append((kind, value))
    if len({kind for kind, _ in refs}) != len(raw.split(" | ")):
        errors.append("Provides kinds must occur once")
    return refs, errors


def _shell_syntax(command: str) -> bool:
    """Return whether a command contains unsupported shell syntax."""
    return any(token in command for token in ("|", ";", "&", ">", "<", "$", "#", "\n"))


def _shell_tokens(command: str) -> tuple[list[str], list[str]]:
    """Split a command without accepting shell evaluation."""
    if _shell_syntax(command):
        return [], ["Verify contains unsupported shell syntax"]
    try:
        return shlex.split(command), []
    except ValueError:
        return [], ["Verify has invalid shell quoting"]


def _make_assignments(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Separate one Make target from supported assignments."""
    targets = [token for token in tokens if "=" not in token]
    assignments = [token for token in tokens if "=" in token]
    if len(targets) != 1:
        return [], ["Verify must contain one Make target"]
    allowed = {"TEST", "K", "VERBOSE", "FILE"}
    names = [token.split("=", 1)[0] for token in assignments]
    if any(name not in allowed for name in names):
        return [], ["Verify contains an unsupported assignment"]
    if len(names) != len(set(names)):
        return [], ["Verify contains a duplicate assignment"]
    return [targets[0], *assignments], []


def _strict_make_tokens(command: str) -> tuple[list[str], list[str]]:
    """Parse one restricted Make command."""
    tokens, errors = _shell_tokens(command)
    if errors:
        return [], errors
    if not tokens or tokens[0] != "make":
        return [], ["Verify must start with make"]
    if any(token.startswith("-") for token in tokens[1:]):
        return [], ["Verify cannot use Make options"]
    return _make_assignments(tokens[1:])


def _real_section(data: str, name: str) -> list[str]:
    """Read one Markdown section while ignoring fenced examples."""
    lines: list[str] = []
    in_section = False
    fenced = False
    for line in data.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line == f"## {name}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            lines.append(line)
    return lines


def _strict_spec_decisions(root: Path, spec_path: str) -> set[str]:
    """Read active decisions from the real Decisions section only."""
    data = (root / spec_path).read_text(encoding="utf-8")
    section = "\n".join(_real_section(data, "Decisions"))
    blocks = re.split(r"^### (?=D[1-9][0-9]* — )", section, flags=re.MULTILINE)
    return {
        f"D{match.group(1)}"
        for block in blocks
        if (match := re.match(r"D([1-9][0-9]*) —", block))
        and re.search(r"^- \*\*Status:\*\* active$", block, re.MULTILINE)
    }


def _strict_git_path(root: Path, path: str) -> bool:
    """Return whether a path exists in the recorded commit."""
    return _git_text(root, ["cat-file", "-e", f"HEAD:{path}"]) is not None


def _strict_test_names(root: Path, path: str) -> set[str]:
    """Collect statically declared test names from the baseline tree."""
    files = [path]
    if not path.endswith(".py"):
        listing = _git_text(root, ["ls-tree", "-r", "--name-only", "HEAD", "--", path])
        files = listing.splitlines() if listing else []
    names: set[str] = set()
    for file in files:
        data = _git_bytes(root, "HEAD", file)
        if data is not None:
            names.update(
                re.findall(
                    r"^\s*(?:async\s+)?def\s+(test_\w+)",
                    data.decode("utf-8"),
                    re.MULTILINE,
                )
            )
    return names


def _strict_targets(root: Path) -> set[str]:
    """Read Make targets from the baseline Makefile."""
    data = _git_text(root, ["show", "HEAD:Makefile"]) or ""
    return set(re.findall(r"^([A-Za-z0-9_.-]+):(?!=)", data, re.MULTILINE))


def _strict_value(command: list[str], name: str) -> str | None:
    """Find one assignment in parsed Make tokens."""
    prefix = f"{name}="
    return next(
        (token[len(prefix) :] for token in command if token.startswith(prefix)), None
    )


def _verify_key_error(task: StrictTask, key: str | None, test: str | None) -> list[str]:
    """Validate K's narrow grammar and its TEST dependency."""
    if key is not None and not re.fullmatch(r"[A-Za-z0-9_]+", key):
        return [f"task {task.number}: K must be one identifier"]
    if test is None and key is not None:
        return [f"task {task.number}: K requires TEST"]
    return []


def _selector_known(
    path: str, selector: str, names: set[str], providers: dict[str, set[str]]
) -> bool:
    """Return whether a test selector resolves."""
    provided = {
        value
        for value in providers["test"]
        if value.rsplit("::", 1)[-1] == selector
        and (value.partition("::")[0] == path or path == "tests")
    }
    return not selector or selector in names or bool(provided)


def _provided_names(path: str, providers: dict[str, set[str]]) -> set[str]:
    """Collect provided test names for one selected TEST path."""
    return {
        value.rsplit("::", 1)[-1]
        for value in providers["test"]
        if value.partition("::")[0] == path
        or (path == "tests" and value.startswith("tests/"))
    }


def _key_known(
    key: str | None,
    path: str,
    names: set[str],
    providers: dict[str, set[str]],
) -> bool:
    """Return whether a K identifier matches a selected test path."""
    return not key or any(
        key in name for name in names | _provided_names(path, providers)
    )


def _verify_test_path(
    root: Path,
    task: StrictTask,
    test: str,
    key: str | None,
    providers: dict[str, set[str]],
) -> list[str]:
    """Validate a TEST path, selector, and K identifier."""
    path, _, selector = test.partition("::")
    if not _safe_strict_path(path) or (
        path != "tests" and not path.startswith("tests/")
    ):
        return [f"task {task.number}: TEST must be under tests/"]
    baseline = _strict_git_path(root, path)
    known_path = baseline or path in providers["test-path"]
    if not known_path:
        return [f"task {task.number}: TEST path does not exist: {path}"]
    names = _strict_test_names(root, path) if baseline else set()
    if not _selector_known(path, selector, names, providers):
        return [f"task {task.number}: unknown test selector {selector}"]
    if not _key_known(key, path, names, providers):
        return [f"task {task.number}: K does not match a known test: {key}"]
    return []


def _verify_test_refs(
    root: Path,
    task: StrictTask,
    command: list[str],
    providers: dict[str, set[str]],
) -> list[str]:
    """Validate TEST, K, and selector assignments."""
    test = _strict_value(command, "TEST")
    key = _strict_value(command, "K")
    file_value = _strict_value(command, "FILE")
    verbose = _strict_value(command, "VERBOSE")
    if file_value is not None and not _safe_strict_path(file_value):
        return [f"task {task.number}: FILE is not a safe path"]
    if verbose is not None and verbose != "1":
        return [f"task {task.number}: VERBOSE must be 1"]
    errors = _verify_key_error(task, key, test)
    if errors or test is None:
        return errors
    return _verify_test_path(root, task, test, key, providers)


def _strict_verify(
    root: Path,
    task: StrictTask,
    providers: dict[str, set[str]],
    targets: set[str],
) -> list[str]:
    """Validate one task Verify field against the baseline and providers."""
    match = _VERIFY.fullmatch(task.verify)
    if match is None:
        return [f"task {task.number}: Verify must contain one backticked command"]
    command, errors = _strict_make_tokens(match.group(1))
    if errors:
        return [f"task {task.number}: {error}" for error in errors]
    target = command[0]
    if target == "check":
        return [f"task {task.number}: task Verify cannot be make check"]
    if target not in targets and target not in providers["make-target"]:
        return [f"task {task.number}: unknown Make target {target}"]
    return _verify_test_refs(root, task, command, providers)


def _task_file_errors(
    root: Path,
    task: StrictTask,
    refs: list[tuple[str, str]],
    providers: dict[str, set[str]],
) -> list[str]:
    """Validate task file producers and consumers."""
    findings: list[str] = []
    for kind, path in refs:
        exists = _strict_git_path(root, path)
        if kind == "modify" and not exists and path not in providers["path"]:
            findings.append(f"task {task.number}: modify path does not exist: {path}")
        if kind == "create" and (exists or path in providers["path"]):
            findings.append(f"task {task.number}: create path already exists: {path}")
    return findings


def _task_provision_errors(
    task: StrictTask, refs: list[tuple[str, str]], provisions: list[tuple[str, str]]
) -> list[str]:
    """Require each provided artifact's owning file in Files."""
    files = {path for _, path in refs}
    findings: list[str] = []
    for kind, value in provisions:
        path = value.split("::", 1)[0] if kind == "test" else "Makefile"
        if path not in files:
            findings.append(f"task {task.number}: provided {kind} lacks file ownership")
    return findings


def _task_decision_errors(task: StrictTask, decisions: set[str]) -> list[str]:
    """Validate task decision references."""
    if task.decisions == "None":
        return []
    return [
        f"task {task.number}: unknown active decision {decision}"
        for decision in (value.strip() for value in task.decisions.split(","))
        if decision not in decisions
    ]


def _update_providers(
    task: StrictTask,
    refs: list[tuple[str, str]],
    provisions: list[tuple[str, str]],
    providers: dict[str, set[str]],
) -> tuple[dict[str, set[str]], list[str]]:
    """Record task producers and reject duplicate producers."""
    updated = {key: set(values) for key, values in providers.items()}
    findings: list[str] = []
    for kind, value in provisions:
        bucket = "test" if kind == "test" else "make-target"
        if value in updated[bucket]:
            findings.append(f"task {task.number}: duplicate provided {kind}: {value}")
        updated[bucket].add(value)
        if kind == "test":
            updated["test-name"].add(value.rsplit("::", 1)[-1])
            updated["test-path"].add(value.split("::", 1)[0])
    updated["path"].update(path for kind, path in refs if kind == "create")
    return updated, findings


def _strict_task(
    root: Path,
    task: StrictTask,
    providers: dict[str, set[str]],
    decisions: set[str],
    targets: set[str],
) -> tuple[dict[str, set[str]], list[str]]:
    """Validate one task and return updated producer registries."""
    refs, file_errors = _strict_file_refs(task.files)
    provisions, provision_errors = _strict_provides(task.provides)
    findings = [
        f"task {task.number}: {error}" for error in file_errors + provision_errors
    ]
    findings.extend(_task_provision_errors(task, refs, provisions))
    findings.extend(_task_decision_errors(task, decisions))
    findings.extend(_task_file_errors(root, task, refs, providers))
    updated, producer_errors = _update_providers(task, refs, provisions, providers)
    findings.extend(_strict_verify(root, task, updated, targets))
    return updated, findings + producer_errors


def _strict_plan_context(plan: Path, root: Path) -> tuple[str | None, str, list[str]]:
    """Read the plan and validate its path, marker, and repository state."""
    relative, findings = _strict_path(root, plan)
    if relative is None:
        return None, "", findings
    findings.extend(_strict_marker(root, relative))
    if not _strict_clean(root):
        findings.append("repository is not clean")
    try:
        text = plan.read_text(encoding="utf-8")
        if not text:
            findings.append("plan is empty")
        return relative, text, findings
    except (OSError, UnicodeDecodeError):
        return relative, "", [*findings, "plan cannot be read"]


def _strict_spec_gate(root: Path, spec_path: str) -> list[str]:
    """Run the complete ready specification gate."""
    guard = Path(__file__).with_name("spec-guard.py")
    result = subprocess.run(
        [sys.executable, str(guard), "--ready", spec_path],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    return [] if result.returncode == 0 else ["specification fails spec-check-ready"]


def _strict_spec_errors(root: Path, parsed: StrictPlan) -> tuple[set[str], list[str]]:
    """Validate plan specification freshness and return active decisions."""
    spec_path = parsed.metadata["Spec"]
    spec = root / spec_path
    if not spec.is_file():
        return set(), [f"specification does not exist: {spec_path}"]
    spec_bytes = spec.read_bytes()
    findings = _strict_spec_gate(root, spec_path)
    if hashlib.sha256(spec_bytes).hexdigest() != parsed.metadata["Spec SHA-256"]:
        findings.append("specification digest does not match")
    head = _git_text(root, ["rev-parse", "HEAD"])
    if head != parsed.metadata["Repository commit"]:
        findings.append("Repository commit does not match HEAD")
    if not _strict_git_path(root, spec_path):
        findings.append("specification is not tracked")
    try:
        return _strict_spec_decisions(root, spec_path), findings
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError):
        return set(), [*findings, "specification decisions cannot be read"]


def _review_required_errors(lines: list[str]) -> list[str]:
    """Validate required review metadata fields."""
    required = {
        "Reviewer": re.compile(r"^Reviewer: .+$"),
        "Plan SHA-256": re.compile(r"^Plan SHA-256: [0-9a-f]{64}$"),
        "Date": re.compile(r"^Date: [0-9]{4}-[0-9]{2}-[0-9]{2}$"),
        "Status": re.compile(r"^Status: (Blocking|Approved)$"),
    }
    return [
        f"review must contain one {name} field"
        for name, pattern in required.items()
        if sum(pattern.fullmatch(line) is not None for line in lines) != 1
    ]


def _review_row_errors(lines: list[str]) -> tuple[list[str], list[str]]:
    """Validate review rows and return all rows plus malformed rows."""
    rows = [line for line in lines if " → " in line]
    errors = [
        f"invalid review row: {row}"
        for row in rows
        if not re.fullmatch(r".+ → .+ → .+ → (blocking|non-blocking)", row)
    ]
    return rows, errors


def _review_digest_error(plan: Path, lines: list[str]) -> str | None:
    """Check the review digest against the current plan bytes."""
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    return (
        None
        if f"Plan SHA-256: {digest}" in lines
        else "review digest does not match plan"
    )


def _review_status_errors(lines: list[str]) -> list[str]:
    """Require an approved review without blocking findings."""
    status = next((line for line in lines if line.startswith("Status: ")), "")
    return [] if status == "Status: Approved" else ["review is not Approved"]


def _review_blocking_errors(rows: list[str]) -> list[str]:
    """Reject blocking rows in an approved review artifact."""
    return [
        "review contains a blocking finding"
        for row in rows
        if row.endswith(" → blocking")
    ]


def _strict_review_errors(plan: Path) -> list[str]:
    """Validate an optional post-review approval artifact."""
    review = plan.parent / "review.md"
    if not review.exists():
        return []
    try:
        lines = [
            line for line in review.read_text(encoding="utf-8").splitlines() if line
        ]
        digest_error = _review_digest_error(plan, lines)
    except (OSError, UnicodeDecodeError):
        return ["review artifact cannot be read"]
    findings = _review_required_errors(lines)
    if digest_error:
        findings.append(digest_error)
    rows, row_errors = _review_row_errors(lines)
    findings.extend(row_errors)
    findings.extend(_review_status_errors(lines))
    findings.extend(_review_blocking_errors(rows))
    return findings


def _strict_task_errors(
    root: Path, parsed: StrictPlan, decisions: set[str]
) -> list[str]:
    """Validate every task in order."""
    providers = {
        key: set() for key in ("path", "test", "test-name", "test-path", "make-target")
    }
    targets = _strict_targets(root)
    findings: list[str] = []
    for task in parsed.tasks:
        providers, found = _strict_task(root, task, providers, decisions, targets)
        findings.extend(found)
    if parsed.phases and parsed.phases[-1] != parsed.tasks[-1].number[0]:
        findings.append("last phase has no task")
    return findings


def strict_audit(plan: Path, root: Path) -> list[str]:
    """Validate one canonical v1 plan."""
    _relative, text, findings = _strict_plan_context(plan, root)
    if not text:
        return findings
    parsed, errors = _strict_plan(text)
    findings.extend(errors)
    if parsed is None:
        return findings
    decisions, spec_errors = _strict_spec_errors(root, parsed)
    findings.extend(spec_errors)
    findings.extend(_strict_review_errors(plan))
    return findings + _strict_task_errors(root, parsed, decisions)


def _strict_main(plan: Path) -> int:
    """Run the strict canonical plan gate."""
    try:
        findings = strict_audit(plan, _repo_root())
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError) as exc:
        print(f"plan-check: gate error: {exc}", file=sys.stderr)
        return 1
    if not findings:
        return 0
    print("\n".join(findings))
    print(f"plan-check: {len(findings)} finding(s)")
    return 2


def main(argv: list[str]) -> int:
    """Audit one plan. See the module docstring for the exit codes."""
    if len(argv) == 2 and argv[0] == "--check":
        return _strict_main(Path(argv[1]))
    if len(argv) != 1:
        print("usage: plan-guard.py [--check] <plan.md>", file=sys.stderr)
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
