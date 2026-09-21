#!/usr/bin/env python3
"""Validate committed specification documents.

The guard checks structure and repository references. It does not judge whether a
human answer is a good product decision or whether semantic review found every gap.

Modes are complete-document gates:

* ``--check`` reads the working tree.
* ``--ready`` requires an unchanged tracked, ready specification.
* ``--check-all`` checks every tracked ``docs/specs/*.md`` file.
* ``--check-index`` reads the staged specification and staged evidence files.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SECTION = re.compile(r"^## (.+)$")
_SUBHEADING = re.compile(r"^### (.+)$")
_METADATA = {
    "Topic": re.compile(r"^Topic: ([a-z0-9][a-z0-9._-]*)$"),
    "Revision": re.compile(r"^Revision: ([1-9][0-9]*)$"),
    "Status": re.compile(r"^Status: (Draft|Ready|Superseded)$"),
    "Superseded by": re.compile(
        r"^Superseded by: (None|docs/specs/[a-z0-9][a-z0-9._-]*\.md)$"
    ),
}
_REQUIRED = (
    "Goal",
    "Requirements",
    "Out of scope",
    "Decisions",
    "Repository evidence",
    "Acceptance criteria",
    "Open questions",
)
_REQ_HEADING = re.compile(r"^R([1-9][0-9]*) — (.+)$")
_DEC_HEADING = re.compile(r"^D([1-9][0-9]*) — (.+)$")
_QUESTION_HEADING = re.compile(r"^Q([1-9][0-9]*) — (.+)$")
_REQ_STATUS = re.compile(r"^- \*\*Status:\*\* (active|superseded by R[1-9][0-9]*)$")
_BEHAVIOR = re.compile(r"^- \*\*Behavior:\*\* (.+)$")
_DEC_STATUS = re.compile(r"^- \*\*Status:\*\* (active|superseded by D[1-9][0-9]*)$")
_QUESTION = re.compile(r"^- \*\*Question:\*\* (.+)$")
_ANSWER = re.compile(r"^- \*\*Answer:\*\* (.+)$")
_IMPACT = re.compile(r"^- \*\*Impact:\*\* (.+)$")
_EVIDENCE_FIELD = re.compile(r"^- \*\*Evidence:\*\* (.+)$")
_EVIDENCE_LINE = re.compile(r"^- E([1-9][0-9]*): (.+)$")
_ACCEPTANCE = re.compile(r"^- \*\*(R[1-9][0-9]*(?:, R[1-9][0-9]*)*):\*\* (.+)$")
_DRAFT_MARKER = re.compile(r"\b(?:TBD|TODO)\b|\bto be decided\b", re.IGNORECASE)


@dataclass(frozen=True)
class Evidence:
    """One parsed repository, URL, or person evidence value."""

    key: str
    value: str
    path: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class Entry:
    """One requirement, decision, or question entry."""

    number: int
    status: str
    evidence: str | None = None
    affects: str | None = None


@dataclass(frozen=True)
class ParsedSpec:
    """The structural data needed by the gate."""

    metadata: dict[str, str]
    requirements: list[Entry]
    decisions: list[Entry]
    questions: list[Entry]
    evidence: list[Evidence]
    acceptance: list[list[int]]


def _repo_root() -> Path:
    """Resolve the configured repository root."""
    from os import environ

    configured = environ.get("CLAUDE_PROJECT_DIR")
    if configured:
        return Path(configured).resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def _git_bytes(root: Path, revision: str, path: str) -> bytes | None:
    """Read one Git blob, or return None when it does not exist."""
    object_name = f":{path}" if revision == ":" else f"{revision}:{path}"
    result = subprocess.run(
        ["git", "show", object_name],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _tracked(root: Path, path: str) -> bool:
    """Return whether Git tracks the repository-relative path."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _working_tree_clean(root: Path) -> bool:
    """Return whether tracked files have no staged or unstaged changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return not result.stdout.strip()


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


def _section_ranges(
    lines: list[str | None],
) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Find required section ranges and structural section errors."""
    headings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if line is not None and (match := _SECTION.match(line))
    ]
    errors: list[str] = []
    names = [name for _, name in headings]
    if len(names) != len(set(names)):
        errors.append("duplicate section heading")
    ranges = {
        name: (
            start + 1,
            headings[pos + 1][0] if pos + 1 < len(headings) else len(lines),
        )
        for pos, (start, name) in enumerate(headings)
        if name in _REQUIRED
    }
    if names[: len(_REQUIRED)] != list(_REQUIRED):
        errors.append("required sections are missing or out of order")
    if any(name not in ranges for name in _REQUIRED):
        errors.append("required section is missing")
    return ranges, errors


