from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from exact.tools.exa import ExaClient

FIXTURE = Path(__file__).parent / "fixtures" / "exa_publication_search.json"


def _fixture_payload() -> dict:
    """The captured Exa ``/search`` wire body for ``category="publication"``."""
    return json.loads(FIXTURE.read_text())


class _Item:
    def __init__(self, title, url, highlights=None, text="", entities=None):
        self.title = title
        self.url = url
        self.highlights = highlights
        self.text = text
        self.entities = entities


class _Result:
    def __init__(self, results):
        self.results = results


class FakeExaSdk:
    def __init__(self, results=None, error=None, payload=None):
        self.search_kwargs: list[dict] = []
        self.contents_urls: list = []
        self.requests: list[tuple[str, dict]] = []
        self._results = results or []
        self._error = error
        self._payload = payload

    def request(self, endpoint: str, data: dict) -> dict:
        """Mirror ``exa_py.Exa.request``; ``data`` is its parameter name."""
        self.requests.append((endpoint, data))
        if self._error:
            raise self._error
        return self._payload if self._payload is not None else _fixture_payload()

    def search_and_contents(self, query, **kwargs):
        self.search_kwargs.append(kwargs)
        if self._error:
            raise self._error
        return _Result(self._results)

    def get_contents(self, urls, **kwargs):
        self.contents_urls.append(urls)
        if self._error:
            raise self._error
        return _Result(self._results)


def _client(
    sdk, clock=lambda: "2026-01-01T00:00:00Z", timeout: float = 20.0
) -> ExaClient:
    return ExaClient("k", timeout, sdk=sdk, clock=clock)


class _SlowSdk:
    """Each call takes longer than the client soft timeout, then returns."""

    def __init__(self, delay: float = 0.15, results=None, error=None):
        self.calls = 0
        self._delay = delay
        self._results = results or []
        self._error = error

    def search_and_contents(self, query, **kwargs):
        self.calls += 1
        time.sleep(self._delay)
        if self._error:
            raise self._error
        return _Result(self._results)

    def get_contents(self, urls, **kwargs):
        self.calls += 1
        time.sleep(self._delay)
        if self._error:
            raise self._error
        return _Result(self._results)


class _TimeoutThenOk:
    def __init__(self, delay: float = 0.15, results=None):
        self.calls = 0
        self._delay = delay
        self._results = results or []

    def search_and_contents(self, query, **kwargs):
        self.calls += 1
        if self.calls == 1:
            time.sleep(self._delay)
            return _Result([])
        return _Result(self._results)


def _entity_props(result: dict) -> dict:
    for ent in result.get("entities") or []:
        if ent.get("type") == "publication":
            return ent.get("properties") or {}
    return {}


def test_publication_fixture_holds_abstract_and_doi():
    payload = _fixture_payload()
    results = payload.get("results") or []
    assert results
    assert any(_entity_props(r).get("abstract") for r in results)
    assert any(
        _entity_props(r).get("doi") or "doi.org" in (r.get("url") or "")
        for r in results
    )


def test_exa_search_passes_five_hits():
    sdk = FakeExaSdk()
    _client(sdk).search("What is X?", num=5)
    assert sdk.search_kwargs[0]["num_results"] == 5
    assert "category" not in sdk.search_kwargs[0]


def test_exa_people_search_passes_category():
    sdk = FakeExaSdk()
    _client(sdk).search("senior ML engineers", num=5, category="people")
    assert sdk.search_kwargs[0]["category"] == "people"
    assert sdk.search_kwargs[0]["num_results"] == 5


def test_exa_company_search_passes_category():
    sdk = FakeExaSdk()
    _client(sdk).search("fintech companies", num=5, category="company")
    assert sdk.search_kwargs[0]["category"] == "company"


