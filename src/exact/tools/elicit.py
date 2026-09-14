from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from exact.models import Source


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _snippet(text: str, limit: int = 1200) -> str:
    return (text or "").strip()[:limit]


def _rows_from_dict(data: dict) -> list:
    for key in ("papers", "results", "data", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("papers") or value.get("items")
            if isinstance(nested, list):
                return nested
    return []


def _paper_list(data: object, num: int) -> list:
    if isinstance(data, list):
        papers = data
    elif isinstance(data, dict):
        papers = _rows_from_dict(data)
    else:
        papers = []
    return [item for item in papers[:num] if isinstance(item, dict)]


def _paper_source(i: int, item: dict, retrieved_at: str) -> Source:
    doi = item.get("doi")
    url = (
        item.get("url")
        or item.get("pdfUrl")
        or (f"https://doi.org/{doi}" if doi else None)
    )
    return Source(
        id=f"tmp_{i}",
        title=item.get("title") or "untitled",
        url=url,
        doi=doi,
        snippet=_snippet(item.get("abstract") or item.get("summary") or ""),
        provider="elicit",
        retrieved_at=retrieved_at,
    )


def _retry_status(status: int) -> bool:
    return status == 429 or status >= 500


def _send_with_retry(fetch):
    try:
        resp = fetch()
    except Exception as exc:
        if not isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            raise
        return fetch()
    if _retry_status(getattr(resp, "status_code", 200)):
        return fetch()
    return resp


class ElicitClient:
    def __init__(
        self,
        api_key: str,
        timeout: float = 20.0,
        *,
        post=None,
        clock=None,
        client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self._post = post
        self._client = client
        self._clock = clock or _now

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _post_once(self, query: str, num: int):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "maxResults": num}
        if self._post is not None:
            return self._post(
                "https://elicit.com/api/v2/search/papers",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        return self._http().post(
            "https://elicit.com/api/v2/search/papers",
            headers=headers,
            json=payload,
        )

    def search(self, query: str, num: int = 5) -> list[Source]:
        if not self.enabled:
            return []
        resp = _send_with_retry(lambda: self._post_once(query, num))
        resp.raise_for_status()
        retrieved_at = self._clock()
        return [
            _paper_source(i, item, retrieved_at)
            for i, item in enumerate(_paper_list(resp.json(), num))
        ]


def dump_sources(sources: list[Source]) -> list[dict[str, Any]]:
    return [s.model_dump() for s in sources]
