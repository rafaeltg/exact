#!/usr/bin/env python3
"""`.claude/hooks/pr-feedback.py` — the pending review feedback of one PR.

`/babysit-pr` acts on three feedback sources: unresolved review threads, general
PR comments, and review bodies. Fetching them has exact rules that a model can
get wrong without an error, so this program owns them:

* Every list is paginated. `gh api --paginate --slurp` returns one array per
  page; the pages are flattened here. The thread query declares `$endCursor`
  and selects `pageInfo`, which `gh api graphql --paginate` needs to page.
* A thread carries its 20 newest comments, so its key always sees the latest
  one, and its first comment, which is the only valid reply target.
* An HTTP error makes `gh` print an error object, not a list. That fails the
  run here instead of reading as "no feedback".
* An `Addressed: …#pullrequestreview-<id>` marker suppresses a review by exact
  id. A substring test would let a marker for review 1234 hide review 123.

Every `gh` call runs with `GH_TOKEN` set to the token of `EXACT_GITHUB_USER`, so
the global `gh` account never changes. The own login is read back from the API
with that token, so a case difference in the variable cannot make the loop
answer its own comments.

Needs Python 3.12 or later: `make pr-feedback` runs it through `uv run`.

Usage: ``pr-feedback.py --pr <number>``. Prints the pending feedback as JSON.
Exit codes: 0 success, 1 on a usage, `gh`, or payload error.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

type GhRunner = Callable[[list[str]], str]
type Json = dict[str, Any]

THREADS_QUERY = """
query($owner:String!, $name:String!, $number:Int!, $endCursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100, after:$endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          line
          originalLine
          path
          diffSide
          firstComment: comments(first:1) { nodes { databaseId } }
          comments(last:20) {
            nodes {
              databaseId
              body
              author { login }
              diffHunk
              originalCommit { oid }
              commit { oid }
            }
          }
        }
      }
    }
  }
}
"""

COUNTER_LINE = re.compile(
    r"Found \d+ issues at or above high severity — see inline comments\."
)


class FeedbackError(Exception):
    """A `gh` payload that is not the shape the feedback contract needs."""


@dataclass(frozen=True)
class PrRef:
    """One pull request, and the account that acts on it."""

    repo: str
    number: int
    own_login: str

    def marker_prefix(self) -> str:
        """The fixed start of every marker this account posts on this PR."""
        return (
            f"Addressed: https://github.com/{self.repo}/pull/{self.number}"
            "#pullrequestreview-"
        )


@dataclass(frozen=True)
class Feedback:
    """The three raw feedback lists of one PR, pages already flattened."""

    threads: list[Json]
    general_comments: list[Json]
    review_bodies: list[Json]


def marker_review_id(comment: Json, ref: PrRef) -> str | None:
    """The review id an own marker comment addresses, or None.

    Only a body that is exactly the prefix plus digits is a marker. A comment
    that merely starts with `Addressed:` stays reviewer feedback.
    """
    if comment["user"] != ref.own_login:
        return None
    body = comment["body"]
    review_id = body.removeprefix(ref.marker_prefix())
    if review_id == body or not review_id.isdigit():
        return None
    return review_id


def pending_threads(threads: list[Json], own_login: str) -> list[Json]:
    """Unresolved threads that wait for this account, each with its ledger key.

    A thread whose latest comment is this account's waits for the reviewer.
    """
    pending = []
    for thread in threads:
        comments = thread["comments"]["nodes"]
        if thread["isResolved"] or not comments:
            continue
        latest = comments[-1]
        if (latest["author"] or {}).get("login") == own_login:
            continue
        pending.append(_pending_thread(thread, latest))
    return pending


def _pending_thread(thread: Json, latest: Json) -> Json:
    """The thread fields `/babysit-pr` reads.

    `line` is a position in the latest comment's `commit`, so that commit is the
    one to read the context window from.
    """
    first = thread["firstComment"]["nodes"]
    return {
        "key": f"{thread['id']}@{latest['databaseId']}",
        "id": thread["id"],
        "path": thread["path"],
        "line": thread["line"],
        "originalLine": thread["originalLine"],
        "diffSide": thread["diffSide"],
        "isOutdated": thread["isOutdated"],
        "commit_sha": (latest["commit"] or {}).get("oid"),
        "replyToDatabaseId": first[0]["databaseId"] if first else None,
        "comments": thread["comments"]["nodes"],
    }


def pending_general_comments(comments: list[Json], own_login: str) -> list[Json]:
    """General comments by anyone but this account.

    This account's comments are its own markers, notes and replies.
    """
    return [comment for comment in comments if comment["user"] != own_login]


def pending_review_bodies(
    reviews: list[Json], comments: list[Json], ref: PrRef
) -> list[Json]:
    """Submitted, non-empty review bodies that no marker has addressed.

    This account's own "Found N issues" counter line is not feedback.
    """
    addressed = {
        review_id
        for comment in comments
        if (review_id := marker_review_id(comment, ref)) is not None
    }
    return [
        review
        for review in reviews
        if review["body"]
        and review["state"] != "PENDING"
        and str(review["id"]) not in addressed
        and not _is_own_counter_line(review, ref.own_login)
    ]


def _is_own_counter_line(review: Json, own_login: str) -> bool:
    return review["user"] == own_login and bool(
        COUNTER_LINE.fullmatch(review["body"].strip())
    )


def select_pending(feedback: Feedback, ref: PrRef) -> Json:
    """The pending feedback of one PR, in the shape `/babysit-pr` reads."""
    return {
        "repo": ref.repo,
        "pr": ref.number,
        "threads": pending_threads(feedback.threads, ref.own_login),
        "generalComments": pending_general_comments(
            feedback.general_comments, ref.own_login
        ),
        "reviewBodies": pending_review_bodies(
            feedback.review_bodies, feedback.general_comments, ref
        ),
    }


def fetch_feedback(ref: PrRef, gh: GhRunner) -> Feedback:
    """Fetch every page of the three feedback sources of one PR."""
    owner, name = ref.repo.split("/", 1)
    thread_pages = _pages(
        gh(
            [
                "api", "graphql", "--paginate", "--slurp",
                "-f", f"query={THREADS_QUERY}",
                "-f", f"owner={owner}", "-f", f"name={name}",
                "-F", f"number={ref.number}",
            ]
        )
    )  # fmt: skip
    base = f"repos/{ref.repo}"
    return Feedback(
        threads=[node for page in thread_pages for node in _thread_nodes(page)],
        general_comments=[
            _general_comment(item)
            for item in _rest_list(gh, f"{base}/issues/{ref.number}/comments")
        ],
        review_bodies=[
            _review_body(item)
            for item in _rest_list(gh, f"{base}/pulls/{ref.number}/reviews")
        ],
    )


def _pages(output: str) -> list[Any]:
    payload = json.loads(output)
    if not isinstance(payload, list):
        raise FeedbackError(f"gh returned {type(payload).__name__}, not pages")
    return payload


def _thread_nodes(page: Json) -> list[Json]:
    try:
        return page["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    except (KeyError, TypeError) as exc:
        raise FeedbackError(f"thread page has no reviewThreads: {page}") from exc


def _rest_list(gh: GhRunner, endpoint: str) -> list[Json]:
    items = []
    for page in _pages(gh(["api", "--paginate", "--slurp", endpoint])):
        if not isinstance(page, list):
            raise FeedbackError(f"{endpoint}: page is not a list: {page}")
        items.extend(page)
    return items


def _login(item: Json) -> str | None:
    """The author login; GitHub sends a null user for a deleted account."""
    return (item["user"] or {}).get("login")


def _general_comment(item: Json) -> Json:
    return {"id": item["id"], "user": _login(item), "body": item["body"] or ""}


def _review_body(item: Json) -> Json:
    return {
        "id": item["id"],
        "user": _login(item),
        "state": item["state"],
        "body": item["body"] or "",
        "commit_sha": item["commit_id"],
    }


def token_runner(login: str) -> GhRunner:
    """A `gh` runner that acts as `login` without switching the global account."""
    token = _run(["gh", "auth", "token", "--user", login], os.environ.copy()).strip()
    if not token:
        raise FeedbackError(f"gh has no token for {login}")
    env = {**os.environ, "GH_TOKEN": token}
    return lambda args: _run(["gh", *args], env)


def _run(command: list[str], env: dict[str, str]) -> str:
    return subprocess.run(
        command, capture_output=True, text=True, check=True, env=env
    ).stdout


def resolve_ref(number: int, gh: GhRunner) -> PrRef:
    """The PR in the current repository, with the login the token acts as."""
    repo = gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    login = gh(["api", "user", "--jq", ".login"])
    return PrRef(repo=repo.strip(), number=number, own_login=login.strip())


def main(
    argv: list[str], runner_factory: Callable[[str], GhRunner] = token_runner
) -> int:
    """Print the pending feedback of one PR. See the module docstring."""
    login = os.environ.get("EXACT_GITHUB_USER", "")
    valid = len(argv) == 2 and argv[0] == "--pr" and re.fullmatch(r"[0-9]+", argv[1])
    if not valid or not login:
        print(
            "usage: EXACT_GITHUB_USER=<login> pr-feedback.py --pr <number>",
            file=sys.stderr,
        )
        return 1
    try:
        gh = runner_factory(login)
        ref = resolve_ref(int(argv[1]), gh)
        pending = select_pending(fetch_feedback(ref, gh), ref)
    except subprocess.CalledProcessError as exc:
        print(f"pr-feedback: gh failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 1
    except (FeedbackError, ValueError, TypeError, KeyError) as exc:
        print(f"pr-feedback: bad payload: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(pending, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