def test_exa_search_maps_title_url_snippet():
    sdk = FakeExaSdk(
        results=[
            _Item(
                title="Source A",
                url="https://example.com/a",
                highlights=["X is Y according to this page."],
            )
        ]
    )
    got = _client(sdk).search("What is X?", num=5)
    assert got[0].title == "Source A"
    assert got[0].url == "https://example.com/a"
    assert got[0].snippet == "X is Y according to this page."
    assert got[0].provider == "exa"
    assert got[0].retrieved_at == "2026-01-01T00:00:00Z"


def test_exa_people_entity_folds_into_snippet():
    sdk = FakeExaSdk(
        results=[
            _Item(
                title="Jane Doe - VP Engineering",
                url="https://www.linkedin.com/in/janedoe",
                highlights=["Built the search platform."],
                entities=[
                    {
                        "id": "person_1",
                        "type": "person",
                        "properties": {
                            "name": "Jane Doe",
                            "location": "San Francisco",
                            "workHistory": [
                                {
                                    "title": "VP Engineering",
                                    "company": {"name": "Example AI"},
                                }
                            ],
                        },
                    }
                ],
            )
        ]
    )
    got = _client(sdk).search("VP Engineering", num=5, category="people")
    assert "Jane Doe" in got[0].snippet
    assert "VP Engineering at Example AI" in got[0].snippet
    assert "Built the search platform." in got[0].snippet


def test_exa_company_entity_folds_into_snippet():
    sdk = FakeExaSdk(
        results=[
            _Item(
                title="Example AI",
                url="https://www.example.ai",
                highlights=["Enterprise search."],
                entities=[
                    {
                        "id": "company_1",
                        "type": "company",
                        "properties": {
                            "name": "Example AI",
                            "foundedYear": 2021,
                            "headquarters": {
                                "city": "San Francisco",
                                "country": "United States",
                            },
                            "financials": {
                                "fundingTotal": 42000000,
                                "fundingLatestRound": {"name": "Series B"},
                            },
                        },
                    }
                ],
            )
        ]
    )
    got = _client(sdk).search("Example AI", num=5, category="company")
    assert "Example AI" in got[0].snippet
    assert "founded 2021" in got[0].snippet
    assert "San Francisco, United States" in got[0].snippet
    assert "funding $42000000" in got[0].snippet
    assert "Series B" in got[0].snippet


def test_exa_snippet_caps_at_1200():
    sdk = FakeExaSdk(
        results=[
            _Item(
                title="Source A",
                url="https://example.com/a",
                highlights=["x" * 1201],
            )
        ]
    )
    got = _client(sdk).search("What is X?", num=5)
    assert len(got[0].snippet) == 1200


def test_exa_entity_snippet_caps_at_1200():
    sdk = FakeExaSdk(
        results=[
            _Item(
                title="Jane Doe",
                url="https://example.com/a",
                highlights=["x" * 1200],
                entities=[
                    {
                        "type": "person",
                        "properties": {"name": "Jane Doe"},
                    }
                ],
            )
        ]
    )
    got = _client(sdk).search("Jane", num=5, category="people")
    assert len(got[0].snippet) == 1200
    assert got[0].snippet.startswith("Jane Doe")


def test_exa_highlights_reads_the_given_url():
    sdk = FakeExaSdk(
        results=[_Item(title="Source A", url="https://example.com/a", highlights=["X"])]
    )
    _client(sdk).highlights("https://example.com/a")
    assert sdk.contents_urls == [["https://example.com/a"]]


def test_exa_http_timeout_default_is_20():
    assert ExaClient("k", sdk=FakeExaSdk()).timeout == 20.0


def test_exa_search_retries_timeout_then_succeeds():
    sdk = _TimeoutThenOk(
        results=[
            _Item(
                title="Source A",
                url="https://example.com/a",
                highlights=["X is Y according to this page."],
            )
        ]
    )
    got = _client(sdk, timeout=0.05).search("What is X?", num=5)
    assert sdk.calls == 2
    assert got[0].title == "Source A"


@pytest.mark.parametrize(
    "method, args",
    [
        ("search", ("What is X?",)),
        ("highlights", ("https://example.com/a",)),
    ],
)
def test_exa_retries_once_on_timeout(method: str, args: tuple) -> None:
    sdk = _SlowSdk()
    client = _client(sdk, timeout=0.05)
    with pytest.raises(TimeoutError):
        getattr(client, method)(*args)
    assert sdk.calls == 2