def _metadata(lines: list[str | None]) -> tuple[dict[str, str], list[str]]:
    """Parse the four metadata fields before the first section."""
    values: dict[str, str] = {}
    errors: list[str] = []
    if not lines or lines[0] is None or not lines[0].startswith("# "):
        errors.append("first line must be a level-one title")
    for line in lines[1:]:
        if line is None or _SECTION.match(line):
            break
        for name, pattern in _METADATA.items():
            if match := pattern.match(line):
                if name in values:
                    errors.append(f"duplicate metadata field: {name}")
                values[name] = match.group(1)
                break
    errors.extend(
        f"missing metadata field: {name}" for name in _METADATA if name not in values
    )
    return values, errors


def _sequence(numbers: list[int], label: str) -> list[str]:
    """Require one-based contiguous entry numbers."""
    wanted = list(range(1, len(numbers) + 1))
    return [] if numbers == wanted else [f"{label} IDs are not contiguous"]


def _entry_fields(
    body: list[str | None], patterns: dict[str, re.Pattern[str]], label: str
) -> tuple[dict[str, str], list[str]]:
    """Parse one line-oriented entry body."""
    values: dict[str, str] = {}
    errors: list[str] = []
    for line in body:
        if line is None or not line:
            continue
        matched = False
        for name, pattern in patterns.items():
            if match := pattern.match(line):
                matched = True
                if name in values:
                    errors.append(f"duplicate {label} field: {name}")
                values[name] = match.group(1)
                break
        if not matched:
            errors.append(f"invalid {label} field: {line}")
    return values, errors


def _entries(
    lines: list[str | None],
    heading: re.Pattern[str],
    fields: dict[str, re.Pattern[str]],
    label: str,
) -> tuple[list[Entry], list[str]]:
    """Parse numbered entries in a structured section."""
    entries: list[Entry] = []
    errors: list[str] = []
    current_number: int | None = None
    body: list[str | None] = []
    for line in lines:
        match = _SUBHEADING.match(line or "") if line is not None else None
        if match:
            if current_number is not None:
                entries, errors = _finish_entry(
                    entries, errors, current_number, body, fields, label
                )
            entry = heading.match(match.group(1))
            if entry is None:
                errors.append(f"invalid {label} heading: {match.group(1)}")
                current_number = None
                body = []
            else:
                current_number = int(entry.group(1))
                body = []
            continue
        if current_number is None and line and not line.isspace():
            errors.append(f"content before first {label} entry")
        else:
            body.append(line)
    if current_number is not None:
        entries, errors = _finish_entry(
            entries, errors, current_number, body, fields, label
        )
    errors.extend(_sequence([entry.number for entry in entries], label))
    return entries, errors


def _finish_entry(
    entries: list[Entry],
    errors: list[str],
    number: int,
    body: list[str | None],
    fields: dict[str, re.Pattern[str]],
    label: str,
) -> tuple[list[Entry], list[str]]:
    """Validate and append one structured entry."""
    values, found = _entry_fields(body, fields, label)
    errors.extend(found)
    required = set(fields)
    missing = required - values.keys()
    errors.extend(f"{label} {number} missing field: {name}" for name in sorted(missing))
    if missing:
        return entries, errors
    status = values.get("status", "open")
    evidence = values.get("evidence")
    entries.append(Entry(number, status, evidence, values.get("affects")))
    return entries, errors


def _evidence_value(raw: str, key: str = "") -> Evidence | None:
    """Parse one evidence token."""
    if raw in {"person-decision"}:
        return Evidence(key, raw)
    if raw.startswith("url:"):
        parsed = urlparse(raw[4:])
        valid = (
            parsed.scheme == "https"
            and parsed.netloc
            and not any(char.isspace() for char in raw)
        )
        return Evidence(key, raw) if valid else None
    if not raw.startswith("repo:"):
        return None
    token = raw[5:]
    line: int | None = None
    if "#L" in token and "::" in token:
        return None
    if "#L" in token:
        token, suffix = token.rsplit("#L", 1)
        if not suffix.isdigit() or int(suffix) < 1:
            return None
        line = int(suffix)
    if "::" in token:
        token, symbol = token.split("::", 1)
        if not symbol or any(char.isspace() for char in symbol):
            return None
    if not _safe_repo_path(token):
        return None
    return Evidence(key, raw, token, line)


