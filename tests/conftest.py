from __future__ import annotations

import pytest

# Only ``exact.cli.main`` reads these, but every module that drives ``main``
# would trace, print detail lines, or write beside a shell ``EXACT_DB``.
_RUN_ENV_NAMES = (
    "EXACT_TRACE",
    "EXACT_TRACE_PATH",
    "EXACT_VERBOSE",
    "EXACT_DB",
    "EXACT_LANGUAGE",
    "EXACT_TONE",
    "EXACT_LENGTH",
    "EXACT_STRUCTURE",
    "EXACT_SOURCE_MIX",
    "EXACT_INCLUDE_DOMAINS",
    "EXACT_EXCLUDE_DOMAINS",
    "EXACT_DENYLIST",
    "EXACT_RECENCY",
    "EXACT_PREFER_PRIMARY",
    "EXACT_NEWS_BIAS",
    "EXACT_CLARIFY_MODE",
)


@pytest.fixture(autouse=True)
def _no_inherited_run_knobs(monkeypatch):
    """A shell export of a trace or verbose knob must not steer any test."""
    for name in _RUN_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
