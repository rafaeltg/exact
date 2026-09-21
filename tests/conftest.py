from __future__ import annotations

import pytest

# Only ``exact.cli.main`` reads these, but every module that drives ``main``
# would trace, print detail lines, or write beside a shell ``EXACT_DB``.
_RUN_ENV_NAMES = ("EXACT_TRACE", "EXACT_TRACE_PATH", "EXACT_VERBOSE", "EXACT_DB")


@pytest.fixture(autouse=True)
def _no_inherited_run_knobs(monkeypatch):
    """A shell export of a trace or verbose knob must not steer any test."""
    for name in _RUN_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
