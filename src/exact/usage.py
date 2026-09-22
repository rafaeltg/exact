"""Token, tool-call, and estimated-cost observability for a query run.

USD is computed at print time from the dated rate table below. Events store
counts and tokens only. Vendor retries inside Exa/Elicit clients are not
metered: one public client call is one event.

LangChain Anthropic maps usage so `input_tokens` is the total (uncached +
cache_read + cache_creation). Cache breakdown lives in
`input_token_details`. Pricing: uncached at base input, cache_read at 0.1x,
cache_creation at 1.25x (5m write), output at base output.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel


class StructuredOutputError(Exception):
    """Structured LLM output was missing or failed to parse."""


# Rate table dated 2026-09-14. Estimates only; vendor prices change.
RATES_AS_OF = "2026-09-14"

# Claude input/output USD per million tokens (leaf id substring → rates).
_LLM_RATES: list[tuple[str, float, float]] = [
    ("haiku-4-5", 1.0, 5.0),
    ("sonnet-4-6", 3.0, 15.0),
    ("sonnet-4-5", 3.0, 15.0),
]

CACHE_READ_MULT = 0.1
CACHE_WRITE_MULT = 1.25

EXA_SEARCH_USD = 0.007
EXA_HIGHLIGHTS_USD = 0.001


def tool_event(kind: str, node: str, *, calls: int = 1) -> dict[str, Any]:
    """Build a vendor tool-call usage event (one public client call → one event)."""
    return {"kind": kind, "node": node, "calls": calls}


def llm_event(
    *,
    node: str,
    role: str,
    model: str,
    usage: dict[str, int] | None = None,
    calls: int = 1,
) -> dict[str, Any]:
    """Build an llm usage event. ``usage`` holds token counts when present."""
    tokens = usage or {}
    return {
        "kind": "llm",
        "node": node,
        "role": role,
        "model": model,
        "input_tokens": int(tokens.get("input_tokens") or 0),
        "output_tokens": int(tokens.get("output_tokens") or 0),
        "cache_read": int(tokens.get("cache_read") or 0),
        "cache_creation": int(tokens.get("cache_creation") or 0),
        "calls": calls,
    }


def _cache_from_meta(meta: Any) -> tuple[int, int]:
    if not isinstance(meta, dict):
        return 0, 0
    details = meta.get("input_token_details") or {}
    if not isinstance(details, dict):
        return 0, 0
    read = int(details.get("cache_read") or 0)
    # Prefer TTL-specific write counts when LangChain zeros the generic key.
    write = int(details.get("cache_creation") or 0)
    write += int(details.get("ephemeral_5m_input_tokens") or 0)
    write += int(details.get("ephemeral_1h_input_tokens") or 0)
    return read, write


def _tokens_from_meta(meta: Any) -> tuple[int, int, int, int]:
    if not isinstance(meta, dict):
        return 0, 0, 0, 0
    inp = int(meta.get("input_tokens") or 0)
    out = int(meta.get("output_tokens") or 0)
    read, write = _cache_from_meta(meta)
    return inp, out, read, write


def _from_message(msg: Any, *, node: str, role: str, model: str) -> dict:
    inp, out, read, write = _tokens_from_meta(getattr(msg, "usage_metadata", None))
    return llm_event(
        node=node,
        role=role,
        model=model,
        usage={
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read": read,
            "cache_creation": write,
        },
    )


def _is_ai_message(msg: Any) -> bool:
    if type(msg).__name__ == "AIMessage":
        return True
    return getattr(msg, "type", None) == "ai"


def invoke_structured(
    model: Any,
    schema: type[BaseModel],
    messages: list[Any],
    *,
    node: str,
    role: str,
    model_id: str,
) -> tuple[Any, list[dict[str, Any]]]:
    """Invoke structured output; return (parsed, usage events).

    Prefer include_raw=True so live models expose usage_metadata. Fakes that
    ignore kwargs and return a Pydantic object yield a zero-token llm event.
    """
    structured = model.with_structured_output(schema, include_raw=True)
    try:
        result = structured.invoke(messages)
    except OutputParserException as exc:
        # Anthropic cannot force a tool call while thinking is on, so the
        # model may answer in prose. That escapes the include_raw fallback.
        raise StructuredOutputError(f"{node}: {exc}") from exc
    if isinstance(result, BaseModel):
        return result, [llm_event(node=node, role=role, model=model_id)]
    if not isinstance(result, dict):
        if result is None:
            raise StructuredOutputError(f"{node}: structured output missing")
        return result, [llm_event(node=node, role=role, model=model_id)]
    parsed = result.get("parsed")
    raw = result.get("raw")
    if parsed is None:
        raise StructuredOutputError(f"{node}: structured output missing")
    return parsed, [_from_message(raw, node=node, role=role, model=model_id)]


def invoke_text(
    model: Any,
    messages: list[Any],
    *,
    node: str,
    role: str,
    model_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Invoke a plain chat model and return (text, usage events)."""
    report = model.invoke(messages)
    # ``.text`` joins only text blocks; ``.content`` may be a list of blocks
    # (thinking + text) that no downstream string operation accepts.
    text = str(getattr(report, "text", "") or "") or str(report)
    return text, [_from_message(report, node=node, role=role, model=model_id)]


