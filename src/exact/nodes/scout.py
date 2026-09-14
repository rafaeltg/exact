from __future__ import annotations

from exact.config import Runtime
from exact.intent import academic_signal
from exact.tools.elicit import ElicitClient
from exact.tools.elicit import dump_sources as dump_elicit
from exact.tools.exa import ExaClient
from exact.tools.exa import dump_sources as dump_exa
from exact.usage import tool_event


def scout(state: dict, runtime: Runtime) -> dict:
    settings = runtime.settings
    query = state["initial_query"]
    hits: list[dict] = []
    errors: list[str] = []
    usage: list[dict] = []
    try:
        exa = runtime.extras.get("exa") or ExaClient(
            settings.exa_api_key, settings.http_timeout
        )
        hits.extend(dump_exa(exa.search(query, num=settings.max_hits)))
        usage.append(tool_event("exa_search", "scout"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"exa scout failed: {exc}")
    if academic_signal(query) and settings.elicit_api_key:
        try:
            elicit = runtime.extras.get("elicit") or ElicitClient(
                settings.elicit_api_key, settings.http_timeout
            )
            hits.extend(dump_elicit(elicit.search(query, num=settings.max_hits)))
            usage.append(tool_event("elicit_search", "scout"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"elicit scout failed: {exc}")
    for i, hit in enumerate(hits, start=1):
        hit["id"] = f"src_scout_{i}"
    return {
        "scout_hits": hits,
        "errors": errors,
        "usage": usage,
        "clarify_turns": state.get("clarify_turns") or 0,
    }
