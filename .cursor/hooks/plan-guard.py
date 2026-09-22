#!/usr/bin/env python3
"""`.cursor/hooks/plan-guard.py` — gate one canonical `/plan` artifact.

A plan that names a file, a test or a `make` target that does not exist ships a
bug no gate catches: the executor follows the plan and the command fails. A
program checks that half faster than a reviewer, and never skips a row.

Two modes. Both are complete-document gates:

* ``--check <plan.md>`` validates one plan at
  `.claude/artifacts/plan/<topic>/plan.md`: the `.spec-plan-v1` marker, a clean
  repository, the metadata block, the phase and task grammar, sentence length,
  the recorded specification, and any `review.md` beside the plan.
* ``--init <topic>`` gates the inputs before a plan is written: the topic slug,
  the ready specification gate, a clean tree, and the state of the topic
  directory. It writes the marker and prints the metadata lines of the plan
  head. A directory that holds a plan for another specification is `stale`: the
  mode reports the state and leaves the replacement decision to the user.

Checked against the recorded `HEAD`, per task:

- a `modify:` path exists in that commit, or an earlier task creates it. A
  `create:` path exists in neither
- every cited `D<n>` and `R<n>` is active in the specification, and every
  active `R<n>` has at least one task
- a `Verify` names one Make target, and one `TEST=` path, `::selector` and `K=`
  name. Each resolves in that commit, or an earlier task provides it. `K=` is a
  **substring** match, as pytest's own `-k` is: `K=test_academic_signal` is
  satisfied by `test_academic_signal_is_true_for_spec_heuristics`
- no sentence is over 25 words, opens with filler, or admits a red tree

Not checked: the symbols a `Do` field names, and the semantics of any row.
Those stay with the `/plan` Phase 5 reviewer.

Known limit: `create:` paths exist once execution starts. The gate reads `HEAD`,
not the worktree, so a landed Phase 1 does not turn those paths into findings.

Exit codes: 0 clean, 1 on a usage or gate error, 2 on findings. Findings go to
stdout, one per line. `scripts/hooks/post-plan.sh` reads the closing count line
to tell findings from a broken guard, and fails open on anything else.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Only a file under this directory is a plan artifact. Anything else exits 0:
# the hook fires on every Write, and most writes are not plans.
PLAN_DIR = ".claude/artifacts/plan/"

# ASD-STE100 sentence length. `spec-guard.py` carries the same block helpers and
# the same limit: the two guards share no module, as their Git helpers do not.
MAX_SENTENCE_WORDS = 25
_HEADING_LINE = re.compile(r"^#{1,6} ")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ x]\]\s+)?|[0-9]+\.\s+)")
_FIELD_LABEL = re.compile(r"^\*\*[^*]+:\*\*")
# An indented code block and a table row are not prose. Counting their tokens
# as words reports a sentence nobody wrote.
_NOT_PROSE = re.compile(r"^(?:\s{4,}\S|\s*\|)")
# A run of comma-separated code spans is one term. One word per span reports a
# list of paths as a long sentence, and that finding is false.
_CODE_RUN = re.compile(r"`[^`]*`(?:\s*,\s*`[^`]*`)*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[0-9A-Za-z]")
# Anchored to a sentence start. `an exclude note that names the lane` is
# ordinary English, and a false finding teaches the writer to skip the gate.
_FILLER = re.compile(
    r"^(?:note that|it is important to|keep in mind|as mentioned above)\b",
    re.IGNORECASE,
)
# `task-structuring` § "No planned-red language". A task that admits a red tree
# is two tasks, or a phase boundary in the wrong place.
_PLANNED_RED = re.compile(
    r"\b(?:will fail until|expected to fail|placeholder for now"
    r"|atomic batch with|tests pass only after)\b",
    re.IGNORECASE,
)


def _strip_fences(lines: list[str]) -> list[str | None]:
    """Hide fenced Markdown lines while preserving line positions."""
    masked: list[str | None] = []
    fenced = False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            masked.append(None)
        else:
            masked.append(None if fenced else line)
    return masked


def _starts_block(line: str | None) -> bool:
    """Return whether the line cannot continue the block before it."""
    if line is None or not line.strip():
        return True
    return bool(
        _HEADING_LINE.match(line.strip())
        or _LIST_MARKER.match(line)
        or _FIELD_LABEL.match(line)
        or _NOT_PROSE.match(line)
    )


def _field_text(line: str) -> str:
    """One line without its list marker and its field label."""
    return _FIELD_LABEL.sub("", _LIST_MARKER.sub("", line).strip()).strip()


def _is_prose(line: str | None) -> bool:
    """Return whether the line carries sentence text of its own."""
    if line is None or not line.strip():
        return False
    return not _HEADING_LINE.match(line.strip()) and not _NOT_PROSE.match(line)


def _text_blocks(lines: list[str | None]) -> list[str]:
    """Join wrapped prose lines into blocks. Headings carry no sentence."""
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if _starts_block(line) and current:
            blocks.append(" ".join(current))
            current = []
        if _is_prose(line):
            current.append(_field_text(line or ""))
    if current:
        blocks.append(" ".join(current))
    return blocks


def _fence_errors(lines: list[str]) -> list[str]:
    """Report a fence that never closes.

    `_strip_fences` masks every line after an unclosed fence, so the sentence
    rules would silently stop applying. Silence is this guard's worst failure.
    """
    opened = sum(1 for line in lines if line.startswith("```"))
    return ["unclosed code fence"] if opened % 2 else []


def _word_count(sentence: str) -> int:
    """Count STE words. A run of code spans is one word; punctuation is none."""
    masked = _CODE_RUN.sub("code", sentence)
    return sum(1 for token in masked.split() if _WORD.search(token))


def _one_sentence_errors(sentence: str) -> list[str]:
    """Validate one sentence against the length and phrase rules."""
    masked = _CODE_RUN.sub("code", sentence).strip()
    findings: list[str] = []
    count = _word_count(masked)
    if count > MAX_SENTENCE_WORDS:
        findings.append(
            f"sentence is over {MAX_SENTENCE_WORDS} words ({count}): {sentence[:60]}"
        )
    if _FILLER.match(masked):
        findings.append(f"sentence opens with filler: {sentence[:60]}")
    found = _PLANNED_RED.search(masked)
    if found is not None:
        findings.append(f"planned-red language: {found.group(0)}")
    return findings


def _sentence_errors(text: str) -> list[str]:
    """Report every sentence the writing rules reject."""
    lines = text.splitlines()
    findings = _fence_errors(lines)
    findings.extend(
        finding
        for block in _text_blocks(_strip_fences(lines))
        for sentence in _SENTENCE_SPLIT.split(block)
        for finding in _one_sentence_errors(sentence)
    )
    return findings


def _repo_root() -> Path:
    """Resolved, because `_strict_path` compares it against a resolved path.

    Mirrors `complexity-guard._repo_root`: an unresolved CLAUDE_PROJECT_DIR
    that traverses a symlink (on macOS /var and /tmp both do) makes
    `relative_to` raise, and the gate then rejects a plan inside the tree.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR", "")
    return Path(root).resolve() if root else Path(__file__).resolve().parents[2]