def llm_events_from_messages(
    messages: list[Any],
    *,
    node: str,
    role: str,
    model: str,
) -> list[dict[str, Any]]:
    """Collect llm usage events from AI messages in an agent transcript."""
    events: list[dict[str, Any]] = []
    for msg in messages or []:
        if not _is_ai_message(msg):
            continue
        events.append(_from_message(msg, node=node, role=role, model=model))
    return events


def _model_leaf(model: str) -> str:
    return model.split(":", 1)[-1].lower()


def _rates_for(model: str) -> tuple[float, float] | None:
    leaf = _model_leaf(model)
    for key, in_rate, out_rate in _LLM_RATES:
        if key in leaf:
            return in_rate, out_rate
    return None


def llm_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> float | None:
    """Estimate LLM USD from the dated rate table; None when the model is unknown."""
    rates = _rates_for(model)
    if rates is None:
        return None
    in_rate, out_rate = rates
    cached = cache_read + cache_creation
    uncached = max(0, input_tokens - cached)
    return (
        uncached * in_rate
        + cache_read * in_rate * CACHE_READ_MULT
        + cache_creation * in_rate * CACHE_WRITE_MULT
        + output_tokens * out_rate
    ) / 1_000_000


# Every Exa search kind. Confirmed 2026-09-17 against a live /search response:
# a publication search bills the same $0.007 as a web search, so one rate and
# one printed counter cover them all. Highlights and Elicit price apart.
EXA_SEARCH_KINDS = frozenset(
    {
        "exa_search",
        "exa_people_search",
        "exa_company_search",
        "exa_publication_search",
    }
)
_METERED_TOOL_KINDS = EXA_SEARCH_KINDS | {"exa_highlights", "elicit_search"}

# The group key an ``llm`` event falls under when its ``model`` or ``node``
# field is missing or empty.
_UNKNOWN_KEY = "(unknown)"


def _empty_llm_totals() -> dict:
    return {
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "llm_cost": 0.0,
        "llm_unpriced_calls": 0,
    }


def _empty_totals() -> dict:
    return {
        **_empty_llm_totals(),
        "exa_search": 0,
        "exa_highlights": 0,
        "elicit_search": 0,
    }


def _fold_llm(totals: dict, ev: dict, calls: int) -> None:
    totals["llm_calls"] += calls
    inp = int(ev.get("input_tokens") or 0)
    out = int(ev.get("output_tokens") or 0)
    read = int(ev.get("cache_read") or 0)
    write = int(ev.get("cache_creation") or 0)
    totals["input_tokens"] += inp
    totals["output_tokens"] += out
    totals["cache_read"] += read
    totals["cache_creation"] += write
    priced = llm_usd(
        str(ev.get("model") or ""),
        inp,
        out,
        cache_read=read,
        cache_creation=write,
    )
    if priced is None:
        totals["llm_unpriced_calls"] += calls
        return
    totals["llm_cost"] += priced