class _NoRequestSdk:
    """An SDK build with no ``request`` attribute, as exa-py 1.x had."""

    def __init__(self, results=None):
        self.search_kwargs: list[dict] = []
        self._results = results or []

    def search_and_contents(self, query, **kwargs):
        self.search_kwargs.append(kwargs)
        return _Result(self._results)


def test_search_passes_publication_category_and_stamps_focus():
    sdk = FakeExaSdk()
    got = _client(sdk).search("GLP-1 trials", num=5, category="publication")
    assert sdk.requests[0][0] == "/search"
    assert sdk.requests[0][1]["category"] == "publication"
    assert {s.focus for s in got} == {"publication"}


def test_plain_search_stamps_web_focus():
    sdk = FakeExaSdk(results=[_Item(title="A", url="https://example.com/a")])
    assert _client(sdk).search("What is X?", num=5)[0].focus == "web"


def test_search_passes_any_category_through():
    sdk = FakeExaSdk(results=[_Item(title="A", url="https://example.com/a")])
    got = _client(sdk).search("news", num=5, category="news")
    assert sdk.search_kwargs[0]["category"] == "news"
    # An unrecognized category is not a lane, so its hits read as web.
    assert got[0].focus == "web"


def test_highlights_leave_focus_and_doi_unset():
    sdk = FakeExaSdk(
        results=[_Item(title="A", url="https://doi.org/10.1/x", highlights=["X"])]
    )
    got = _client(sdk).highlights("https://doi.org/10.1/x")
    assert got[0].focus is None
    assert got[0].doi is None


def test_publication_search_uses_raw_request_with_contents():
    sdk = FakeExaSdk()
    got = _client(sdk).search("GLP-1 trials", num=5, category="publication")
    body = sdk.requests[0][1]
    assert body["contents"] == {"highlights": True}
    assert body["numResults"] == 5
    assert not [k for k in body if "_" in k]
    assert got
    assert any(s.doi for s in got)
    assert any(len(s.snippet) > 200 for s in got)


@pytest.mark.parametrize(
    "result, expected",
    [
        (
            {
                "url": "https://example.com/a",
                "entities": [
                    {"type": "publication", "properties": {"doi": "10.1/entity"}}
                ],
            },
            "10.1/entity",
        ),
        ({"url": "https://dx.DOI.org/10.5/url"}, "10.5/url"),
        ({"url": "https://doi.org/10.7/q?utm=x#frag"}, "10.7/q"),
        ({"url": "https://example.com/paper"}, None),
        ({"url": "https://doi.org/not-a-doi"}, None),
    ],
)
def test_doi_mapping(result, expected):
    sdk = FakeExaSdk(payload={"results": [{"title": "A", **result}]})
    got = _client(sdk).search("q", num=5, category="publication")
    assert got[0].doi == expected


def test_publication_snippet_leads_with_metadata():
    sdk = FakeExaSdk(
        payload={
            "results": [
                {
                    "title": "A trial",
                    "url": "https://doi.org/10.1/x",
                    "highlights": ["ignored when an abstract exists"],
                    "entities": [
                        {
                            "type": "publication",
                            "properties": {
                                "authors": [{"name": "Jane Doe"}],
                                "year": 2025,
                                "citationCount": 12,
                                "abstract": "The abstract body.",
                            },
                        }
                    ],
                }
            ]
        }
    )
    got = _client(sdk).search("q", num=5, category="publication")
    assert got[0].snippet.startswith("Jane Doe (2025), 12 citations.")
    assert "The abstract body." in got[0].snippet
    assert "ignored" not in got[0].snippet