def _safe_repo_path(raw: str) -> bool:
    """Check the lexical repository path grammar."""
    path = Path(raw)
    return bool(
        raw
        and not path.is_absolute()
        and "\\" not in raw
        and ":" not in raw
        and all(part not in {"", ".", ".."} for part in raw.split("/"))
    )


def _parse_evidence(lines: list[str | None]) -> tuple[list[Evidence], list[str]]:
    """Parse ordered repository evidence entries."""
    values: list[Evidence] = []
    numbers: list[int] = []
    errors: list[str] = []
    for line in lines:
        if line is None or not line:
            continue
        match = _EVIDENCE_LINE.match(line)
        if match is None:
            errors.append(f"invalid evidence entry: {line}")
            continue
        number = int(match.group(1))
        key = f"E{number}"
        numbers.append(number)
        evidence = _evidence_value(match.group(2), key)
        if evidence is None:
            errors.append(f"invalid evidence value: {match.group(2)}")
        else:
            values.append(evidence)
    errors.extend(_sequence(numbers, "evidence"))
    return values, errors


def _parse_acceptance(lines: list[str | None]) -> tuple[list[list[int]], list[str]]:
    """Parse acceptance criteria and requirement references."""
    references: list[list[int]] = []
    errors: list[str] = []
    for line in lines:
        if line is None or not line:
            continue
        match = _ACCEPTANCE.match(line)
        if match is None:
            errors.append(f"invalid acceptance criterion: {line}")
            continue
        references.append([int(value[1:]) for value in match.group(1).split(", ")])
    return references, errors


def _parse_questions(lines: list[str | None]) -> tuple[list[Entry], list[str]]:
    """Parse open questions with their requirement and decision impact."""
    content = [line for line in lines if line]
    if content == ["None."]:
        return [], []
    fields = {
        "affects": re.compile(r"^- \*\*Affects:\*\* (.+)$"),
        "evidence": _EVIDENCE_FIELD,
    }
    return _entries(lines, _QUESTION_HEADING, fields, "question")


def _parse_spec(text: str) -> tuple[ParsedSpec | None, list[str]]:
    """Parse a complete specification document."""
    lines = _strip_fences(text.splitlines())
    ranges, errors = _section_ranges(lines)
    metadata, metadata_errors = _metadata(lines)
    errors.extend(metadata_errors)
    if errors:
        return None, errors
    requirements, found = _entries(
        lines[slice(*ranges["Requirements"])],
        _REQ_HEADING,
        {"status": _REQ_STATUS, "behavior": _BEHAVIOR},
        "requirement",
    )
    errors.extend(found)
    decisions, found = _entries(
        lines[slice(*ranges["Decisions"])],
        _DEC_HEADING,
        {
            "status": _DEC_STATUS,
            "question": _QUESTION,
            "answer": _ANSWER,
            "impact": _IMPACT,
            "evidence": _EVIDENCE_FIELD,
        },
        "decision",
    )
    errors.extend(found)
    evidence, found = _parse_evidence(lines[slice(*ranges["Repository evidence"])])
    errors.extend(found)
    acceptance, found = _parse_acceptance(lines[slice(*ranges["Acceptance criteria"])])
    errors.extend(found)
    questions, found = _parse_questions(lines[slice(*ranges["Open questions"])])
    errors.extend(found)
    errors.extend(
        _content_rules(
            lines,
            ranges,
            metadata,
            requirements,
            decisions,
            evidence,
            acceptance,
            questions,
        )
    )
    return ParsedSpec(
        metadata, requirements, decisions, questions, evidence, acceptance
    ), errors


