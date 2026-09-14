from __future__ import annotations

from exact.tools.elicit import ElicitClient


class FakeHTTPResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


class FakeElicitPost:
    def __init__(self, responses: list):
        self.calls: list[dict] = []
        self._responses = list(responses)

    def __call__(self, url, *, headers, json, timeout):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_PAPER = {
    "title": "Paper A",
    "doi": "10.1/abc",
    "abstract": "Alpha cells die.",
    "url": "https://doi.org/10.1/abc",
}


def _client(post, api_key="k") -> ElicitClient:
    return ElicitClient(api_key, post=post, clock=lambda: "2026-01-01T00:00:00Z")


def test_elicit_search_is_empty_without_key():
    post = FakeElicitPost([])
    got = _client(post, api_key="").search("What is X?", num=5)
    assert got == []
    assert post.calls == []


def test_elicit_search_sends_max_results_five():
    post = FakeElicitPost([FakeHTTPResponse(200, {"papers": [_PAPER]})])
    _client(post).search("What is X?", num=5)
    assert post.calls[0]["json"] == {"query": "What is X?", "maxResults": 5}


def test_elicit_search_maps_doi_and_abstract():
    post = FakeElicitPost([FakeHTTPResponse(200, {"papers": [_PAPER]})])
    got = _client(post).search("What is X?", num=5)
    assert got[0].provider == "elicit"
    assert got[0].doi == "10.1/abc"
    assert got[0].snippet == "Alpha cells die."
    assert got[0].title == "Paper A"
    assert got[0].retrieved_at == "2026-01-01T00:00:00Z"


def test_elicit_retries_once_on_429():
    post = FakeElicitPost(
        [
            FakeHTTPResponse(429),
            FakeHTTPResponse(200, {"papers": [_PAPER]}),
        ]
    )
    got = _client(post).search("What is X?", num=5)
    assert len(post.calls) == 2
    assert len(got) == 1
    assert got[0].title == "Paper A"


def test_elicit_reuses_injected_httpx_client():
    class CountingClient:
        def __init__(self):
            self.calls = 0

        def post(self, url, *, headers, json):
            self.calls += 1
            return FakeHTTPResponse(200, {"papers": [_PAPER]})

    http = CountingClient()
    client = ElicitClient("k", client=http, clock=lambda: "2026-01-01T00:00:00Z")
    client.search("What is X?", num=5)
    client.search("What is Y?", num=5)
    assert http.calls == 2