# The task pass resolves every path, Make target and test name against HEAD.
# `strict_audit` stops before it when the plan records another commit.
_STALE_BASELINE = "Repository commit does not match HEAD"
_V1_MARKER = ".spec-plan-v1"
_CHECK_STAMP = ".plan-checked"
_SAFE_PATH = re.compile(r"^[^/\s:]+(?:/[^/\s:]+)*$")
_META = {
    "Spec": re.compile(r"^Spec: (docs/specs/[a-z0-9][a-z0-9._-]*\.md)$"),
    "Spec revision": re.compile(r"^Spec revision: ([1-9][0-9]*)$"),
    "Spec SHA-256": re.compile(r"^Spec SHA-256: ([0-9a-f]{64})$"),
    "Repository commit": re.compile(r"^Repository commit: ([0-9a-f]{40})$"),
    "Date": re.compile(r"^Date: ([0-9]{4}-[0-9]{2}-[0-9]{2})$"),
}
_REQUIRED_TASK_FIELDS = frozenset(
    ("Decisions", "Do", "Files", "Provides", "Requirements", "Verify")
)
_TASK_HEADING = re.compile(r"^### Task ([1-9][0-9]*)\.([1-9][0-9]*) — (.+)$")
_PHASE_HEADING = re.compile(r"^### Phase ([1-9][0-9]*) — (.+)$")
_FIELD = re.compile(
    r"^\*\*(Decisions|Do|Files|Provides|Requirements|Verify):\*\* ?(.*)$"
)
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
    requirements: str
    files: str
    provides: str
    verify: str