def _content_rules(
    lines: list[str | None],
    ranges: dict[str, tuple[int, int]],
    metadata: dict[str, str],
    requirements: list[Entry],
    decisions: list[Entry],
    evidence: list[Evidence],
    acceptance: list[list[int]],
    questions: list[Entry],
) -> list[str]:
    """Apply cross-entry and status rules."""
    errors: list[str] = []
    if not any(lines[slice(*ranges["Goal"])]):
        errors.append("Goal is empty")
    out_scope = [line for line in lines[slice(*ranges["Out of scope"])] if line]
    if not out_scope or any(not line.startswith("- ") for line in out_scope):
        errors.append("Out of scope must contain bullets")
    evidence_values = {entry.key for entry in evidence}
    errors.extend(_entry_evidence_errors(decisions, evidence_values))
    errors.extend(_question_evidence_errors(questions, evidence_values))
    active_requirements = {
        entry.number for entry in requirements if entry.status == "active"
    }
    referenced = {number for group in acceptance for number in group}
    all_requirements = {entry.number for entry in requirements}
    errors.extend(
        f"acceptance references unknown requirement R{number}"
        for number in referenced - all_requirements
    )
    errors.extend(
        f"acceptance references superseded requirement R{number}"
        for number in referenced - active_requirements
        if number in all_requirements
    )
    errors.extend(
        "acceptance criterion repeats a requirement"
        for group in acceptance
        if len(group) != len(set(group))
    )
    errors.extend(
        f"active requirement R{number} has no acceptance criterion"
        for number in active_requirements - referenced
    )
    errors.extend(_affects_errors(questions, requirements, decisions))
    errors.extend(_supersession_errors(requirements, decisions))
    if metadata["Status"] == "Superseded" and metadata["Superseded by"] == "None":
        errors.append("Superseded specification needs a replacement")
    if metadata["Status"] != "Superseded" and metadata["Superseded by"] != "None":
        errors.append("only a Superseded specification can name a replacement")
    if metadata["Status"] in {"Ready", "Superseded"}:
        body = [line for line in lines[slice(*ranges["Open questions"])] if line]
        if body != ["None."]:
            errors.append(
                "ready and superseded specifications require Open questions: None."
            )
    errors.extend(_draft_marker_errors(lines, ranges))
    return errors


def _affects_errors(
    questions: list[Entry], requirements: list[Entry], decisions: list[Entry]
) -> list[str]:
    """Validate question requirement and decision references."""
    known = {f"R{entry.number}" for entry in requirements}
    known.update(f"D{entry.number}" for entry in decisions)
    errors: list[str] = []
    for question in questions:
        values = [value.strip() for value in (question.affects or "").split(",")]
        if not values or any(
            not re.fullmatch(r"[RD][1-9][0-9]*", value) for value in values
        ):
            errors.append(f"question {question.number} has invalid Affects")
        if len(values) != len(set(values)):
            errors.append(f"question {question.number} repeats an Affects reference")
        errors.extend(
            f"question {question.number} has unknown Affects reference {value}"
            for value in values
            if value not in known
        )
    return errors


def _entry_evidence_errors(entries: list[Entry], evidence: set[str]) -> list[str]:
    """Check decision evidence references."""
    return [
        f"entry {entry.number} has invalid evidence {entry.evidence}"
        for entry in entries
        if entry.evidence
        and (
            (entry.evidence.startswith("E") and entry.evidence not in evidence)
            or (
                not entry.evidence.startswith("E")
                and _evidence_value(entry.evidence) is None
            )
        )
    ]


def _question_evidence_errors(entries: list[Entry], evidence: set[str]) -> list[str]:
    """Check question evidence references."""
    return [
        f"question {entry.number} has invalid evidence {entry.evidence}"
        for entry in entries
        if entry.evidence
        and (
            (entry.evidence.startswith("E") and entry.evidence not in evidence)
            or (
                not entry.evidence.startswith("E")
                and _evidence_value(entry.evidence) is None
            )
        )
    ]


def _supersession_errors(
    requirements: list[Entry], decisions: list[Entry]
) -> list[str]:
    """Check superseded entry references."""
    errors: list[str] = []
    for entries, prefix in ((requirements, "R"), (decisions, "D")):
        numbers = {entry.number for entry in entries}
        active = {entry.number for entry in entries if entry.status == "active"}
        for entry in entries:
            if entry.status.startswith("superseded"):
                target = int(entry.status.rsplit(prefix, 1)[-1])
                if (
                    target <= entry.number
                    or target not in numbers
                    or target not in active
                ):
                    errors.append(f"{prefix}{entry.number} has invalid supersession")
    return errors