def test_publication_without_abstract_falls_back_to_highlights():
    sdk = FakeExaSdk(
        payload={
            "results": [
                {
                    "title": "A trial",
                    "url": "https://doi.org/10.1/x",
                    "highlights": ["The highlight body."],
                    "entities": [
                        {
                            "type": "publication",
                            "properties": {"authors": [{"name": "Jane Doe"}]},
                        }
                    ],
                }
            ]
        }
    )
    assert (
        "The highlight body."
        in _client(sdk).search("q", num=5, category="publication")[0].snippet
    )


def test_missing_request_sets_degraded():
    sdk = _NoRequestSdk(results=[_Item(title="A", url="https://example.com/a")])
    client = _client(sdk)
    got = client.search("q", num=5, category="publication")
    assert got
    assert got[0].focus == "publication"
    assert sdk.search_kwargs[0]["category"] == "publication"
    assert client.degraded is not None
    assert "DOI" in client.degraded


def test_raw_request_path_leaves_degraded_unset():
    client = _client(FakeExaSdk())
    client.search("q", num=5, category="publication")
    assert client.degraded is None


@pytest.mark.parametrize(
    "count, has_et_al",
    [(2, False), (3, False), (4, True)],
)
def test_publication_author_list_caps_at_three_names(count: int, has_et_al: bool):
    authors = [{"name": f"Author {i}"} for i in range(count)]
    sdk = FakeExaSdk(
        payload={
            "results": [
                {
                    "title": "A trial",
                    "url": "https://doi.org/10.1/x",
                    "entities": [
                        {
                            "type": "publication",
                            "properties": {"authors": authors, "year": 2025},
                        }
                    ],
                }
            ]
        }
    )
    snippet = _client(sdk).search("q", num=5, category="publication")[0].snippet
    assert ("et al." in snippet) is has_et_al
    assert "Author 0" in snippet


_FILTERS = {
    "exclude_domains": ["quora.com"],
    "start_published_date": "2026-09-14",
}


def test_filters_web_search_passes_snake_case_arguments():
    sdk = FakeExaSdk(results=[_Item(title="A", url="https://example.com/a")])
    _client(sdk).search("What is X?", num=5, filters=_FILTERS)
    kwargs = sdk.search_kwargs[0]
    assert kwargs["exclude_domains"] == ["quora.com"]
    assert kwargs["start_published_date"] == "2026-09-14"
    assert kwargs["num_results"] == 5


def test_filters_raw_publication_body_holds_camel_case_keys():
    sdk = FakeExaSdk()
    _client(sdk).search(
        "GLP-1 trials",
        num=5,
        category="publication",
        filters={"include_domains": ["nih.gov"], **_FILTERS},
    )
    body = sdk.requests[0][1]
    assert body["includeDomains"] == ["nih.gov"]
    assert body["excludeDomains"] == ["quora.com"]
    assert body["startPublishedDate"] == "2026-09-14"
    assert not [k for k in body if "_" in k]


def test_filters_degraded_publication_path_passes_snake_case_arguments():
    sdk = _NoRequestSdk()
    _client(sdk).search("GLP-1 trials", num=5, category="publication", filters=_FILTERS)
    kwargs = sdk.search_kwargs[0]
    assert kwargs["exclude_domains"] == ["quora.com"]
    assert kwargs["start_published_date"] == "2026-09-14"
    assert kwargs["category"] == "publication"


_FILTER_KEYS = {
    "include_domains",
    "exclude_domains",
    "start_published_date",
    "includeDomains",
    "excludeDomains",
    "startPublishedDate",
}


def test_filters_an_unfiltered_search_sends_no_filter_key():
    web = FakeExaSdk(results=[_Item(title="A", url="https://example.com/a")])
    _client(web).search("What is X?", num=5, filters={})
    raw = FakeExaSdk()
    _client(raw).search("GLP-1 trials", num=5, category="publication")
    degraded = _NoRequestSdk()
    _client(degraded).search("GLP-1 trials", num=5, category="publication")
    assert not _FILTER_KEYS & set(web.search_kwargs[0])
    assert not _FILTER_KEYS & set(raw.requests[0][1])
    assert not _FILTER_KEYS & set(degraded.search_kwargs[0])