@dataclass(frozen=True)
class PlanInit:
    """The specification facts a new plan records in its metadata block."""

    topic: str
    spec: str
    revision: str
    digest: str


@dataclass(frozen=True)
class SpecFacts:
    """The active specification IDs a task may cite."""

    decisions: set[str]
    requirements: set[str]


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
        missing = _REQUIRED_TASK_FIELDS - fields.keys()
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
                    fields["Requirements"],
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
    kinds: list[str] = []
    for segment in raw.split(" | "):
        match = re.fullmatch(r"(create|modify): ((?:`[^`]+`)(?:, `[^`]+`)*)", segment)
        if match is None:
            errors.append(f"invalid Files field: {raw}")
            continue
        kind = match.group(1)
        kinds.append(kind)
        for path in re.findall(r"`([^`]+)`", match.group(2)):
            if not _safe_strict_path(path):
                errors.append(f"unsafe Files path: {path}")
            refs.append((kind, path))
    if len(set(kinds)) != len(kinds):
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
    kinds: list[str] = []
    for segment in raw.split(" | "):
        match = re.fullmatch(
            r"(test|make-target): ((?:`[^`]+`)(?:, `[^`]+`)*)", segment
        )
        if match is None:
            errors.append(f"invalid Provides field: {raw}")
            continue
        kind = match.group(1)
        kinds.append(kind)
        for value in re.findall(r"`([^`]+)`", match.group(2)):
            if not _provided_value_valid(kind, value):
                errors.append(f"invalid provided {kind}: {value}")
            refs.append((kind, value))
    if len(set(kinds)) != len(kinds):
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


def _active_spec_ids(text: str, section: str, prefix: str) -> set[str]:
    """The active entry IDs in one real specification section."""
    body = "\n".join(_real_section(text, section))
    blocks = re.split(rf"^### (?={prefix}[1-9][0-9]* — )", body, flags=re.MULTILINE)
    return {
        f"{prefix}{match.group(1)}"
        for block in blocks
        if (match := re.match(rf"{prefix}([1-9][0-9]*) —", block))
        and re.search(r"^- \*\*Status:\*\* active$", block, re.MULTILINE)
    }


def _strict_spec_facts(root: Path, spec_path: str) -> SpecFacts:
    """Read the active decision and requirement IDs a task may cite."""
    text = (root / spec_path).read_text(encoding="utf-8")
    return SpecFacts(
        _active_spec_ids(text, "Decisions", "D"),
        _active_spec_ids(text, "Requirements", "R"),
    )


# Memoized: the baseline commit is fixed for one gate run, and a plan asks
# for the same path and the same test directory once per task. Without this
# a twenty-task plan spends seconds re-reading one tree out of Git.
#
# Two conditions the cache needs: the guard is one process per run, and no
# caller writes to the set it gets back. A caller that mutated it, or a second
# audit of one root across a new commit, would read a stale answer.
@functools.cache
def _strict_git_path(root: Path, path: str) -> bool:
    """Return whether a path exists in the recorded commit."""
    return _git_text(root, ["cat-file", "-e", f"HEAD:{path}"]) is not None


@functools.cache
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


def _under_test_path(value: str, path: str) -> bool:
    """Return whether one provided test node id lies under a TEST path.

    The separator keeps the prefix honest: `tests/test_ab.py` is not under
    `tests/test_a`, and a bare `startswith` would say it is.
    """
    owner = value.partition("::")[0]
    return owner == path or owner.startswith(f"{path}/")


def _provided_names(path: str, providers: dict[str, set[str]]) -> set[str]:
    """Collect provided test names for one selected TEST path."""
    return {
        value.rsplit("::", 1)[-1]
        for value in providers["test"]
        if _under_test_path(value, path)
    }


def _selector_known(
    path: str, selector: str, names: set[str], providers: dict[str, set[str]]
) -> bool:
    """Return whether a test selector resolves."""
    return not selector or selector in names | _provided_names(path, providers)


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
    known_path = baseline or bool(_provided_names(path, providers))
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


def _cited_ids(raw: str) -> list[str]:
    """The specification IDs one citation field names."""
    return [] if raw == "None" else [value.strip() for value in raw.split(",")]