def _draft_marker_errors(
    lines: list[str | None], ranges: dict[str, tuple[int, int]]
) -> list[str]:
    """Reject exact draft markers outside fenced examples."""
    fields = [line for line in lines if line]
    return (
        ["draft marker in specification"]
        if any(_DRAFT_MARKER.search(line) for line in fields)
        else []
    )


def _inline_evidence(entries: list[Entry]) -> list[Evidence]:
    """Convert direct entry evidence into values checked by the snapshot gate."""
    return [
        evidence
        for entry in entries
        if entry.evidence and not entry.evidence.startswith("E")
        if (evidence := _evidence_value(entry.evidence)) is not None
    ]


def _working_evidence_path_error(root: Path, path: str) -> str | None:
    """Reject symlink components and resolved paths outside the repository."""
    candidate = root / path
    current = root
    for part in path.split("/"):
        current /= part
        if current.is_symlink():
            return f"evidence path contains a symlink: {path}"
    if not candidate.exists():
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return f"evidence path escapes the repository: {path}"
    return None


def _evidence_errors(root: Path, values: list[Evidence], mode: str) -> list[str]:
    """Validate repository evidence against one repository snapshot."""
    errors: list[str] = []
    for evidence in values:
        if evidence.path is None:
            continue
        if not _safe_repo_path(evidence.path):
            errors.append(f"unsafe evidence path: {evidence.path}")
            continue
        if mode == "working" and (
            path_error := _working_evidence_path_error(root, evidence.path)
        ):
            errors.append(path_error)
            continue
        data = _snapshot_bytes(root, evidence.path, mode)
        if data is None:
            errors.append(f"evidence path not found: {evidence.path}")
            continue
        is_link = (
            _index_symlink(root, evidence.path)
            if mode == "index"
            else (root / evidence.path).is_symlink()
        )
        if is_link:
            errors.append(f"evidence path is a symlink: {evidence.path}")
        if evidence.line and evidence.line > len(data.splitlines()):
            errors.append(f"evidence line is out of range: {evidence.value}")
    return errors


