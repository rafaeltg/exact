#!/usr/bin/env python3
"""Ruff lint-fix then format after a Cursor agent edits a Python file."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

PYTHON_SUFFIXES = {".py", ".pyi"}


def _payload() -> dict:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve(path: str, roots: list[str]) -> Path | None:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    for root in roots:
        nested = Path(root) / path
        if nested.is_file():
            return nested
    return None


def _ruff(roots: list[str]) -> str | None:
    for root in roots:
        bundled = Path(root) / ".venv" / "bin" / "ruff"
        if os.access(bundled, os.X_OK):
            return str(bundled)
    return which("ruff")


def _edited_path(payload: dict, roots: list[str]) -> Path | None:
    tool_input = (
        payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    )
    raw = (
        payload.get("file_path")
        or tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("relative_path")
        or ""
    )
    return _resolve(str(raw), roots)


def main() -> int:
    payload = _payload()
    roots = [os.getcwd(), *payload.get("workspace_roots", [])]
    path = _edited_path(payload, roots)
    if path is None or path.suffix not in PYTHON_SUFFIXES:
        return 0

    ruff = _ruff(roots)
    if not ruff:
        return 0

    file = str(path)
    for args in (
        [ruff, "check", "--fix", "--quiet", file],
        [ruff, "format", "--quiet", file],
    ):
        result = subprocess.run(args, check=False, capture_output=True, text=True)
        if result.returncode != 0 and result.stderr:
            sys.stderr.write(result.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
