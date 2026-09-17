---
description: Address GitHub PR review feedback by classifying comments, applying fixes, running tests, and resolving threads. One-shot pass over the current feedback; for continuous shepherding until green (CI + comments in a loop) use /babysit-pr, which delegates its comment cycles here
argument-hint: <pr-number>
allowed-tools: Bash(gh auth*), Bash(gh api*), Bash(rtk proxy gh api*), Bash(gh pr*), Bash(gh repo*), Bash(git branch*), Bash(git status*), Bash(git show*), Bash(git checkout*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(jq*), Bash(make test*), Bash(make check*), Task, Read, Glob, AskUserQuestion
disable-model-invocation: true
---

You are addressing review feedback on GitHub PR **$ARGUMENTS**.

Standards (commit format, test commands, CI gates) are defined in @CONTRIBUTING.md —
treat it as the single source of truth and do not invent rules not in that file.

Parse the PR number from `$ARGUMENTS` — strip the leading `#` if present. Record the bare number as `PR`.

## Instructions

### Step 1: Validate Environment & Fetch PR Context

Verify that the `EXACT_GITHUB_USER` environment variable is set. If empty or unset, inform the user and **STOP**.

Record the currently active `gh` account so it can be restored later (`gh auth switch` mutates **global** CLI state):

```bash
ORIGINAL_GH_USER=$(gh api user --jq .login 2>/dev/null)
```

Switch the `gh` CLI account:

```bash
gh auth switch -u $EXACT_GITHUB_USER
```

If the switch fails, inform the user and **STOP** (nothing was changed, so no restore is needed on this path).

**From this point on, every exit path — success, error, or any STOP below (the Step 1 guards, "no unresolved feedback", invalid classification JSON, empty `TOUCHED_FILES`) — MUST end by restoring the original account:**

```bash
[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"
```

Then run in parallel:

```bash
gh pr view $PR --json state,isDraft,headRefOid,headRefName --jq '{state,isDraft,headRefOid,headRefName}'
gh repo view --json nameWithOwner --jq '.nameWithOwner'
git branch --show-current
git status --short
```

Record:

- `PR_STATE`, `IS_DRAFT`, `HEAD_SHA`, `HEAD_BRANCH` from the PR view
- `REPO` — `owner/repo` string
- `LOCAL_BRANCH` — current local branch
- `WORKING_TREE_STATUS` — uncommitted changes

Derive `OWNER` and `REPO_NAME` by splitting `REPO` on `/`.

**Guards:**

- If `PR_STATE` is not `OPEN` or `IS_DRAFT` is `true`, inform the user and **STOP**.
- If `LOCAL_BRANCH` does not match `HEAD_BRANCH`, warn: "You are on branch `$LOCAL_BRANCH` but the PR is on `$HEAD_BRANCH`. Switch branches first." **STOP**.
- If `WORKING_TREE_STATUS` is non-empty, warn about uncommitted changes and ask whether to proceed or stop.

### Step 2: Fetch Review Threads, General Comments & Review Bodies

Run in parallel:

**Review threads (GraphQL):**

```bash
gh api graphql -f query='
  query($owner:String!, $name:String!, $number:Int!) {
    repository(owner:$owner, name:$name) {
      pullRequest(number:$number) {
        reviewThreads(first:100) {
          nodes {
            id
            isResolved
            isOutdated
            line
            originalLine
            path
            diffSide
            comments(first:20) {
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
' -F owner="$OWNER" -F name="$REPO_NAME" -F number=$PR
```

**General PR comments (REST)** — this is also the source the Step 9 idempotency
markers are read back from, so an incomplete fetch silently un-suppresses an
already-addressed review:

```bash
gh api --paginate --slurp repos/$REPO/issues/$PR/comments | jq '[.[][] | {id, body, user: .user.login}]'
```

**Review bodies (REST)** — the summary text a reviewer submits with a review (the `#pullrequestreview-<id>` anchor on GitHub):

```bash
gh api --paginate --slurp repos/$REPO/pulls/$PR/reviews | jq '[.[][] | select(.body != "" and .state != "PENDING") | {id, body, state, user: .user.login, commit_sha: .commit_id}]'
```

Both calls need the same three-part shape, and no part of it is optional:

- **`--paginate`** — without it you get the first page only (30 items). A marker
  or a review body past that page is invisible, so an addressed review
  resurfaces and is processed a second time.
- **`--slurp`** — `--paginate` alone emits one JSON array *per page*.
  Concatenated, that is several arrays back to back, not the single array these
  variables are defined as. `--slurp` wraps the pages into one outer array first.
- **`| jq`, never `--jq`** — `gh` **rejects** `--slurp` together with `--jq`
  (``the `--slurp` option is not supported with `--jq` or `--template` ``) and
  exits 1, so the filter must run in a separate `jq` process. `.[][]` then
  flattens outer page, then inner item, back into one array.

(`body != ""` drops the empty-body containers most inline-comment reviews are;
`state != "PENDING"` drops unsubmitted drafts.)

(`/review-pr` fetches the same two endpoints with a different combiner —
`--paginate --jq … | jq -s 'add // []'`. Both are correct; change one only after
checking the other.)

This third source is what makes PR-level review feedback visible at all: a
body-only review (the kind `/review-pr` posts its approach notes as)
creates **no** review thread and is **not** an issue comment, so it appears in
neither of the other two calls. Skipping it silently drops that feedback.

Record:

- `REVIEW_THREADS` — all review thread nodes from GraphQL
- `GENERAL_COMMENTS` — all general PR comments from REST
- `REVIEW_BODIES` — all non-empty, submitted review bodies from REST, each
  carrying the `commit_sha` the review was submitted against. Exclude reviews
  authored by `$EXACT_GITHUB_USER` whose body only re-states feedback already
  addressed (e.g. a plain "Found N issues — see inline comments." counter
  line); keep everything else, including bot reviews with substantive content.

Filter `REVIEW_THREADS` to only unresolved threads (`isResolved` = `false`). Record as `PENDING_THREADS`.

**Marker format (single definition — the Step 2 filters below and the Step 9 posting must use exactly this):** a general comment posted by this command whose body is exactly `Addressed: https://github.com/<REPO>/pull/<PR>#pullrequestreview-<id>`, with no other text. `REPO`, `PR`, and the review id fully determine the body, so for any review id you can build the expected string. Review bodies have no resolution state on GitHub; this marker is the only idempotency signal.

Filter `GENERAL_COMMENTS`: drop a comment only if its author is `$EXACT_GITHUB_USER` **and** its body is exactly `Addressed: https://github.com/<REPO>/pull/<PR>#pullrequestreview-` followed by one or more digits and nothing else — it matches the full template for some review id and carries no other text. Those are markers posted by previous runs of this command (Step 9), not reviewer feedback. Keep every other comment, including one that merely starts with `Addressed:` or cites a review anchor in prose. Record the dropped comments as `MARKER_COMMENTS` and the kept remainder back into `GENERAL_COMMENTS`.

Filter `REVIEW_BODIES`: from each comment in `MARKER_COMMENTS`, parse the id — the digits after its final `#pullrequestreview-` — and compare it to a review's id by **exact string equality**. Never test substring containment: `pullrequestreview-123` is a substring of a marker for review `1234`, so containment silently suppresses a review nobody addressed. Drop every review whose id equals a parsed marker id — a previous run fully addressed it. Record the remainder as `PENDING_REVIEW_BODIES`.

If `PENDING_THREADS`, `GENERAL_COMMENTS`, and `PENDING_REVIEW_BODIES` are all empty, inform the user: "No unresolved feedback to address." Restore the original `gh` account, then **STOP**.

### Step 3: Classify Comments

Spawn a single `general-purpose` subagent (**synchronous — pass `run_in_background: false`**; the pipeline consumes its result immediately and must not idle waiting on a background agent):

- **subagent_type:** `general-purpose`
- **prompt:**

  "You are classifying PR review feedback. For each comment below, assign exactly one category:

  - **BLOCKING** — The reviewer is requesting a code change that must be addressed before merge. Indicators: imperative language ('change this', 'fix this', 'remove this', 'add error handling'), reported bugs, logic corrections, security concerns.
  - **STYLE_NIT** — A non-blocking cosmetic suggestion. Indicators: 'nit:', 'minor:', rename suggestions, formatting preferences, comment wording tweaks. These are safe to apply without testing.
  - **DISCUSSION** — A question, architectural discussion, or comment that cannot be addressed by changing code. Indicators: 'why did you...', 'have you considered...', 'what about...', requests for explanation, praise/acknowledgment.

  If a thread has multiple comments (a conversation), classify based on the **latest unresolved ask**. If the thread is a back-and-forth that appears resolved in conversation even though the thread is still open, classify as DISCUSSION with a note.

  **Review threads (line-attached):**

  ```json
  $PENDING_THREADS
  ```

  **General PR comments:**

  ```json
  $GENERAL_COMMENTS
  ```

  **Review bodies** (PR-level review summaries — often multi-topic; split one
  review body into one entry per distinct actionable point, all sharing the
  review's id. A `state` of CHANGES_REQUESTED is a strong BLOCKING signal.
  Classify a pure overview/praise body as DISCUSSION and start its `summary`
  with 'NO_REPLY_NEEDED:' — Step 8 skips drafting for those):

  ```json
  $PENDING_REVIEW_BODIES
  ```

  Return a JSON array ordered by: BLOCKING first, then STYLE_NIT, then DISCUSSION.

  ```json
  [
    {
      \"id\": \"<thread node_id, general comment id, or review id>\",
      \"type\": \"thread|general|review\",
      \"category\": \"BLOCKING|STYLE_NIT|DISCUSSION\",
      \"file\": \"<path or null for general comments>\",
      \"line\": <line_number or null>,
      \"diff_hunk\": \"<diff hunk string or null>\",
      \"commit_sha\": \"<commit oid the comment references or null>\",
      \"summary\": \"<one-sentence summary of what is being asked>\",
      \"body\": \"<full original comment text>\",
      \"reviewer\": \"<author login>\",
      \"comment_database_id\": <databaseId of the first comment in the thread; null for general and review items>
    }
  ]
  ```

  For review-body entries, use the `commit_sha` already attached to the
  review object — do not set it to null. `file`/`line`/`diff_hunk` are null
  unless the body itself names them; extract any file references from the
  body text into `file` as a best-effort hint."

Record the result as `CLASSIFIED_COMMENTS`. Apply the JSON retry policy: if not valid JSON, extract between first `[` and last `]`, re-parse. If still invalid, present the raw classification to the user, restore the original `gh` account, and **STOP**.

### Step 4: Map Comment Locations to Local Files

For each comment in `CLASSIFIED_COMMENTS` that has a non-null `file` and `line`:

1. Get the file content at the comment's commit: `git show <commit_sha>:<path>`.
   Review-body entries carry the review's own `commit_sha` (Step 2) even when
   `file`/`line` were extracted from the body text — use `HEAD_SHA` only if
   `commit_sha` is genuinely absent.
2. Extract a context window: 3 lines above and 3 lines below the comment's `line` from that version.
3. Read the current local file using the Read tool.
4. Search for the context window in the current local file. Allow fuzzy matching — the target line must match, and at least 4 of the 6 surrounding context lines must match in order.
5. Record the `local_line` — the adjusted line number in the current file.

If the file does not exist locally, mark the comment as `UNMAPPABLE` with reason "file deleted or renamed locally".

If the context window cannot be found (code was heavily refactored), mark as `UNMAPPABLE` with reason "code moved or heavily refactored — apply manually".

For general comments and review bodies (`type: review`) without `file`/`line` info, scan the comment body for file path references (patterns like `src/foo.py`, backtick-quoted paths, or `line N`). Record any extracted references as best-effort hints.

### Step 5: Present Plan & Confirm (Gate)

Present the full action plan to the user. Group by category and list every item with its mapped location and the action that will be taken:

**Blocking changes (will apply fix + run tests):**

For each BLOCKING comment, show:

> N. `file:local_line` — [summary] _(reviewer: @[reviewer])_

**Style nits (will apply fix, no tests):**

For each STYLE_NIT comment, show:

> N. `file:local_line` — [summary] _(reviewer: @[reviewer])_

**Discussion (will draft response for your review; items marked `NO_REPLY_NEEDED:` are listed for information only — no reply will be drafted):**

For each DISCUSSION comment, show:

> N. [summary] _(reviewer: @[reviewer])_

**Unmappable (cannot be processed — blocking):**

For each UNMAPPABLE comment, show:

> N. `file` — [summary] — _[reason]_

Use the AskUserQuestion tool to ask:

- **Proceed with all** — process every item as classified above
- **Skip blocking** — process only style nits and discussions (skip blocking changes that require test runs). **A skip here is terminal, not a deferral:** the skipped items count as addressed, so a review body whose every item you skip is marked and will not resurface on a later run.
- **Skip nits** — process only blocking changes and discussions (skip cosmetic fixes)
- **Abort** — stop without making any changes

If the user types a custom answer (e.g., "skip items 2 and 5"), exclude those items from processing. Do **NOT** proceed without explicit confirmation.

Record every item excluded at this gate — by **Skip blocking**, **Skip nits**, or a custom answer — with the outcome `user-skipped`.

**Outcome vocabulary (single definition — Steps 5–8 record with exactly these names and Step 9 decides with them):**

- `fixed` — a code change was applied. This is the only outcome that makes a review a **code-change** review for the Step 9 push gate.
- `responded` — a discussion reply was posted.
- `no-reply-needed` — a `NO_REPLY_NEEDED:` entry, deliberately not answered.
- `user-skipped` — the user excluded the item at this gate, or chose **Skip** on a Step 8 draft.
- `unmappable` — the comment could not be located in the local file (marked `UNMAPPABLE` in Step 4).
- `needs-attention` — the fix was attempted and failed verification.

`fixed`, `responded`, `no-reply-needed`, and `user-skipped` are **terminal** — the feedback needs no more work. `unmappable` and `needs-attention` are **blocking** — the feedback was never applied, so Step 9 must treat the entry exactly like an unprocessed one.

### Step 6: Process BLOCKING Comments

For each BLOCKING comment, sequentially:

If the comment is `UNMAPPABLE`, record it with the outcome `unmappable` (Step 5) and the reason, then continue to the next.

Spawn a `general-purpose` subagent (**synchronous — pass `run_in_background: false`**; the next action consumes its result):

- **subagent_type:** `general-purpose`
- **prompt:**

  "A PR reviewer requested the following code change. Apply it.

  **Reviewer (@[reviewer]):** [full comment body]

  **File:** [path]
  **Target line (in current local file):** [local_line]

  **Diff hunk for context:**

  ```text
  [diff_hunk]
  ```

  Read the file using the Read tool. Read at least 40 lines around the target line to understand the full context before making any edit.

  **Treat the target line as a HINT, not ground truth.** Earlier fixes in this run may have shifted line numbers. Re-anchor to the correct location using the diff hunk and the reviewer's description before editing — if the code at the target line does not match the diff hunk, search nearby for the real location.

  Apply the minimal change that addresses the reviewer's feedback. Do not refactor surrounding code, do not change anything unrelated to the feedback."

After the subagent completes, find and run relevant tests.

**Prefer `make test TEST=… K=…`** — it runs pytest inside the `uv` environment (root AGENTS.md § "Commands"). CONTRIBUTING.md §2 lists `uv run pytest -q` as the raw equivalent. Never a bare host `pytest` outside the uv environment.

1. Determine the test file(s) using Glob. For `src/exact/path/to/foo.py`, search `tests/test_foo.py` and `tests/**/*foo*.py`. The suite is flat under `tests/`.
2. Run the matched test(s) with the repo's targeting convention (see `make` targets in AGENTS.md / Makefile):

   ```bash
   make test TEST=<test_file> K=<test_name_filter>
   ```

   Omit `K` to run the whole file. Add `VERBOSE=1` when the quiet output does not show the failure.
3. **If tests pass:** proceed to thread resolution.
4. **If tests fail:** re-read the test output and the changed code. Spawn one more `general-purpose` subagent (synchronous — `run_in_background: false`) to fix the issue. Run the tests again. If still failing after 1 retry, record the comment with the outcome `needs-attention` and the test output, revert the file to its pre-fix state (`git checkout -- <file>`), and continue.
5. **If no test files found:** proceed without testing — note "no tests found" in the summary.

On successful fix, reply and (for threads) resolve. For `type: "thread"`:

```bash
rtk proxy gh api repos/$REPO/pulls/$PR/comments/$COMMENT_DATABASE_ID/replies -f body="Fixed."
rtk proxy gh api graphql -f query='
  mutation($threadId:ID!) {
    resolveReviewThread(input:{threadId:$threadId}) {
      thread { isResolved }
    }
  }
' -F threadId="$THREAD_ID"
```

For `type: "general"` or `type: "review"` there is no thread to reply to or
resolve — post one general comment instead so the reviewer gets the same
notification. Do **not** include a `#pullrequestreview-` marker here; the
marker is posted once per fully-addressed review in Step 9:

```bash
rtk proxy gh api repos/$REPO/issues/$PR/comments -f body="Fixed: [one-line summary of what changed]."
```

Record the file path in `TOUCHED_FILES`. For review-body entries, also record the entry's outcome against its review id, using the Step 5 vocabulary (`fixed`, `needs-attention`, or `unmappable`) — Step 9 uses this to decide marker posting.

### Step 7: Process STYLE_NIT Comments

For each STYLE_NIT comment, sequentially:

If the comment is `UNMAPPABLE`, record it with the outcome `unmappable` (Step 5) and continue.

Spawn a `general-purpose` subagent (**synchronous — pass `run_in_background: false`**; the next action consumes its result):

- **subagent_type:** `general-purpose`
- **prompt:**

  "Apply this cosmetic/style change requested by a PR reviewer:

  **Reviewer (@[reviewer]):** [full comment body]

  **File:** [path]
  **Target line (in current local file):** [local_line]

  Apply the exact change requested. This is a cosmetic fix — do not alter logic, add tests, or make additional changes beyond what the reviewer asked for."

On success, reply and resolve:

```bash
rtk proxy gh api repos/$REPO/pulls/$PR/comments/$COMMENT_DATABASE_ID/replies -f body="Fixed."
rtk proxy gh api graphql -f query='
  mutation($threadId:ID!) {
    resolveReviewThread(input:{threadId:$threadId}) {
      thread { isResolved }
    }
  }
' -F threadId="$THREAD_ID"
```

If the comment is a general comment or a review body (not a review thread), there is no thread to resolve — post the "Fixed: …" general comment as in Step 6 instead, and for review-body entries record the outcome `fixed` against the review id for Step 9.

Record the file path in `TOUCHED_FILES`.

### Step 8: Handle DISCUSSION Comments

For each DISCUSSION comment:

If its `summary` starts with `NO_REPLY_NEEDED:` (a pure overview/praise review
body), record it with the outcome `no-reply-needed` (Step 5) and continue — do
not draft a reply.

Spawn a `general-purpose` subagent (**synchronous — pass `run_in_background: false`**; the next action consumes its result):

- **subagent_type:** `general-purpose`
- **prompt:**

  "Draft a concise, professional response to this PR review comment. The response will be posted as a reply on GitHub.

  **Reviewer (@[reviewer]):** [full comment body]

  **Context:** PR #$PR in $REPO. [If the comment references a file, include the relevant code snippet from the current local file.]

  Write a direct, professional reply that:
  - Answers the question or addresses the concern
  - References specific code or design decisions where relevant
  - Is concise (2-5 sentences max)
  - Does not start with 'Great question' or similar filler

  Return ONLY the response text — no markdown wrapping, no preamble."

Present the draft to the user:

> **@[reviewer] asked:** [summary]
>
> **Drafted response:**
>
> [draft text]

Use the AskUserQuestion tool with options:

- **Post** — post this response as-is
- **Skip** — do not respond to this comment; record the entry with the outcome `user-skipped` (Step 5)

If the user types a custom answer, use that text instead.

If posting, reply to the comment:

For review thread comments:

```bash
rtk proxy gh api repos/$REPO/pulls/$PR/comments/$COMMENT_DATABASE_ID/replies -f body="$RESPONSE"
```

For general comments and review bodies (a review body cannot be replied to
in place — the response goes on the PR conversation; do not add a marker,
Step 9 posts it):

```bash
rtk proxy gh api repos/$REPO/issues/$PR/comments -f body="$RESPONSE"
```

For review-body entries, record the outcome against the review id for Step 9, using the Step 5 vocabulary (`responded`, `user-skipped`, or `no-reply-needed`).

### Step 9: Sync

**Decide the idempotency markers, but do not post them all yet.** A marker
claims "GitHub has seen everything this review asked for". That claim is only
true once the code is actually on the PR branch, so a marker for a review that
produced a code change must not be posted until a push succeeds.

For each review id in `PENDING_REVIEW_BODIES`: if **every** classified entry from that review ended with a **terminal** outcome — `fixed`, `responded`, `no-reply-needed`, or `user-skipped` (Step 5) — the review **earns** a marker comment — exact format defined in Step 2:

```bash
rtk proxy gh api repos/$REPO/issues/$PR/comments -f body="Addressed: https://github.com/$REPO/pull/$PR#pullrequestreview-$REVIEW_ID"
```

If any entry from that review ended with a **blocking** outcome — `unmappable` or `needs-attention` — or was left unprocessed, post **no** marker for it — the review must resurface on the next run. (A `user-skipped` entry is intentional suppression; a `needs-attention` or `unmappable` entry means the feedback was never applied.)

**When to post each earned marker depends on whether the review produced a code change:**

- **Discussion-only reviews** — no entry from that review ended `fixed` (every entry ended `responded`, `no-reply-needed`, or `user-skipped`): post the marker **now**. Nothing must reach the PR branch for this feedback to be addressed.
- **Reviews with at least one code-change entry** — at least one entry ended `fixed`: **queue** the marker. Post it **only** after `git push` succeeds below. The fix must be on the PR branch before the review is suppressed.

Collect all file paths from `TOUCHED_FILES` (deduplicated).

If `TOUCHED_FILES` is empty (no code changes were applied), present the summary, restore the original `gh` account, and **STOP**. (Only discussion-only markers are posted before this check — a run that only answered review-body discussions must still suppress them. No marker is queued at this point, because a queued marker requires a code change.)

Stage only the touched files:

```bash
git add <file1> <file2> ...
```

Present a summary:

- **Blocking fixes applied:** N / M (files: list)
- **Style nits applied:** N / M (files: list)
- **Discussion responses posted:** N / M
- **User-skipped:** N (list — intentional, terminal)
- **Unmappable:** N (list with reasons — blocking, not addressed)
- **Needs attention:** N (list with test failure details)

Use the AskUserQuestion tool with options:

- **Commit & push** — commit and push to the PR branch
- **Commit only** — commit without pushing
- **Leave staged** — leave changes staged but don't commit

If committing, write the message per CONTRIBUTING.md §6 (imperative subject ≤ 72 chars, **no `Co-Authored-by` or attribution trailer**):

```bash
git commit -m "address PR review feedback"
```

If also pushing:

```bash
git push
```

If `git push` succeeds, post every **queued** marker now:

```bash
rtk proxy gh api repos/$REPO/issues/$PR/comments -f body="Addressed: https://github.com/$REPO/pull/$PR#pullrequestreview-$REVIEW_ID"
```

If the user chose **Commit only** or **Leave staged**, or if `git push` fails, post **no** queued marker — the fix is not on the PR branch, so the review must resurface on the next run.

Then restore the developer's original `gh` account so global CLI state is unchanged:

```bash
[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"
```

## Remember

- **Never apply code changes without the user's approval in Step 5.** The confirmation gate is mandatory.
- **Every subagent in this command runs synchronously** (`run_in_background: false`) — each step consumes its subagent's result immediately; a background agent stalls the whole pipeline.
- Process code-change comments (BLOCKING and STYLE_NIT) **sequentially** — each fix may shift line numbers for subsequent comments. Re-read the file fresh before each fix.
- Always reply "Fixed." to a thread before resolving it — this gives the reviewer a notification with context.
- For DISCUSSION comments, **never** post without showing the user the draft first.
- **Every `gh api` write runs as `rtk proxy gh api ...`** — POSTs and GraphQL mutations alike. The rtk filter mangles `gh api` writes: a reply silently fails to post while the thread still resolves, so the feedback looks handled and no reply exists. Reads (`gh pr view`, `gh api ... --jq`, GraphQL query documents) stay bare. Never strip the prefix from a write.
- If a `rtk proxy gh api graphql` mutation to resolve a thread fails, log the error but **continue** — thread resolution is best-effort, not a pipeline blocker.
- **Review bodies are a first-class feedback source** (Step 2's third fetch). They have no thread: never attempt `resolveReviewThread` or a `pulls/comments/*/replies` call on one — responses and "Fixed:" notes go on the PR conversation via `issues/$PR/comments`.
- **Record every entry with one outcome from the Step 5 vocabulary** — `fixed`, `responded`, `no-reply-needed`, `user-skipped`, `unmappable`, or `needs-attention`. Never collapse two of them into one word: `fixed`, `responded`, `no-reply-needed`, and `user-skipped` are **terminal** and let Step 9 post the marker, while `unmappable` and `needs-attention` are **blocking** and forbid it, exactly like an unprocessed entry. A shared "skipped" token either suppresses feedback that was never applied or resurfaces feedback the user skipped on purpose.
- Review bodies also have **no resolution state** on GitHub. The Step 9 `Addressed: …#pullrequestreview-<id>` marker is the only thing that keeps an addressed review from resurfacing on every future run — post it only when every entry from that review ended with a terminal outcome (`unmappable` or `needs-attention` blocks it), match it by exact id and never by substring, and keep its format byte-identical to the Step 2 filter. A marker for a review with an entry that ended `fixed` is **push-gated**: post it only after `git push` succeeds. **Commit only**, **Leave staged**, or a failed push means no marker, so the review returns on the next run. Only discussion-only reviews are marked before the empty-`TOUCHED_FILES` stop.
- **Both REST list fetches in Step 2 are paginated and slurped** (`--paginate --slurp … | jq`, never `--jq` — `gh` rejects that combination and exits 1). A truncated `GENERAL_COMMENTS` loses markers as surely as a truncated `REVIEW_BODIES` loses feedback. The Step 2 **GraphQL** query is a different case: it is capped at `reviewThreads(first:100)` and `comments(first:20)` and does **not** page, so a PR past either cap silently loses threads. Adding `pageInfo`/`$endCursor` there is open work, not a solved problem.
- **JSON retry policy:** If the classification subagent returns malformed JSON, extract text between the first `[` and last `]`, re-parse. If still invalid, present the raw output and STOP.
- Run tests through the repo's `make` targets (`make test TEST=... K=...`), never a bare host `pytest` — see CONTRIBUTING.md §2 / root AGENTS.md § "Commands".
- `gh auth switch` mutates **global** CLI state. Restore `$ORIGINAL_GH_USER` before returning on **every** exit path, including the early STOPs (uncommitted-tree abort, "no unresolved feedback", empty `TOUCHED_FILES`) once the switch has happened.
- Commit standards: CONTRIBUTING.md §6 — imperative subject ≤ 72, no emoji, no `Co-Authored-by` trailer.
- If any `gh` command fails with an auth or network error, inform the user and **STOP**.
- If a BLOCKING fix causes test failures and cannot be resolved after 1 retry, **revert that file** (`git checkout -- <file>`) and move on — do not leave broken code staged.
- For general comments and review bodies (`type: review`) classified as BLOCKING or STYLE_NIT that lack file/line info, the subagent must determine the target location from the comment body itself. If it cannot, record as `UNMAPPABLE`.