def _task_citation_errors(
    task: StrictTask, raw: str, label: str, known: set[str]
) -> list[str]:
    """Validate one task citation field against the active specification IDs."""
    return [
        f"task {task.number}: unknown active {label} {value}"
        for value in _cited_ids(raw)
        if value not in known
    ]


def _coverage_errors(tasks: list[StrictTask], requirements: set[str]) -> list[str]:
    """Require one task for each active requirement."""
    cited = {value for task in tasks for value in _cited_ids(task.requirements)}
    return [
        f"active requirement {name} has no task"
        for name in sorted(requirements - cited, key=lambda name: int(name[1:]))
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
    updated["path"].update(path for kind, path in refs if kind == "create")
    return updated, findings


def _strict_task(
    root: Path,
    task: StrictTask,
    providers: dict[str, set[str]],
    facts: SpecFacts,
    targets: set[str],
) -> tuple[dict[str, set[str]], list[str]]:
    """Validate one task and return updated producer registries."""
    refs, file_errors = _strict_file_refs(task.files)
    provisions, provision_errors = _strict_provides(task.provides)
    findings = [
        f"task {task.number}: {error}" for error in file_errors + provision_errors
    ]
    findings.extend(_task_provision_errors(task, refs, provisions))
    findings.extend(
        _task_citation_errors(task, task.decisions, "decision", facts.decisions)
    )
    findings.extend(
        _task_citation_errors(
            task, task.requirements, "requirement", facts.requirements
        )
    )
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
    if result.returncode == 0:
        return []
    detail = [
        line
        for line in result.stdout.splitlines()
        if not line.startswith("spec-check:")
    ]
    return [f"specification fails spec-check-ready: {line}" for line in detail] or [
        "specification fails spec-check-ready"
    ]


def _strict_spec_errors(root: Path, parsed: StrictPlan) -> tuple[SpecFacts, list[str]]:
    """Validate plan specification freshness and read its citable IDs."""
    spec_path = parsed.metadata["Spec"]
    spec = root / spec_path
    if not spec.is_file():
        return SpecFacts(set(), set()), [f"specification does not exist: {spec_path}"]
    spec_bytes = spec.read_bytes()
    findings = _strict_spec_gate(root, spec_path)
    if hashlib.sha256(spec_bytes).hexdigest() != parsed.metadata["Spec SHA-256"]:
        findings.append("specification digest does not match")
    head = _git_text(root, ["rev-parse", "HEAD"])
    if head != parsed.metadata["Repository commit"]:
        findings.append(_STALE_BASELINE)
    if not _strict_git_path(root, spec_path):
        findings.append("specification is not tracked")
    try:
        return _strict_spec_facts(root, spec_path), findings
    except (OSError, UnicodeDecodeError):
        return SpecFacts(set(), set()), [
            *findings,
            "specification entries cannot be read",
        ]


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
        f"review contains a blocking finding: {row}"
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


def _strict_task_errors(root: Path, parsed: StrictPlan, facts: SpecFacts) -> list[str]:
    """Validate every task in order."""
    providers: dict[str, set[str]] = {
        key: set() for key in ("path", "test", "make-target")
    }
    targets = _strict_targets(root)
    findings: list[str] = []
    for task in parsed.tasks:
        providers, found = _strict_task(root, task, providers, facts, targets)
        findings.extend(found)
    findings.extend(_coverage_errors(parsed.tasks, facts.requirements))
    last_with_task = parsed.tasks[-1].number[0] if parsed.tasks else 0
    if parsed.phases and parsed.phases[-1] != last_with_task:
        findings.append("last phase has no task")
    return findings


def strict_audit(plan: Path, root: Path) -> list[str]:
    """Validate one canonical v1 plan."""
    _relative, text, findings = _strict_plan_context(plan, root)
    if not text:
        return findings
    parsed, errors = _strict_plan(text)
    findings.extend(errors)
    findings.extend(_sentence_errors(text))
    if parsed is None:
        return findings
    facts, spec_errors = _strict_spec_errors(root, parsed)
    findings.extend(spec_errors)
    findings.extend(_strict_review_errors(plan))
    if _STALE_BASELINE in spec_errors:
        return findings
    return findings + _strict_task_errors(root, parsed, facts)


def _spec_path(topic: str) -> str:
    """The one specification path a topic may use."""
    return f"docs/specs/{topic}.md"


def _marker_valid(directory: Path) -> bool:
    """Return whether the topic directory carries the v1 workflow marker."""
    try:
        return (directory / _V1_MARKER).read_bytes() == b"version=1\n"
    except OSError:
        return False


def _init_input_errors(root: Path, topic: str) -> list[str]:
    """Validate the topic, its ready specification, and the repository state."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", topic):
        return [f"topic is not a safe slug: {topic}"]
    spec_path = _spec_path(topic)
    if not (root / spec_path).is_file():
        return [f"specification does not exist: {spec_path}"]
    findings = _strict_spec_gate(root, spec_path)
    if not _strict_clean(root):
        findings.append("repository is not clean")
    return findings


def _init_metadata(root: Path, topic: str) -> tuple[PlanInit | None, list[str]]:
    """Read the specification facts that the plan head records."""
    data = (root / _spec_path(topic)).read_bytes()
    revision = re.search(
        r"^Revision: ([1-9][0-9]*)$", data.decode("utf-8"), re.MULTILINE
    )
    if revision is None:
        return None, ["specification revision cannot be read"]
    digest = hashlib.sha256(data).hexdigest()
    return PlanInit(topic, _spec_path(topic), revision.group(1), digest), []


def _plan_directory_state(directory: Path, init: PlanInit) -> tuple[str, list[str]]:
    """Classify the topic directory as new, current, or stale."""
    # `_strict_path` rejects a symlinked plan for the same reason: the marker
    # and the stamp below would otherwise be written outside the repository.
    if directory.is_symlink():
        return "", ["plan directory must not be a symlink"]
    if not directory.exists():
        return "new", []
    if not _marker_valid(directory):
        return "", ["plan directory holds an older plan format: move it"]
    plan = directory / "plan.md"
    if not plan.is_file():
        return "current", []
    metadata, _ = _strict_metadata(plan.read_text(encoding="utf-8").splitlines())
    fresh = (
        metadata.get("Spec") == init.spec
        and metadata.get("Spec SHA-256") == init.digest
    )
    return "current" if fresh else "stale", []


def _init_report(root: Path, init: PlanInit, state: str) -> list[str]:
    """The directory state, then the five metadata lines of the plan head."""
    return [
        f"Plan directory: {PLAN_DIR}{init.topic}/ ({state})",
        f"Spec: {init.spec}",
        f"Spec revision: {init.revision}",
        f"Spec SHA-256: {init.digest}",
        f"Repository commit: {_git_text(root, ['rev-parse', 'HEAD'])}",
        f"Date: {date.today().isoformat()}",
    ]


def plan_init(root: Path, topic: str) -> tuple[list[str], list[str]]:
    """Gate the plan inputs, write the marker, and report the plan metadata.

    A stale directory is a state, not a finding. The plan it holds was written
    for another specification, and only the user decides to replace it.
    """
    findings = _init_input_errors(root, topic)
    if findings:
        return findings, []
    init, findings = _init_metadata(root, topic)
    if init is None:
        return findings, []
    directory = root / PLAN_DIR / topic
    state, findings = _plan_directory_state(directory, init)
    if findings:
        return findings, []
    directory.mkdir(parents=True, exist_ok=True)
    (directory / _V1_MARKER).write_bytes(b"version=1\n")
    # The stamp opens this directory to `scripts/hooks/post-bash.sh`, which
    # gates a plan written through the shell. Both hooks renew it.
    (directory / _CHECK_STAMP).touch()
    return [], _init_report(root, init, state)


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


def _init_main(topic: str) -> int:
    """Run the plan input gate and print the plan metadata."""
    try:
        findings, report = plan_init(_repo_root(), topic)
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError) as exc:
        print(f"plan-init: gate error: {exc}", file=sys.stderr)
        return 1
    if findings:
        print("\n".join(findings))
        print(f"plan-init: {len(findings)} finding(s)")
        return 2
    print("\n".join(report))
    return 0


def main(argv: list[str]) -> int:
    """Run one plan gate mode. See the module docstring for the exit codes."""
    if len(argv) == 2 and argv[0] == "--check":
        return _strict_main(Path(argv[1]))
    if len(argv) == 2 and argv[0] == "--init":
        return _init_main(argv[1])
    print("usage: plan-guard.py --check <plan.md> | --init <topic>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
