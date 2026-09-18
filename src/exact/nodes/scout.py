from __future__ import annotations

from itertools import zip_longest
from typing import NamedTuple

from exact.config import Runtime
from exact.intent import academic_signal
from exact.models import ExactState
from exact.tools.exa import ExaClient
from exact.tools.exa import dump_sources as dump_exa
from exact.usage import tool_event


class _Leg(NamedTuple):
    """What one scout search contributed to the node's return value."""

    hits: list[dict]
    usage: list[dict]
    errors: list[str]


def _leg(exa: ExaClient, query: str, num: int, category: str | None, kind: str) -> _Leg:
    """Run one scout search; a failure becomes an error line, never a raise."""
    label = f"exa {category}" if category else "exa"
    try:
        hits = dump_exa(exa.search(query, num=num, category=category))
    except Exception as exc:  # noqa: BLE001
        return _Leg([], [], [f"{label} scout failed: {exc}"])
    return _Leg(hits, [tool_event(kind, "scout")], [])


def _interleave(web: list[dict], papers: list[dict]) -> list[dict]:
    """Alternate the two lanes so a later slice cannot drop one of them."""
    pairs = zip_longest(web, papers)
    return [hit for pair in pairs for hit in pair if hit is not None]


def scout(state: ExactState, runtime: Runtime) -> ExactState:
    """Run the Exa scout before clarify; mint ``src_scout_*`` ids.

    Web always runs. An academic signal adds a publication search. No key
    gates either lane.
    """
    settings = runtime.settings
    query = state["initial_query"]
    exa = runtime.extras.get("exa") or ExaClient(
        settings.exa_api_key, settings.http_timeout
    )
    web = _leg(exa, query, settings.max_hits, None, "exa_search")
    papers = (
        _leg(exa, query, settings.max_hits, "publication", "exa_publication_search")
        if academic_signal(query)
        else _Leg([], [], [])
    )
    hits = _interleave(web.hits, papers.hits)
    for i, hit in enumerate(hits, start=1):
        hit["id"] = f"src_scout_{i}"
    errors = [*web.errors, *papers.errors]
    if exa.degraded:
        errors.append(exa.degraded)
    return {
        "scout_hits": hits,
        "errors": errors,
        "usage": [*web.usage, *papers.usage],
        "clarify_turns": state.get("clarify_turns") or 0,
    }
