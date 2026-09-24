---
description: >
  Shepherd an open GitHub PR until it is mergeable — address review feedback (classify, fix,
  test, reply, resolve threads) and keep CI green, in a monitor loop. Asks the run policy once at
  launch, then runs on its own. Use /create-pr to create the PR first; use /review-pr to review
  someone else's PR.
argument-hint: "[pr-number]  (default: the PR for the current branch)"
allowed-tools: Bash(scripts/gh-exact*), Bash(rtk proxy scripts/gh-exact api*), Bash(rtk proxy make pr-feedback*), Bash(git branch*), Bash(git status*), Bash(git show*), Bash(git diff*), Bash(git log*), Bash(git fetch*), Bash(git rev-list*), Bash(git checkout*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(rtk proxy make test*), Bash(rtk proxy make check*), Agent, Task, Read, Glob, Grep, Monitor, AskUserQuestion
disable-model-invocation: true
---

# Babysit PR

Shepherd PR **$ARGUMENTS** to mergeable: address review feedback and keep CI green. This is a
monitor loop, not a single pass.

Standards (commit format, test commands, CI gates) are defined in @CONTRIBUTING.md — treat it as
the single source of truth and do not invent rules not in that file. Commit and PR rules are §7
("Conventions"). §6 says a change is ready when the local gates are clean, so every push first
passes `make check` (Step 10), with or without a CI pipeline.

## Step 0: Inputs and run policy

`PR`: the number from `$ARGUMENTS`, with a leading `#` removed. When `$ARGUMENTS` is empty, use the
PR for the current branch (`scripts/gh-exact pr view --json number --jq .number`). If there is
none, say so and **STOP**. `PR` must be digits only; otherwise **STOP**.

Ask the run policy **once**, with one `AskUserQuestion` call holding two questions. The loop never
asks these again.

- **Code fixes** — `Apply automatically`: each cycle applies every CI fix and every BLOCKING and
  STYLE_NIT fix. `Ask each cycle`: each cycle shows the plan (Step 6) and waits for your answer.
- **Push** — `Push automatically`: push after `make check` passes. `Ask before each push`: each push
  waits for your answer.

Record them as `FIX_POLICY` and `PUSH_POLICY`. Discussion replies are always posted without review
(Step 9). No policy controls them.

## Step 1: Validate environment (once)

`EXACT_GITHUB_USER` must name the account the loop acts as. The first `scripts/gh-exact` call
below checks it: it fails with "EXACT_GITHUB_USER is not set" or "gh has no token for …". On that
failure, inform the user and **STOP**.

**Every `gh` call runs through `scripts/gh-exact`**, never bare `gh`. The wrapper sets `GH_TOKEN`
to the token of `EXACT_GITHUB_USER` for that one process. The global `gh` account never changes,
so there is nothing to restore on any exit path. `make pr-feedback` does the same internally.

Run in parallel:

```bash
scripts/gh-exact pr view $PR --json state,isDraft,headRefOid,headRefName --jq '{state,isDraft,headRefOid,headRefName}'
scripts/gh-exact repo view --json nameWithOwner --jq '.nameWithOwner'
git branch --show-current
git status --short --untracked-files=no
```

Record `PR_STATE`, `IS_DRAFT`, `HEAD_BRANCH`, `REPO` (`owner/repo`), `LOCAL_BRANCH` and
`WORKING_TREE_STATUS`.

**Guards:**

- If `PR_STATE` is not `OPEN` or `IS_DRAFT` is `true`, inform the user and **STOP**.
- If `LOCAL_BRANCH` does not match `HEAD_BRANCH`, warn: "You are on branch `$LOCAL_BRANCH` but the
  PR is on `$HEAD_BRANCH`. Switch branches first." **STOP**.
- If `WORKING_TREE_STATUS` is non-empty, **STOP**: "Commit or stash your changes first." The loop stages each fix as it lands, and reverts a failed fix from the index
  (Step 7). Your own uncommitted edits in a touched file would be committed or lost.

Start the run state. It lives only in this conversation:

- `HANDLED = {}` — the run ledger. One entry per processed feedback entry, keyed by its ledger key
  (Step 4), with its outcome (Step 6 vocabulary) and its review id when it came from a review body.
- `TOUCHED_FILES = []` — files staged since the last commit. Deduplicate it.
- `QUEUED_MARKERS = []` — review markers that wait for a successful push (Step 10).
- `CI_ATTEMPTS = {}` — CI fix attempts per failing check name (Step 3).
- `PUSHED_THIS_CYCLE = false` — reset at the start of every Step 2.
- `HAS_CI` — decide it once, now: `true` when Glob finds any file under `.github/workflows/`. It
  decides only whether an empty `statusCheckRollup` is expected. Checks that do appear are always
  tested, whatever `HAS_CI` says: GitHub Apps and external services add checks without a workflow
  file.
- `EMPTY_WAITS = 0` — waits spent on an empty `statusCheckRollup` since the last push (Step 11,
  rule 2). Reset it to `0` after every successful push.

## The loop

Repeat Steps 2–11 until an exit condition in Step 11 holds.

### Step 2: Snapshot

Set `PUSHED_THIS_CYCLE = false`. Then:

```bash
scripts/gh-exact pr view $PR --json state,isDraft,mergeable,reviewDecision,statusCheckRollup,headRefOid,headRefName
git branch --show-current
git fetch origin $HEAD_BRANCH
git rev-list --count HEAD..origin/$HEAD_BRANCH
```

Record `HEAD_SHA` (`headRefOid`). Print one status line for the cycle.

Go to Step 11 as **Blocked** when any of these holds:

- `state` is not `OPEN`, or `isDraft` is `true`;
- the local branch no longer matches `HEAD_BRANCH`;
- the `rev-list` count is above `0`: the PR branch has commits that the local branch does not have
  (a reviewer's "Commit suggestion", or another push). A human must integrate them.

### Step 3: CI

Skip this step when no check in `statusCheckRollup` is failing or stuck.

- **Failing:** fetch the failing job's log tail (`scripts/gh-exact run view <id> --log-failed`), and diagnose. A
  failing check that is not a GitHub Actions run has no log to fetch: go to Step 11 as
  **Blocked**, and name the check.
  - When `FIX_POLICY` is `Ask each cycle`, show the diagnosis and the intended fix, and ask with
    AskUserQuestion: **Apply** or **Stop**. **Stop** goes to Step 11 as **Blocked** ("CI fix
    declined"). This gate is separate from the Step 6 review plan, because Step 6 does not run in
    a cycle with no review feedback.
  - Apply the minimal fix. Run `rtk proxy make check` to verify it. If it fails, try one more fix. If it
    still fails, revert the files (`git checkout -- <file>`), record the failure, and continue.
  - On success, stage the files (`git add <file>`) and add them to `TOUCHED_FILES`. Step 10
    commits them.
  - Increase `CI_ATTEMPTS[<check name>]`. When it reaches 2 and the check still fails, go to
    Step 11 as **Blocked**.
  - Never re-run a failed workflow without a fix, unless the failure is demonstrably an
    infrastructure flake. State the evidence.
- **Stuck:** a job queued or in progress beyond ~15 min with no log progress:
  `scripts/gh-exact run rerun <id>`. Note it in the cycle status line.

### Step 4: Fetch the pending feedback

```bash
rtk proxy make pr-feedback PR=$PR
```

Run it through `rtk proxy`, so no output filter can shorten the JSON.

It prints one JSON object. On a non-zero exit, report the error and **STOP**: a partial fetch
reads as "no feedback", and a lost marker re-processes an addressed review.

- `threads` — unresolved review threads that wait for this account. Each carries `key` (its ledger
  key), `id`, `path`, `line`, `commit_sha` (the commit `line` refers to), `replyToDatabaseId` (the
  only valid reply target), and its 20 newest `comments`, each with its `diffHunk`. An outdated
  thread has `line: null`. A thread whose latest comment is by
  `$EXACT_GITHUB_USER` is not listed: it waits for the reviewer.
- `generalComments` — general PR comments by anyone but `$EXACT_GITHUB_USER`. The loop never
  answers itself.
- `reviewBodies` — submitted, non-empty review bodies that no marker has addressed. The own
  "Found N issues … see inline comments." counter line is not listed. Each carries its
  `commit_sha`.

`.claude/hooks/pr-feedback.py` owns the pagination, the error checks, and the marker match (exact
id, never a substring). Do not re-implement them here.

**Marker format (single definition — the script's filter and the Step 10 posting use exactly
this):** a general comment by `$EXACT_GITHUB_USER` whose body is exactly
`Addressed: https://github.com/<REPO>/pull/<PR>#pullrequestreview-<id>`, with no other text. Review
bodies have no resolution state on GitHub; this marker is the only idempotency signal across runs.

**Ledger keys:**

- **Thread:** the `key` field (`<thread id>@<databaseId of the latest comment>`). A new comment on a
  handled thread makes a new key, so the thread comes back.
- **General comment:** `<comment id>`.
- **Review-body entry:** `<review id>#<entry index>`, from Step 5's split. One review can hold
  several entries, and each keeps its own outcome.

**Ledger filter.** Drop every thread and general comment whose key is in `HANDLED`. Drop a review
body when any `HANDLED` entry carries its review id: the loop classifies each review once per run.
Without this filter the loop processes the same item again each cycle:

- a general comment has no resolution state and no marker;
- a review with a queued marker stays visible until a push succeeds.

**Accepted limit.** `HANDLED` lives for one run. A new run answers again the general comments that
an earlier run already answered: they have no resolution state and no marker.

Record the survivors as `PENDING_THREADS`, `GENERAL_COMMENTS`, and `PENDING_REVIEW_BODIES`. If all
three are empty, skip to Step 10.

### Step 5: Classify comments

Spawn a single `general-purpose` subagent (**synchronous — pass `run_in_background: false`**; the
pipeline consumes its result immediately):

- **subagent_type:** `general-purpose`
- **prompt:**

  "You are classifying PR review feedback. For each comment below, assign exactly one category:

  - **BLOCKING** — The reviewer is requesting a code change that must be addressed before merge.
    Indicators: imperative language ('change this', 'fix this', 'remove this', 'add error
    handling'), reported bugs, logic corrections, security concerns.
  - **STYLE_NIT** — A non-blocking cosmetic suggestion. Indicators: 'nit:', 'minor:', rename
    suggestions, formatting preferences, comment wording tweaks. These are safe to apply without
    testing.
  - **DISCUSSION** — A question, architectural discussion, or comment that cannot be addressed by
    changing code. Indicators: 'why did you...', 'have you considered...', 'what about...',
    requests for explanation, praise/acknowledgment.

  If a thread has multiple comments (a conversation), classify based on the **latest unresolved
  ask**. If the thread is a back-and-forth that appears resolved in conversation even though the
  thread is still open, classify as DISCUSSION with a note.

  **Review threads (line-attached):**

  ```json
  $PENDING_THREADS
  ```

  **General PR comments:**

  ```json
  $GENERAL_COMMENTS
  ```

  **Review bodies** (PR-level review summaries — often multi-topic; split one review body into one
  entry per distinct actionable point, all sharing the review's id. A `state` of CHANGES_REQUESTED
  is a strong BLOCKING signal. Classify a pure overview/praise body as DISCUSSION and start its
  `summary` with 'NO_REPLY_NEEDED:' — Step 9 skips drafting for those):

  ```json
  $PENDING_REVIEW_BODIES
  ```

  Return a JSON array ordered by: BLOCKING first, then STYLE_NIT, then DISCUSSION.

  ```json
  [
    {
      \"id\": \"<thread node_id, general comment id, or review id>\",
      \"key\": \"<the thread's key, copied verbatim; null for general and review items>\",
      \"type\": \"thread|general|review\",
      \"category\": \"BLOCKING|STYLE_NIT|DISCUSSION\",
      \"file\": \"<path or null for general comments>\",
      \"line\": <line_number or null>,
      \"diff_hunk\": \"<diff hunk string or null>\",
      \"commit_sha\": \"<for a thread, its commit_sha, copied verbatim; for a review, the review's commit_sha; else null>\",
      \"summary\": \"<one-sentence summary of what is being asked>\",
      \"body\": \"<full original comment text>\",
      \"reviewer\": \"<author login>\",
      \"comment_database_id\": <the thread's replyToDatabaseId (replies must target the thread's first comment); null for general and review items>
    }
  ]
  ```

  For review-body entries, use the `commit_sha` already attached to the review object — do not set
  it to null. `file`/`line`/`diff_hunk` are null unless the body itself names them; extract any file
  references from the body text into `file` as a best-effort hint."

Record the result as `CLASSIFIED_COMMENTS`. JSON retry policy: if not valid JSON, extract between
the first `[` and the last `]`, and re-parse. If still invalid, present the raw classification to
the user, and **STOP**.

**Map comment locations to local files.** For each comment in `CLASSIFIED_COMMENTS` that has a
non-null `file` and `line`:

1. Get the file content at the comment's commit: `git show <commit_sha>:<path>`. Review-body
   entries carry the review's own `commit_sha` even when `file`/`line` were extracted from the body
   text — use `HEAD_SHA` only if `commit_sha` is genuinely absent.
2. Extract a context window: 3 lines above and 3 lines below the comment's `line` from that version.
3. Read the current local file using the Read tool.
4. Search for the context window in the current local file. Allow fuzzy matching — the target line
   must match, and at least 4 of the 6 surrounding context lines must match in order.
5. Record the `local_line` — the adjusted line number in the current file.

If the file does not exist locally, mark the comment as `UNMAPPABLE` with reason "file deleted or
renamed locally". If the context window cannot be found, mark it as `UNMAPPABLE` with reason "code
moved or heavily refactored — apply manually".

For general comments and review bodies without `file`/`line` info, scan the comment body for file
path references (patterns like `src/foo.py`, backtick-quoted paths, or `line N`). Record any
extracted references as best-effort hints.

### Step 6: Fix gate and outcome vocabulary

**Outcome vocabulary (single definition — Steps 6–10 record with exactly these names):**

- `fixed` — a code change was applied. This is the only outcome that makes a review a
  **code-change** review for the Step 10 push gate.
- `responded` — a discussion reply was posted.
- `no-reply-needed` — a `NO_REPLY_NEEDED:` entry, deliberately not answered.
- `user-skipped` — the user excluded the item at this gate.
- `unmappable` — the comment could not be located in the local file.
- `needs-attention` — the fix was attempted and failed verification.

`fixed`, `responded`, `no-reply-needed`, and `user-skipped` are **terminal**. `unmappable` and
`needs-attention` are **blocking** — the feedback was never applied, so Step 10 treats the entry
exactly like an unprocessed one. Every processed entry goes into `HANDLED` under its ledger key
(Step 4), with its outcome. The entry index of a review-body entry is its position among the
`CLASSIFIED_COMMENTS` entries that share its review id, counted from 0.

**Variables for the API calls in Steps 7–10**, taken from each classified entry:

- `THREAD_ID` — the entry's `id` when `type` is `thread`;
- `COMMENT_DATABASE_ID` — the entry's `comment_database_id`;
- `REVIEW_ID` — the entry's `id` when `type` is `review`;
- `RESPONSE` — the reply text from the Step 9 subagent.

**When `FIX_POLICY` is `Apply automatically`:** process every item. Go to Step 7.

**When `FIX_POLICY` is `Ask each cycle`:** present the plan. Group by category and list every item
with its mapped location and the action:

- **Blocking changes (will apply fix + run tests):** `N. file:local_line — [summary] (reviewer: @[reviewer])`
- **Style nits (will apply fix, no tests):** the same shape.
- **Discussion (a reply will be drafted and posted; `NO_REPLY_NEEDED:` items get no reply):**
  `N. [summary] (reviewer: @[reviewer])`
- **Unmappable (cannot be processed — blocking):** `N. file — [summary] — [reason]`

Use the AskUserQuestion tool with these options:

- **Proceed with all** — process every item as classified above
- **Skip blocking** — process only style nits and discussions. **A skip is terminal, not a
  deferral:** the skipped items count as addressed, so a review body whose every item you skip is
  marked and will not resurface.
- **Skip nits** — process only blocking changes and discussions
- **Abort** — apply no review fix in this cycle, and exit the loop (Step 11, blocked). A CI fix
  staged in Step 3 stays staged; the final report lists it.

If the user types a custom answer (e.g., "skip items 2 and 5"), exclude those items. Record every
excluded item with the outcome `user-skipped`.

### Step 7: Process BLOCKING comments

For each BLOCKING comment, sequentially:

If the comment is `UNMAPPABLE`, record it with the outcome `unmappable` and the reason, then
continue to the next.

Spawn a `general-purpose` subagent (**synchronous — pass `run_in_background: false`**):

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

  Read the file using the Read tool. Read at least 40 lines around the target line to understand
  the full context before making any edit.

  **Treat the target line as a HINT, not ground truth.** Earlier fixes in this run may have shifted
  line numbers. Re-anchor to the correct location using the diff hunk and the reviewer's
  description before editing — if the code at the target line does not match the diff hunk, search
  nearby for the real location.

  Apply the minimal change that addresses the reviewer's feedback. Do not refactor surrounding
  code, do not change anything unrelated to the feedback."

After the subagent completes, find and run the relevant tests. Use `rtk proxy make test TEST=… K=…` — it runs
pytest inside the `uv` environment (root AGENTS.md § "Commands"). Never a bare host `pytest`.

1. Determine the test file(s) using Glob. For `src/exact/path/to/foo.py`, search
   `tests/test_foo.py` and `tests/**/*foo*.py`. The suite is flat under `tests/`.
2. Run the matched test(s): `rtk proxy make test TEST=<test_file> K=<test_name_filter>`. Omit `K` to run the
   whole file. Add `VERBOSE=1` when the quiet output does not show the failure.
3. **If tests pass:** proceed to thread resolution.
4. **If tests fail:** re-read the test output and the changed code. Spawn one more
   `general-purpose` subagent (synchronous) to fix the issue. Run the tests again. If still failing
   after 1 retry, record the comment with the outcome `needs-attention` and the test output, revert
   the fix, and continue. A fix can change more than one file. `git diff --name-only` lists the
   files of this fix only, because every earlier fix of this run is already staged (below). Revert
   each file it lists (`git checkout -- <file>`). The revert restores the file from the index, so
   only this fix is lost.
5. **If no test files found:** proceed without testing — note "no tests found" in the summary.

On a successful fix, reply and (for threads) resolve. For `type: "thread"`:

```bash
rtk proxy scripts/gh-exact api repos/$REPO/pulls/$PR/comments/$COMMENT_DATABASE_ID/replies -f body="Fixed."
rtk proxy scripts/gh-exact api graphql -f query='
  mutation($threadId:ID!) {
    resolveReviewThread(input:{threadId:$threadId}) {
      thread { isResolved }
    }
  }
' -F threadId="$THREAD_ID"
```

For `type: "general"` or `type: "review"` there is no thread to reply to or resolve — post one
general comment instead. Do **not** include a `#pullrequestreview-` marker here; Step 10 posts the
marker once per fully-addressed review:

```bash
rtk proxy scripts/gh-exact api repos/$REPO/issues/$PR/comments -f body="Fixed: [one-line summary of what changed]."
```

Stage every file that `git diff --name-only` lists at once (`git add <file>`), add each one to
`TOUCHED_FILES`, and record the outcome in `HANDLED`.

### Step 8: Process STYLE_NIT comments

For each STYLE_NIT comment, sequentially:

If the comment is `UNMAPPABLE`, record it with the outcome `unmappable` and continue.

Spawn a `general-purpose` subagent (**synchronous — pass `run_in_background: false`**):

- **subagent_type:** `general-purpose`
- **prompt:**

  "Apply this cosmetic/style change requested by a PR reviewer:

  **Reviewer (@[reviewer]):** [full comment body]

  **File:** [path]
  **Target line (in current local file):** [local_line]

  Apply the exact change requested. This is a cosmetic fix — do not alter logic, add tests, or make
  additional changes beyond what the reviewer asked for."

If the subagent reports that it could not apply the change, revert each file that
`git diff --name-only` lists (`git checkout -- <file>`), record the outcome `needs-attention`, and
continue.

On success, reply and resolve with the same two calls as Step 7. For a general comment or a review
body, post the "Fixed: …" general comment as in Step 7 instead. Style nits run no tests here;
`make check` in Step 10 covers them before any push.

Stage every file that `git diff --name-only` lists at once (`git add <file>`), add each one to
`TOUCHED_FILES`, and record the outcome `fixed` in `HANDLED`.

### Step 9: Handle DISCUSSION comments

For each DISCUSSION comment:

If its `summary` starts with `NO_REPLY_NEEDED:`, record the outcome `no-reply-needed` and continue.

Spawn a `general-purpose` subagent (**synchronous — pass `run_in_background: false`**):

- **subagent_type:** `general-purpose`
- **prompt:**

  "Draft a concise, professional response to this PR review comment. The response will be posted
  as a reply on GitHub.

  **Reviewer (@[reviewer]):** [full comment body]

  **Context:** PR #$PR in $REPO. [If the comment references a file, include the relevant code
  snippet from the current local file.]

  Write a direct, professional reply that:
  - Answers the question or addresses the concern
  - References specific code or design decisions where relevant
  - Is concise (2-5 sentences max)
  - Does not start with 'Great question' or similar filler

  Return ONLY the response text — no markdown wrapping, no preamble."

Post the draft without review. For review thread comments:

```bash
rtk proxy scripts/gh-exact api repos/$REPO/pulls/$PR/comments/$COMMENT_DATABASE_ID/replies -f body="$RESPONSE"
```

For general comments and review bodies (a review body cannot be replied to in place — the response
goes on the PR conversation; do not add a marker, Step 10 posts it):

```bash
rtk proxy scripts/gh-exact api repos/$REPO/issues/$PR/comments -f body="$RESPONSE"
```

Record the outcome `responded` in `HANDLED`, and keep the text for the final report.

### Step 10: Sync

**Decide the idempotency markers.** A marker claims "GitHub has seen everything this review asked
for". That claim is only true once the code is on the PR branch.

For each review id with an entry processed in this cycle, look up **every** `HANDLED` entry that
carries that review id. If all of them ended with a **terminal** outcome, the review **earns** a
marker comment — exact format defined in Step 4:

```bash
rtk proxy scripts/gh-exact api repos/$REPO/issues/$PR/comments -f body="Addressed: https://github.com/$REPO/pull/$PR#pullrequestreview-$REVIEW_ID"
```

If any entry from that review ended with a **blocking** outcome, or was left unprocessed, post
**no** marker for it.

**When to post each earned marker:**

- **Discussion-only reviews** — no entry ended `fixed`: post the marker **now**.
- **Reviews with at least one `fixed` entry**: add the marker to `QUEUED_MARKERS`. Post it **only**
  after a `git push` succeeds. A queued marker stays queued across cycles until a push succeeds.

**Commit** when `TOUCHED_FILES` is not empty. Every file in it is already staged (Steps 3, 7, 8).
Follow CONTRIBUTING.md §7 ("Commits / PRs"), and pass the message with a HEREDOC. Pre-commit runs the
repo hooks — do not skip them.

- The commit succeeds: clear `TOUCHED_FILES`.
- A hook rejects the commit: go to Step 11 as **Blocked**. Report the hook output. The fixes stay
  staged. Their threads already say "Fixed.", so list them in the report.

**Push** when the local branch is ahead of the PR branch:

```bash
git rev-list --count origin/$HEAD_BRANCH..HEAD
```

When the count is `0`, skip to Step 11. Otherwise:

1. Run `rtk proxy make check`. If it fails, go to Step 11 as **Blocked**, and report the output. Nothing is
   pushed. List the threads and comments that already say "Fixed." while their code is not on the
   PR branch.
2. `PUSH_POLICY` is `Ask before each push`: show the cycle summary (below), and ask with
   AskUserQuestion: **Push** or **Hold**. **Hold** keeps the commits local and goes to Step 11 as
   **Blocked** ("commits held locally").
3. Push:

   ```bash
   git push
   ```

4. The push succeeds: set `PUSHED_THIS_CYCLE = true` and `EMPTY_WAITS = 0`, post every marker in
   `QUEUED_MARKERS`, and clear it.
5. The push fails (for example, a non-fast-forward): post no queued marker, and go to Step 11 as
   **Blocked**. Report the error.

The count also catches commits that an earlier cycle left unpushed, so no commit is forgotten.

Cycle summary:

- **Blocking fixes applied:** N / M (files: list)
- **Style nits applied:** N / M (files: list)
- **Discussion responses posted:** N / M
- **User-skipped:** N (list — intentional, terminal)
- **Unmappable:** N (list with reasons — blocking, not addressed)
- **Needs attention:** N (list with test failure details)
- **Commits not pushed:** N

### Step 11: Exit check, then wait

Check these in order. The first one that holds decides.

1. **Blocked** — report exactly what a human must do, and stop. Any of:
   - an earlier step sent the cycle here as **Blocked** (Steps 2, 3, 10);
   - the user chose **Abort** (Step 6);
   - any `HANDLED` entry has a **blocking** outcome (`unmappable`, `needs-attention`);
   - `mergeable` is `CONFLICTING`.
2. **Keep watching** — go to rule 5. Any of:
   - `PUSHED_THIS_CYCLE` is `true`, because the Step 2 snapshot predates the push, and the new
     head's checks are not seen yet;
   - a check in `statusCheckRollup` is queued or in progress;
   - `HAS_CI` is `true`, `statusCheckRollup` is empty, and `EMPTY_WAITS` is below `2`: GitHub may
     not have listed the checks yet. Add `1` to `EMPTY_WAITS`. After two such waits, an empty list
     means no workflow runs for this PR (for example, a path filter or a `main`-only trigger).
3. **Success** — all of these hold:
   - every check in `statusCheckRollup` ended `SUCCESS`, `SKIPPED` or `NEUTRAL`, or the list is
     empty and rule 2 no longer waits for it;
   - this cycle's Step 4 found no pending feedback;
   - the `rev-list` count of Step 10 is `0`;
   - `QUEUED_MARKERS` is empty;
   - `reviewDecision` is not `CHANGES_REQUESTED`.

   Report, and stop.
4. **Waiting on a reviewer** — rule 3 holds except that `reviewDecision` is `CHANGES_REQUESTED`.
   Every item is handled. A reviewer must re-review. Report, and stop.
5. **Wait** — wait with `Monitor`, paced to the slowest
   pending signal (the CI run duration), not a fixed short poll. When `HAS_CI` is `false` and
   nothing is pending, do not wait. Then go to Step 2.

Never merge the PR yourself unless explicitly told to.


## Output

Per cycle: one status line (`checks 3/5 green, 2 threads open — fixed X, pushed <sha>`).

Final:

- what was fixed;
- the commits pushed, and any commit still local;
- the threads resolved;
- every discussion reply posted, with its text;
- every blocked item with its reason;
- the current PR state.

## Remember

- **The run policy is asked once, in Step 0.** Never ask it again mid-loop. Discussion replies are
  always posted without review.
- **Every subagent runs synchronously** (`run_in_background: false`) — each step consumes its
  subagent's result immediately; a background agent stalls the whole pipeline.
- Process code-change comments (BLOCKING and STYLE_NIT) **sequentially** — each fix may shift line
  numbers for subsequent comments. Re-read the file fresh before each fix.
- Always reply "Fixed." to a thread before resolving it — this gives the reviewer a notification
  with context.
- **`HANDLED` is the only thing that stops the loop from processing an item twice in one run.**
  Add every processed entry to it, whatever its outcome. The Step 4 ledger filter must run every
  cycle.
- **Every `gh` call runs through `scripts/gh-exact`**, never bare `gh`. It acts as
  `EXACT_GITHUB_USER` for that one process, so the global account never changes.
- **Every `gh api` write runs as `rtk proxy scripts/gh-exact api ...`** — POSTs and GraphQL
  mutations alike. The rtk filter mangles `gh api` writes: a reply silently fails to post while the
  thread still resolves. Reads stay bare. Never strip the prefix from a write.
- If a `rtk proxy scripts/gh-exact api graphql` mutation to resolve a thread fails, log the error but
  **continue** — thread resolution is best-effort.
- **Review bodies are a first-class feedback source** (the `reviewBodies` list of Step 4). They have no thread:
  never attempt `resolveReviewThread` or a `pulls/comments/*/replies` call on one — responses and
  "Fixed:" notes go on the PR conversation via `issues/$PR/comments`.
- **Record every entry with one outcome from the Step 6 vocabulary.** Never collapse two of them
  into one word: `fixed`, `responded`, `no-reply-needed`, and `user-skipped` are **terminal** and
  let Step 10 post the marker, while `unmappable` and `needs-attention` are **blocking** and forbid
  it.
- The `Addressed: …#pullrequestreview-<id>` marker is the only thing that keeps an addressed review
  from resurfacing on a future run. Post it only when every entry from that review ended with a
  terminal outcome, match it by exact id and never by substring, and keep its format byte-identical
  to the Step 4 filter. A marker for a review with a `fixed` entry is **push-gated**.
- **Step 4 fetches only through `make pr-feedback`.** The script owns pagination, error checks and
  the exact-id marker match. Never fetch feedback with ad-hoc `gh api` calls.
- Run tests through the repo's `make` targets (`rtk proxy make test TEST=... K=...`), never a bare host
  `pytest`.
- **Stage each fix the moment it lands.** A failed fix is then reverted from the index without
  losing earlier fixes, and Step 10 commits exactly what was staged.
- **Never push without a clean `make check`.** The repository has no CI pipeline
  (CONTRIBUTING.md §6), so the local gate is the only check before code reaches the PR.
- If any `gh` command fails with an auth or network error, inform the user and **STOP**.
- If a BLOCKING fix causes test failures and cannot be resolved after 1 retry, **revert every file of that fix**
  (each file `git diff --name-only` lists, with `git checkout -- <file>`) and move on — do not leave
  broken code in the tree.
- For general comments and review bodies classified as BLOCKING or STYLE_NIT that lack file/line
  info, the subagent must determine the target location from the comment body itself. If it cannot,
  record as `unmappable`.
