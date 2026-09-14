from __future__ import annotations

import time

import pytest

from exact.tools.exa import ExaClient


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
    def __init__(self, results=None, error=None):
        self.search_kwargs: list[dict] = []
        self.contents_urls: list = []
        self._results = results or []
        self._error = error

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
