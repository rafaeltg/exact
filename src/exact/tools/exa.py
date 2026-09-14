from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from exa_py import Exa

from exact.models import Source


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _snippet(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text[:limit]


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 429 or (isinstance(status, int) and status >= 500)


def _timed(fetch, timeout: float):
    """Run fetch with a wall-clock timeout.

    On timeout the worker is joined before control returns so a retry cannot
    overlap an in-flight Exa SDK call (the SDK has no cancel/timeout API).
    Late results after the soft timeout are discarded.
    """
    outcome: list = []

    def run() -> None:
        try:
            outcome.append((True, fetch()))
        except Exception as exc:  # noqa: BLE001
            outcome.append((False, exc))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if not outcome:
        worker.join()
        raise TimeoutError("exa request timed out")
    ok, value = outcome[0]
    if ok:
        return value
    raise value


def _invoke(fetch, timeout: float):
    try:
        return _timed(fetch, timeout)
    except Exception as exc:
        if not _retryable(exc):
            raise
        return _timed(fetch, timeout)


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return getattr(value, "__dict__", None) or {}


def _entity_props(item, entity_type: str) -> dict | None:
    for ent in getattr(item, "entities", None) or []:
        data = _as_dict(ent)
        if data.get("type") == entity_type:
            return _as_dict(data.get("properties"))
    return None


def _format_person(props: dict) -> str:
    parts: list[str] = []
    if props.get("name"):
        parts.append(str(props["name"]))
    if props.get("location"):
        parts.append(str(props["location"]))
    history = props.get("workHistory") or []
    if history:
        job = _as_dict(history[0])
        company = _as_dict(job.get("company")).get("name")
        role = " at ".join(p for p in (job.get("title"), company) if p)
        if role:
            parts.append(str(role))
    return " | ".join(parts)


def _format_company(props: dict) -> str:
    parts: list[str] = []
    if props.get("name"):
        parts.append(str(props["name"]))
    if props.get("foundedYear") is not None:
        parts.append(f"founded {props['foundedYear']}")
    hq = _as_dict(props.get("headquarters"))
    place = ", ".join(p for p in (hq.get("city"), hq.get("country")) if p)
    if place:
        parts.append(place)
    fin = _as_dict(props.get("financials"))
    if fin.get("fundingTotal") is not None:
        parts.append(f"funding ${fin['fundingTotal']}")
    latest = _as_dict(fin.get("fundingLatestRound"))
    if latest.get("name"):
        parts.append(str(latest["name"]))
    return " | ".join(parts)


def _entity_line(item) -> str:
    person = _entity_props(item, "person")
    if person:
        return _format_person(person)
    company = _entity_props(item, "company")
    if company:
        return _format_company(company)
    return ""


def _item_text(item) -> str:
    highlights = getattr(item, "highlights", None) or []
    if highlights:
        return " ".join(highlights)
    return getattr(item, "text", None) or ""


def _item_snippet(item) -> str:
    body = _item_text(item)
    line = _entity_line(item)
    if line and body:
        return _snippet(f"{line}. {body}")
    return _snippet(line or body)


class ExaClient:
    def __init__(self, api_key: str, timeout: float = 20.0, *, sdk=None, clock=None):
        self.api_key = api_key
        self.timeout = timeout
        self._client = sdk
        self._clock = clock or _now

    def _exa(self):
        if self._client is None:
            self._client = Exa(self.api_key)
        return self._client

    def _source(self, i: int, item, fallback_url: str) -> Source:
        url = getattr(item, "url", None) or fallback_url or None
        return Source(
            id=f"tmp_{i}",
            title=getattr(item, "title", None) or url or "untitled",
            url=url,
            snippet=_item_snippet(item),
            provider="exa",
            retrieved_at=self._clock(),
        )

    def _map(self, result, fallback_url: str) -> list[Source]:
        items = getattr(result, "results", None) or []
        return [self._source(i, item, fallback_url) for i, item in enumerate(items)]

    def search(
        self, query: str, num: int = 5, *, category: str | None = None
    ) -> list[Source]:
        def fetch():
            kwargs: dict[str, Any] = {"num_results": num, "highlights": True}
            if category in ("people", "company"):
                kwargs["category"] = category
            return self._exa().search_and_contents(query, **kwargs)

        return self._map(_invoke(fetch, self.timeout), "")

    def highlights(self, url: str) -> list[Source]:
        result = _invoke(
            lambda: self._exa().get_contents([url], highlights=True), self.timeout
        )
        return self._map(result, url)


def dump_sources(sources: list[Source]) -> list[dict[str, Any]]:
    return [s.model_dump() for s in sources]
