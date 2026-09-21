"""JSONL trace sidecar: one envelope line per run event.

This module imports nothing from ``exact``. Every other module may therefore
import it without making a cycle, which is what lets the node layer reach a
tracer through ``Runtime``.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, override

# An added field keeps this number. A rename or a removal raises it.
ENVELOPE_VERSION = 1

# One cap for every error text the sidecar carries, with no marker.
ERROR_TEXT_MAX = 500

# The ``t{wave}_{i}`` grammar of a research topic id.
_TOPIC_ID = re.compile(r"t(\d+)_\d+")


def clip_error(text: str) -> str:
    """Cut one error text to the length the sidecar accepts."""
    return text[:ERROR_TEXT_MAX]


def crumb(row: dict) -> dict:
    """The four-key source reference a ``tool`` line carries.

    Both retrieval legs build it here, so the ids a consumer joins on cannot
    drift apart. Each of the four values may be ``None``.
    """
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "url": row.get("url"),
        "doi": row.get("doi"),
    }


def wave_of(topic_id: str | None) -> int | None:
    """The wave a research topic id names; ``None`` for any other id.

    The topic id grammar is no contract for a trace reader, so every line that
    names a topic carries this value beside it.
    """
    match = _TOPIC_ID.fullmatch(topic_id or "")
    return int(match.group(1)) if match else None


class Tracer(Protocol):
    """The sidecar seam one run injects through ``Runtime``."""

    run_id: str
    dropped: int

    def emit(self, kind: str, data: dict) -> None:
        """Write one envelope. It never raises."""

    def record_drop(self, exc: Exception) -> None:
        """Count one event the run could not write."""

    def close(self) -> None:
        """Release the sink. A later emit is swallowed."""


class NullTracer(Tracer):
    """The tracer of a run with tracing off. It writes nothing."""

    def __init__(self) -> None:
        self.run_id = ""
        self.dropped = 0

    @override
    def emit(self, kind: str, data: dict) -> None:
        return

    @override
    def record_drop(self, exc: Exception) -> None:
        return

    @override
    def close(self) -> None:
        return


class JsonlTracer(Tracer):
    """Append one UTF-8 JSONL envelope per emit, with no write buffer.

    Each line is one unbuffered write, so a failed write leaves no bytes for a
    later write or ``close`` to flush.
    """

    def __init__(self, path: Path, thread_id: str):
        self.run_id = str(uuid.uuid4())
        self.dropped = 0
        self._thread_id = thread_id
        self._seq = 0
        self._closed = False
        self._handle = path.open("ab", buffering=0)
        # Reentrant: a write failure calls ``record_drop`` while ``emit``
        # still holds the lock, and both guard the same state.
        self._lock = threading.RLock()

    def _envelope(self, kind: str, data: dict, seq: int) -> dict:
        return {
            "v": ENVELOPE_VERSION,
            "ts": datetime.now(UTC).isoformat(timespec="microseconds"),
            "run_id": self.run_id,
            "thread_id": self._thread_id,
            "seq": seq,
            "kind": kind,
            "data": data,
        }

    def _write_all(self, payload: bytes) -> None:
        # A raw write may be short; loop so one envelope is never left cut.
        view = memoryview(payload)
        while view:
            view = view[self._handle.write(view) :]

    @override
    def emit(self, kind: str, data: dict) -> None:
        with self._lock:
            if self._closed:
                return
            seq = self._seq + 1
            try:
                line = json.dumps(self._envelope(kind, data, seq), ensure_ascii=False)
                self._write_all((line + "\n").encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                self.record_drop(exc)
                return
            # A dropped event takes no number, so ``seq`` counts written lines.
            self._seq = seq

    @override
    def record_drop(self, exc: Exception) -> None:
        with self._lock:
            self.dropped += 1
            if self.dropped > 1:
                return
        print(
            f"warning: trace write failed: {exc}; "
            "later failures are counted in run_end",
            file=sys.stderr,
        )

    @override
    def close(self) -> None:
        with self._lock:
            self._closed = True
            try:
                self._handle.close()
            except OSError as exc:
                # Called from the CLI ``finally``: a raise would hide the run's
                # own outcome.
                self.record_drop(exc)