def _index_symlink(root: Path, path: str) -> bool:
    """Return whether the staged path has Git's symlink mode."""
    result = subprocess.run(
        ["git", "ls-files", "-s", "--", path],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return any(
        line.split(maxsplit=1)[0] == "120000" for line in result.stdout.splitlines()
    )


def _snapshot_bytes(root: Path, path: str, mode: str) -> bytes | None:
    """Read a path from the requested working-tree, HEAD, or index snapshot."""
    if mode == "index":
        return _git_bytes(root, ":", path)
    if mode == "head":
        return _git_bytes(root, "HEAD", path)
    target = root / path
    return target.read_bytes() if target.is_file() and not target.is_symlink() else None


def _stable_ids(items: list[Entry] | list[Evidence]) -> list[int]:
    """Extract comparable IDs from structured entries and evidence."""
    return [
        item.number if isinstance(item, Entry) else int(item.key[1:]) for item in items
    ]


def _baseline_errors(
    root: Path, path: str, current: ParsedSpec, mode: str
) -> list[str]:
    """Compare stable IDs and revision against the selected Git baseline."""
    baseline_bytes = _git_bytes(root, "HEAD", path)
    if baseline_bytes is None:
        return []
    try:
        baseline, errors = _parse_spec(baseline_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        return ["HEAD specification is not UTF-8"]
    if baseline is None or errors:
        return ["HEAD specification is invalid"]
    found: list[str] = []
    for label, old, new in (
        ("requirement", baseline.requirements, current.requirements),
        ("decision", baseline.decisions, current.decisions),
        ("evidence", baseline.evidence, current.evidence),
    ):
        old_ids = _stable_ids(old)
        new_ids = _stable_ids(new)
        if new_ids[: len(old_ids)] != old_ids:
            found.append(f"existing {label} IDs changed")
    if current.metadata["Revision"] <= baseline.metadata["Revision"] and mode != "head":
        found.append("Revision did not increase over HEAD")
    return found


def _path_errors(root: Path, path: Path) -> list[str]:
    """Validate the specification location and safe topic."""
    candidate = path if path.is_absolute() else root / path
    if candidate.is_symlink():
        return ["specification must not be a symlink"]
    try:
        relative = candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return ["specification is outside the repository"]
    parts = relative.split("/")
    if (
        len(parts) != 3
        or parts[0:2] != ["docs", "specs"]
        or parts[2].split(".")[-1] != "md"
    ):
        return ["specification must be docs/specs/<topic>.md"]
    topic = parts[2][:-3]
    return [] if _SLUG.fullmatch(topic) else ["specification topic is not a safe slug"]


def _status_errors(root: Path, parsed: ParsedSpec, mode: str) -> list[str]:
    """Validate the complete replacement specification."""
    replacement = parsed.metadata["Superseded by"]
    if replacement == "None":
        return []
    snapshot = "index" if mode == "index" else "head" if mode == "ready" else "working"
    data = _snapshot_bytes(root, replacement, snapshot)
    if data is None or not _tracked(root, replacement):
        return [f"replacement specification not found: {replacement}"]
    try:
        replacement_doc, parse_errors = _parse_spec(data.decode("utf-8"))
    except UnicodeDecodeError:
        return [f"replacement specification is not UTF-8: {replacement}"]
    if replacement_doc is None or parse_errors:
        return [f"replacement specification is invalid: {replacement}"]
    if replacement_doc.metadata["Status"] != "Ready":
        return ["replacement specification is not Ready"]
    findings = check_file(root / replacement, mode, nested=True)
    return [f"replacement: {finding}" for finding in findings]


def check_file(path: Path, mode: str = "working", nested: bool = False) -> list[str]:
    """Return findings for one specification file."""
    root = _repo_root()
    findings = _path_errors(root, path)
    candidate = path if path.is_absolute() else root / path
    relative = candidate.resolve().relative_to(root).as_posix() if not findings else ""
    data = _snapshot_bytes(root, relative, mode) if relative else None
    if data is None:
        return [*findings, "specification cannot be read"]
    if mode == "index" and _index_symlink(root, relative):
        findings.append("specification must not be a symlink")
    if mode == "ready" and (
        not _tracked(root, relative) or not _working_tree_clean(root)
    ):
        findings.append("ready specification requires a clean tracked worktree")
    try:
        parsed, errors = _parse_spec(data.decode("utf-8"))
    except UnicodeDecodeError:
        return [*findings, "specification is not UTF-8"]
    findings.extend(errors)
    if parsed is None:
        return findings
    topic = Path(relative).stem
    if parsed.metadata.get("Topic") != topic:
        findings.append("Topic does not match filename")
    evidence = parsed.evidence + _inline_evidence(parsed.decisions + parsed.questions)
    findings.extend(
        _evidence_errors(root, evidence, "head" if mode == "ready" else mode)
    )
    baseline = _git_bytes(root, "HEAD", relative)
    if baseline != data:
        findings.extend(_baseline_errors(root, relative, parsed, mode))
    if not nested:
        findings.extend(_status_errors(root, parsed, mode))
    if mode == "ready" and _git_bytes(root, "HEAD", relative) != data:
        findings.append("ready specification differs from HEAD")
    return findings


def _tracked_specs(root: Path) -> list[Path]:
    """List tracked specification files."""
    result = subprocess.run(
        ["git", "ls-files", "--", "docs/specs/*.md"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def _arguments(argv: list[str]) -> argparse.Namespace:
    """Parse one complete-document gate mode."""
    parser = argparse.ArgumentParser(prog="spec-guard.py")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", metavar="FILE")
    group.add_argument("--ready", metavar="FILE")
    group.add_argument("--check-index", metavar="FILE")
    group.add_argument("--check-all", action="store_true")
    return parser.parse_args(argv)


def _print_findings(findings: list[str]) -> int:
    """Print gate findings and return the documented exit code."""
    if not findings:
        return 0
    for finding in findings:
        print(finding)
    print(f"spec-check: {len(findings)} finding(s)")
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run the selected specification gate."""
    try:
        args = _arguments(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    try:
        if args.check_all:
            findings = [
                f"{path}: {finding}"
                for path in _tracked_specs(_repo_root())
                for finding in check_file(path)
            ]
        else:
            selected = args.check or args.ready or args.check_index
            mode = "ready" if args.ready else "index" if args.check_index else "working"
            findings = check_file(Path(selected), mode)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"spec-check: gate error: {exc}", file=sys.stderr)
        return 1
    return _print_findings(findings)


if __name__ == "__main__":
    sys.exit(main())
