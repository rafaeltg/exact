from __future__ import annotations

from collections.abc import Mapping
from itertools import zip_longest
from typing import Any, NamedTuple

from exact.config import Runtime
from exact.intent import academic_signal
from exact.models import ExactState
from exact.prefs import exa_filters, filter_suffix, state_prefs
from exact.tools.exa import ExaClient
from exact.tools.exa import dump_sources as dump_exa
from exact.trace import clip_error, crumb
from exact.usage import tool_event


class _Leg(NamedTuple):
    """What one scout search contributed to the node's return value."""

    hits: list[dict]
    usage: list[dict]
    errors: list[str]
    exc_text: str | None = None


def _leg(
    exa: ExaClient,
    query: str,
    num: int,
    category: str | None,
    kind: str,
    filters: Mapping[str, Any],
) -> _Leg:
    """Run one scout search; a failure becomes an error line, never a raise.

    A filtered leg that comes back empty says so: the filters, not the query,
    may be why clarify saw nothing.
    """
    label = f"exa {category}" if category else "exa"
    try:
        hits = dump_exa(exa.search(query, num=num, category=category, filters=filters))
    except Exception as exc:  # noqa: BLE001
        return _Leg([], [], [f"{label} scout failed: {exc}"], str(exc))
    errors = []
    if not hits and filters:
        errors.append(f"{label} scout: no hits{filter_suffix(filters)}")
    return _Leg(hits, [tool_event(kind, "scout")], errors)


def _runs_papers(source_mix: str, query: str) -> bool:
    """Whether the scout also searches publications under this source mix."""
    if source_mix == "web":
        return False
    if source_mix in ("academic", "mixed"):
        return True
    return academic_signal(query)


def _scout_tool_event(leg: _Leg, kind: str, query: str) -> dict:
    """The ``tool`` summary of one scout leg that ran."""
    failed = leg.exc_text is not None
    return {
        "name": kind,
        "outcome": "error" if failed else "ok",
        "topic_id": "scout",
        "wave": None,
        "query": query,
        "url": None,
        "hit_count": None if failed else len(leg.hits),
        "sources": [crumb(hit) for hit in leg.hits],
        "error": clip_error(leg.exc_text) if leg.exc_text is not None else None,
    }


def _interleave(web: list[dict], papers: list[dict]) -> list[dict]:
    """Alternate the two lanes so a later slice cannot drop one of them."""
    pairs = zip_longest(web, papers)
    return [hit for pair in pairs for hit in pair if hit is not None]


def scout(state: ExactState, runtime: Runtime) -> ExactState:
    """Run the Exa scout before clarify; mint ``src_scout_*`` ids.

    Web always runs. ``source_mix`` decides the publication search, and under
    ``auto`` an academic signal does. No key gates either lane.
    """
    settings = runtime.settings
    query = state["initial_query"]
    exa = runtime.extras.get("exa") or ExaClient(
        settings.exa_api_key, settings.http_timeout
    )
    prefs = state_prefs(state)
    filters = exa_filters(prefs)
    num = settings.max_hits
    academic = _runs_papers(prefs["source_mix"], query)
    web = _leg(exa, query, num, None, "exa_search", filters)
    papers = (
        _leg(exa, query, num, "publication", "exa_publication_search", filters)
        if academic
        else _Leg([], [], [])
    )
    hits = _interleave(web.hits, papers.hits)
    for i, hit in enumerate(hits, start=1):
        hit["id"] = f"src_scout_{i}"
    # After the id loop: each leg's hit dicts now carry their minted ids.
    runtime.tracer.emit("tool", _scout_tool_event(web, "exa_search", query))
    if academic:
        runtime.tracer.emit(
            "tool", _scout_tool_event(papers, "exa_publication_search", query)
        )
    errors = [*web.errors, *papers.errors]
    if exa.degraded:
        errors.append(exa.degraded)
    return {
        "scout_hits": hits,
        "errors": errors,
        "usage": [*web.usage, *papers.usage],
        "clarify_turns": state.get("clarify_turns") or 0,
    }
