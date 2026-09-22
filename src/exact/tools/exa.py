from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from exa_py import Exa

from exact.models import Source, TopicFocus

_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org"})

# The raw ``/search`` body of each filter argument; ``request`` does no casing.
_CAMEL_FILTERS = {
    "include_domains": "includeDomains",
    "exclude_domains": "excludeDomains",
    "start_published_date": "startPublishedDate",
}
_MAX_NAMED_AUTHORS = 3


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


class _WireItem:
    """One ``/search`` result straight off the wire.

    ``sdk.request`` performs no key casing, so a raw result is a camelCase
    dict. This exposes the same attributes the SDK result object carries, so
    every reader below works on either shape.
    """

    def __init__(self, data: dict) -> None:
        self.title = data.get("title")
        self.url = data.get("url")
        self.highlights = data.get("highlights")
        self.text = data.get("text")
        self.entities = data.get("entities")


def _as_items(payload: Any) -> list[Any]:
    """Results of an SDK result object or of a raw ``sdk.request`` body."""
    if isinstance(payload, dict):
        return [
            _WireItem(r) for r in payload.get("results") or [] if isinstance(r, dict)
        ]
    return list(getattr(payload, "results", None) or [])


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


def _author_names(props: dict) -> str:
    """Author names from the wire shape, which is a list of objects."""
    names: list[str] = []
    for author in props.get("authors") or []:
        name = _as_dict(author).get("name") if not isinstance(author, str) else author
        if name:
            names.append(str(name))
    if len(names) > _MAX_NAMED_AUTHORS:
        return ", ".join(names[:_MAX_NAMED_AUTHORS]) + " et al."
    return ", ".join(names)


def _format_publication(props: dict) -> str:
    names = _author_names(props)
    year = props.get("year")
    head = (
        f"{names} ({year})" if names and year is not None else names or str(year or "")
    )
    parts = [head] if head else []
    citations = props.get("citationCount")
    if citations is not None:
        parts.append(f"{citations} citations")
    return ", ".join(parts)


_FOCUS_BY_CATEGORY: dict[str, TopicFocus] = {
    "web": "web",
    "people": "people",
    "company": "company",
    "publication": "publication",
}


def _as_focus(category: str | None) -> TopicFocus:
    """The lane a search category stamps on its hits.

    Any category reaches the SDK, but only a known lane is a valid focus, so
    an unrecognized one reads as web rather than failing the whole search.
    """
    return _FOCUS_BY_CATEGORY.get(category or "", "web")


def _doi_from_url(url: str | None) -> str | None:
    """The DOI a ``doi.org`` resolver URL carries, else None."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.hostname is None or parts.hostname.lower() not in _DOI_HOSTS:
        return None
    doi = parts.path.lstrip("/")
    return doi if doi.startswith("10.") else None


def _doi_from(item) -> str | None:
    props = _entity_props(item, "publication") or {}
    doi = props.get("doi")
    if doi:
        return str(doi)
    return _doi_from_url(getattr(item, "url", None))


def _entity_line(item) -> str:
    person = _entity_props(item, "person")
    if person:
        return _format_person(person)
    company = _entity_props(item, "company")
    if company:
        return _format_company(company)
    publication = _entity_props(item, "publication")
    if publication:
        return _format_publication(publication)
    return ""


def _item_text(item) -> str:
    abstract = (_entity_props(item, "publication") or {}).get("abstract")
    if abstract:
        return str(abstract)
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
    """Exa search/highlights client with soft timeout and one retry."""

    def __init__(
        self,
        api_key: str,
        timeout: float = 20.0,
        *,
        sdk: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.degraded: str | None = None
        self._client = sdk
        self._clock = clock or _now

    def _exa(self):
        if self._client is None:
            self._client = Exa(self.api_key)
        return self._client

    def _source(
        self, i: int, item, fallback_url: str, focus: TopicFocus | None
    ) -> Source:
        url = getattr(item, "url", None) or fallback_url or None
        return Source(
            id=f"tmp_{i}",
            title=getattr(item, "title", None) or url or "untitled",
            url=url,
            # A highlights read carries no lane, so its DOI stays unset too;
            # the caller backfills both from the source that owns the URL.
            doi=_doi_from(item) if focus else None,
            snippet=_item_snippet(item),
            provider="exa",
            focus=focus,
            retrieved_at=self._clock(),
        )

    def _map(
        self, items: list[Any], fallback_url: str, focus: TopicFocus | None
    ) -> list[Source]:
        return [self._source(i, it, fallback_url, focus) for i, it in enumerate(items)]

    def _search_contents(
        self,
        query: str,
        num: int,
        category: str | None,
        filters: Mapping[str, Any] | None,
    ):
        kwargs: dict[str, Any] = {"num_results": num, "highlights": True}
        if category is not None:
            kwargs["category"] = category
        kwargs.update(filters or {})
        return self._exa().search_and_contents(query, **kwargs)

    def _publication_items(
        self, query: str, num: int, filters: Mapping[str, Any] | None
    ) -> list[Any]:
        """Publication hits through the raw endpoint, so entities survive.

        exa-py 2.20.0 parses only person and company entities, so the typed
        `search_and_contents` path drops the publication entity that carries
        the abstract and the DOI. `request` returns the undecoded wire body.
        Retire this once exa-py parses publication entities.
        """
        sdk = self._exa()
        if not hasattr(sdk, "request"):
            items = _as_items(
                _invoke(
                    lambda: self._search_contents(query, num, "publication", filters),
                    self.timeout,
                )
            )
            # Only after the call returns: a raise is already one error line.
            self.degraded = (
                "exa publication search ran without abstracts; "
                "DOIs only from doi.org urls"
            )
            return items
        # `request` performs no key casing, so the body must be camelCase.
        body = {
            "query": query,
            "numResults": num,
            "category": "publication",
            "contents": {"highlights": True},
        }
        for key, value in (filters or {}).items():
            body[_CAMEL_FILTERS[key]] = value
        return _as_items(_invoke(lambda: sdk.request("/search", body), self.timeout))

    def search(
        self,
        query: str,
        num: int = 5,
        *,
        category: str | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> list[Source]:
        """Search Exa; ``category`` selects the lane, ``filters`` the domains and dates.

        ``filters`` holds the snake-case Exa filter arguments.
        """
        if category == "publication":
            items = self._publication_items(query, num, filters)
        else:
            items = _as_items(
                _invoke(
                    lambda: self._search_contents(query, num, category, filters),
                    self.timeout,
                )
            )
        return self._map(items, "", _as_focus(category))

    def highlights(self, url: str) -> list[Source]:
        """Fetch highlight snippets for a known URL."""
        result = _invoke(
            lambda: self._exa().get_contents([url], highlights=True), self.timeout
        )
        return self._map(_as_items(result), url, None)


def dump_sources(sources: list[Source]) -> list[dict[str, Any]]:
    """Serialize sources for graph state (checkpoint-friendly dicts)."""
    return [s.model_dump() for s in sources]
