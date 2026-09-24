"""Tests for the pending-feedback fetch of `/babysit-pr`."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "pr-feedback.py"
)


def _load_script() -> ModuleType:
    """Load the hyphenated feedback script."""
    spec = importlib.util.spec_from_file_location("pr_feedback", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


feedback = _load_script()

OWN = "exact-bot"
REF = feedback.PrRef(repo="acme/app", number=7, own_login=OWN)
MARKER = "Addressed: https://github.com/acme/app/pull/7#pullrequestreview-"


def _comment(database_id: int, login: str | None) -> dict[str, Any]:
    return {
        "databaseId": database_id,
        "body": f"comment {database_id}",
        "author": {"login": login} if login else None,
        "diffHunk": "@@ -1 +1 @@",
        "originalCommit": {"oid": "a" * 40},
        "commit": {"oid": "b" * 40},
    }


def _thread(
    thread_id: str, comments: list[dict[str, Any]], *, is_resolved: bool = False
) -> dict[str, Any]:
    return {
        "id": thread_id,
        "isResolved": is_resolved,
        "isOutdated": False,
        "line": 3,
        "originalLine": 3,
        "path": "src/exact/cli.py",
        "diffSide": "RIGHT",
        "firstComment": {"nodes": [{"databaseId": comments[0]["databaseId"]}]},
        "comments": {"nodes": comments},
    }


def _general(comment_id: int, login: str, body: str) -> dict[str, Any]:
    return {"id": comment_id, "user": login, "body": body}


def _review(
    review_id: int, login: str, body: str, state: str = "COMMENTED"
) -> dict[str, Any]:
    return {
        "id": review_id,
        "user": login,
        "state": state,
        "body": body,
        "commit_sha": "c" * 40,
    }


def _pending(
    threads: list[dict[str, Any]] | None = None,
    comments: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = feedback.Feedback(
        threads=threads or [],
        general_comments=comments or [],
        review_bodies=reviews or [],
    )
    return feedback.select_pending(raw, REF)


def test_resolved_thread_is_not_pending() -> None:
    out = _pending(threads=[_thread("T1", [_comment(1, "alice")], is_resolved=True)])
    assert out["threads"] == []


def test_thread_whose_latest_comment_is_own_waits_for_the_reviewer() -> None:
    thread = _thread("T1", [_comment(1, "alice"), _comment(2, OWN)])
    assert _pending(threads=[thread])["threads"] == []


def test_thread_opened_by_own_account_is_not_pending() -> None:
    assert _pending(threads=[_thread("T1", [_comment(1, OWN)])])["threads"] == []


def test_new_reviewer_comment_after_own_reply_makes_thread_pending() -> None:
    thread = _thread(
        "T1", [_comment(1, "alice"), _comment(2, OWN), _comment(3, "alice")]
    )
    assert [t["key"] for t in _pending(threads=[thread])["threads"]] == ["T1@3"]


def test_reply_target_is_the_first_comment_of_the_thread() -> None:
    thread = _thread("T1", [_comment(10, "alice"), _comment(11, "bob")])
    assert _pending(threads=[thread])["threads"][0]["replyToDatabaseId"] == 10


def test_own_general_comments_are_not_pending() -> None:
    comments = [_general(1, OWN, "Fixed: renamed x."), _general(2, "alice", "Why?")]
    assert [c["id"] for c in _pending(comments=comments)["generalComments"]] == [2]


def test_marker_suppresses_the_review_with_that_exact_id() -> None:
    out = _pending(
        comments=[_general(1, OWN, f"{MARKER}123")],
        reviews=[_review(123, "alice", "Please fix."), _review(124, "alice", "More.")],
    )
    assert [r["id"] for r in out["reviewBodies"]] == [124]


def test_marker_for_a_longer_id_does_not_suppress_a_prefix_id() -> None:
    out = _pending(
        comments=[_general(1, OWN, f"{MARKER}1234")],
        reviews=[_review(123, "alice", "Please fix.")],
    )
    assert [r["id"] for r in out["reviewBodies"]] == [123]


@pytest.mark.parametrize(
    ("author", "body"),
    [
        (OWN, f"{MARKER}123 and more text"),
        (OWN, f"{MARKER}"),
        ("alice", f"{MARKER}123"),
    ],
    ids=["extra-text", "no-id", "other-author"],
)
def test_comment_that_is_not_an_exact_own_marker_suppresses_nothing(
    author: str, body: str
) -> None:
    out = _pending(
        comments=[_general(1, author, body)],
        reviews=[_review(123, "alice", "Please fix.")],
    )
    assert [r["id"] for r in out["reviewBodies"]] == [123]


@pytest.mark.parametrize(
    ("body", "state"),
    [("", "COMMENTED"), ("Draft note.", "PENDING")],
    ids=["empty-body", "unsubmitted"],
)
def test_review_body_that_carries_no_submitted_feedback_is_not_pending(
    body: str, state: str
) -> None:
    reviews = [_review(1, "alice", body, state=state)]
    assert _pending(reviews=reviews)["reviewBodies"] == []


def test_submitted_review_body_is_pending() -> None:
    reviews = [_review(3, "alice", "Real feedback.", state="CHANGES_REQUESTED")]
    assert [r["id"] for r in _pending(reviews=reviews)["reviewBodies"]] == [3]


def test_own_counter_line_review_is_not_pending() -> None:
    counter = "Found 4 issues at or above high severity — see inline comments."
    reviews = [_review(1, OWN, counter), _review(2, OWN, "## Approach notes\nUse X.")]
    assert [r["id"] for r in _pending(reviews=reviews)["reviewBodies"]] == [2]


def test_counter_line_by_another_account_is_pending() -> None:
    counter = "Found 4 issues at or above high severity — see inline comments."
    reviews = [_review(1, "alice", counter)]
    assert [r["id"] for r in _pending(reviews=reviews)["reviewBodies"]] == [1]


@pytest.mark.parametrize(
    "review_id", ["١٢٣", "123\n"], ids=["non-ascii-digits", "trailing-newline"]
)
def test_marker_with_a_malformed_id_suppresses_nothing(review_id: str) -> None:
    out = _pending(
        comments=[_general(1, OWN, f"{MARKER}{review_id}")],
        reviews=[_review(123, "alice", "Please fix.")],
    )
    assert [r["id"] for r in out["reviewBodies"]] == [123]


def test_thread_whose_latest_comment_has_a_deleted_author_is_pending() -> None:
    thread = _thread("T1", [_comment(1, OWN), _comment(2, None)])
    assert [t["key"] for t in _pending(threads=[thread])["threads"]] == ["T1@2"]


def test_thread_line_is_read_against_the_latest_comment_commit() -> None:
    thread = _thread("T1", [_comment(1, "alice")])
    assert _pending(threads=[thread])["threads"][0]["commit_sha"] == "b" * 40


class FakeGh:
    """In-memory `gh`: answers each call with a fixed JSON payload.

    It refuses a list fetch without `--paginate` and `--slurp`, and a thread
    query that cannot page, because those flags are the pagination contract.
    """

    def __init__(self, responses: dict[str, Any], *, fails: bool = False) -> None:
        self._responses = responses
        self._fails = fails

    def __call__(self, args: list[str]) -> str:
        if self._fails:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502\n")
        if args[:2] == ["repo", "view"]:
            return "acme/app\n"
        if args[:2] == ["api", "user"]:
            return f"{OWN}\n"
        assert "--paginate" in args and "--slurp" in args, args
        if "graphql" in args:
            query = next(a for a in args if a.startswith("query="))
            assert "after:$endCursor" in query and "pageInfo" in query
            return json.dumps(self._responses["graphql"])
        return json.dumps(self._responses[args[-1]])


def _thread_page(threads: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads}}}}
    }


def _rest_comment(comment_id: int, login: str | None) -> dict[str, Any]:
    user = {"login": login} if login else None
    return {"id": comment_id, "user": user, "body": f"body {comment_id}"}


def _rest_review(review_id: int, login: str) -> dict[str, Any]:
    return {
        "id": review_id,
        "user": {"login": login},
        "state": "COMMENTED",
        "body": f"review {review_id}",
        "commit_id": "c" * 40,
    }


def _gh(
    thread_pages: Any = None,
    comment_pages: Any = None,
    review_pages: Any = None,
    *,
    fails: bool = False,
) -> FakeGh:
    responses = {
        "graphql": [_thread_page([])] if thread_pages is None else thread_pages,
        "repos/acme/app/issues/7/comments": [[]]
        if comment_pages is None
        else comment_pages,
        "repos/acme/app/pulls/7/reviews": [[]]
        if review_pages is None
        else review_pages,
    }
    return FakeGh(responses, fails=fails)


def test_every_page_of_each_source_is_read() -> None:
    gh = _gh(
        thread_pages=[
            _thread_page([_thread("T1", [_comment(1, "alice")])]),
            _thread_page([_thread("T2", [_comment(2, "bob")])]),
        ],
        comment_pages=[[_rest_comment(1, "alice")], [_rest_comment(2, "bob")]],
        review_pages=[[_rest_review(1, "alice")], [_rest_review(2, "bob")]],
    )
    raw = feedback.fetch_feedback(REF, gh)
    assert [t["id"] for t in raw.threads] == ["T1", "T2"]
    assert [c["id"] for c in raw.general_comments] == [1, 2]
    assert [r["id"] for r in raw.review_bodies] == [1, 2]


def test_error_object_from_gh_fails_the_fetch() -> None:
    gh = _gh(comment_pages={"message": "Not Found", "status": "404"})
    with pytest.raises(feedback.FeedbackError):
        feedback.fetch_feedback(REF, gh)


def test_error_object_inside_a_page_fails_the_fetch() -> None:
    gh = _gh(review_pages=[{"message": "API rate limit exceeded"}])
    with pytest.raises(feedback.FeedbackError):
        feedback.fetch_feedback(REF, gh)


def test_graphql_page_without_threads_fails_the_fetch() -> None:
    gh = _gh(thread_pages=[{"errors": [{"message": "Could not resolve"}]}])
    with pytest.raises(feedback.FeedbackError):
        feedback.fetch_feedback(REF, gh)


def test_comment_from_a_deleted_account_is_kept() -> None:
    raw = feedback.fetch_feedback(REF, _gh(comment_pages=[[_rest_comment(5, None)]]))
    pending = feedback.select_pending(raw, REF)
    assert [(c["id"], c["user"]) for c in pending["generalComments"]] == [(5, None)]


@pytest.fixture
def github_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACT_GITHUB_USER", "Exact-Bot")


@pytest.mark.parametrize(
    "argv",
    [[], ["--pr"], ["--pr", "abc"], ["--pr", "²"], ["--issue", "7"]],
    ids=str,
)
@pytest.mark.usefixtures("github_user")
def test_malformed_arguments_print_usage_and_exit_1(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert feedback.main(argv, lambda _login: _gh()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err


def test_missing_github_user_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("EXACT_GITHUB_USER", raising=False)
    assert feedback.main(["--pr", "7"], lambda _login: _gh()) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.usefixtures("github_user")
def test_gh_failure_exits_1_and_prints_no_feedback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert feedback.main(["--pr", "7"], lambda _login: _gh(fails=True)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HTTP 502" in captured.err


@pytest.mark.usefixtures("github_user")
def test_bad_payload_exits_1_and_prints_no_feedback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gh = _gh(comment_pages={"message": "Not Found"})
    assert feedback.main(["--pr", "7"], lambda _login: gh) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bad payload" in captured.err


@pytest.mark.usefixtures("github_user")
def test_own_comments_are_matched_by_the_login_the_api_returns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gh = _gh(comment_pages=[[_rest_comment(1, OWN), _rest_comment(2, "alice")]])
    assert feedback.main(["--pr", "7"], lambda _login: gh) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["repo"], printed["pr"]) == ("acme/app", 7)
    assert [c["id"] for c in printed["generalComments"]] == [2]