def _fold_tool(totals: dict, kind: str, calls: int) -> None:
    if kind in EXA_SEARCH_KINDS:
        totals["exa_search"] += calls
    elif kind == "exa_highlights":
        totals["exa_highlights"] += calls
    elif kind == "elicit_search":
        totals["elicit_search"] += calls


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold usage events into totals and estimated costs."""
    totals = _empty_totals()
    for ev in events or []:
        kind = ev.get("kind")
        calls = int(ev.get("calls") or 1)
        if kind == "llm":
            _fold_llm(totals, ev, calls)
            continue
        _fold_tool(totals, str(kind or ""), calls)
    exa_cost = (
        totals["exa_search"] * EXA_SEARCH_USD
        + totals["exa_highlights"] * EXA_HIGHLIGHTS_USD
    )
    totals["exa_cost"] = exa_cost
    totals["total"] = exa_cost + totals["llm_cost"]
    return totals


def _group_order(item: tuple[str, dict]) -> tuple[float, int, str]:
    """Sort key for one group line: priced USD desc, tokens desc, key asc."""
    key, totals = item
    tokens = totals["input_tokens"] + totals["output_tokens"]
    # Float sums depend on event order. Rounding removes that noise, so equal
    # USD falls through to tokens and key. Rate-table USD steps are far larger.
    return (-round(totals["llm_cost"], 10), -tokens, key)


def llm_groups(
    events: list[dict[str, Any]], field: Literal["model", "node"]
) -> list[tuple[str, dict[str, Any]]]:
    """Fold ``llm`` events into per-``field`` totals, sorted by ``_group_order``.

    An event with a missing or empty ``field`` value groups under
    ``_UNKNOWN_KEY``. Non-``llm`` events are skipped.
    """
    groups: dict[str, dict[str, Any]] = {}
    for ev in events or []:
        if ev.get("kind") != "llm":
            continue
        key = str(ev.get(field) or _UNKNOWN_KEY)
        totals = groups.setdefault(key, _empty_llm_totals())
        _fold_llm(totals, ev, int(ev.get("calls") or 1))
    return sorted(groups.items(), key=_group_order)


def _llm_fields(t: dict) -> str:
    """The calls/tokens fields shared by the total row and every group row."""
    return f"{t['llm_calls']} calls  {t['input_tokens']} in  {t['output_tokens']} out"


def _cache_lines(t: dict) -> list[str]:
    """The cache sub-line of one row; empty when the row has no cache tokens."""
    if not (t["cache_read"] or t["cache_creation"]):
        return []
    return [f"        cache  {t['cache_read']} read  {t['cache_creation']} write"]


def _priced_usd(t: dict) -> str:
    """The USD field of a row, with its unpriced-call count when non-zero."""
    n = t["llm_unpriced_calls"]
    mark = f" + {n} unpriced" if n else ""
    return f"${t['llm_cost']:.4f}{mark}"


def _model_line(key: str, t: dict) -> str:
    """One ``by model`` row; a model the rate table cannot price reads unpriced."""
    usd = "unpriced" if t["llm_unpriced_calls"] else f"${t['llm_cost']:.4f}"
    return f"    {key}  {_llm_fields(t)}   {usd}"


def _node_line(key: str, t: dict) -> str:
    """One ``by node`` row; a node mixing priced and unpriced models sums both."""
    return f"    {key}  {_llm_fields(t)}   {_priced_usd(t)}"


def _group_lines(
    label: str,
    groups: list[tuple[str, dict]],
    line: Callable[[str, dict], str],
) -> list[str]:
    """One labelled group block: its header, then each row and cache sub-line."""
    lines = [f"  {label}"]
    for key, t in groups:
        lines.append(line(key, t))
        lines += _cache_lines(t)
    return lines


def _breakdown_lines(events: list[dict[str, Any]]) -> list[str]:
    """The ``by model`` and ``by node`` group blocks; empty with no llm events."""
    models = llm_groups(events, "model")
    if not models:
        return []
    lines = _group_lines("by model", models, _model_line)
    lines += _group_lines("by node", llm_groups(events, "node"), _node_line)
    return lines


def format_usage(
    events: list[dict[str, Any]], *, effort: str | None = None
) -> list[str]:
    """CLI ``## Usage`` lines; empty when there are no events."""
    if not events:
        return []
    a = aggregate(events)
    lines = ["## Usage" if effort is None else f"## Usage (effort={effort})"]
    lines.append(f"llm     {_llm_fields(a)}   {_priced_usd(a)}")
    lines += _cache_lines(a)
    lines += _breakdown_lines(events)
    lines.append(
        f"exa     {a['exa_search']} search  {a['exa_highlights']} highlights"
        f"        ${a['exa_cost']:.4f}"
    )
    lines.append(
        f"elicit  {a['elicit_search']} search                      (subscription)"
    )
    if not a["llm_unpriced_calls"]:
        lines.append(f"total                                 ${a['total']:.4f}")
    else:
        lines.append(
            f"total                                 ${a['total']:.4f}+ (llm unpriced)"
        )
    return lines


def tool_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count vendor tool events by kind for status lines."""
    counts: dict[str, int] = {}
    for ev in events or []:
        kind = ev.get("kind")
        if kind in _METERED_TOOL_KINDS:
            counts[kind] = counts.get(kind, 0) + int(ev.get("calls") or 1)
    return counts
