---
description: >
  Shepherd an open GitHub PR until it is mergeable — keep CI green, address review
  feedback, unstick stalled workflows. Runs as a monitor loop, not a single pass, and
  DELEGATES each comment cycle to /resolve-pr. Use /create-pr to create the PR
  first; use /resolve-pr alone for a one-shot pass over current feedback; use
  /review-pr to review someone else's PR.
argument-hint: "[pr-number]  (default: the PR for the current branch)"
allowed-tools: Bash(gh auth*), Bash(gh api*), Bash(gh pr*), Bash(gh repo*), Bash(gh run*), Bash(git branch*), Bash(git status*), Bash(git show*), Bash(git diff*), Bash(git log*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(make test*), Bash(make check*), SlashCommand, Task, Read, Glob, Grep, Monitor, AskUserQuestion
disable-model-invocation: true
---

# Babysit PR

Shepherd a PR to mergeable: keep CI green, address review feedback, unstick stuck workflows. Runs as a monitor loop, not a single pass.

## Inputs

- `PR`: number or URL, from `$ARGUMENTS`. Default: the PR for the current branch (`gh pr view --json number`). If none exists, stop and say so.
- Repo conventions: commit/PR standards come from CONTRIBUTING.md; if the repo's /create-pr defines gh-account preflight (e.g. `EXACT_GITHUB_USER`), follow the same preflight and always restore the original account before finishing a cycle.

## Loop (repeat until exit condition)

1. **Snapshot state:** `gh pr view PR --json state,mergeable,reviewDecision,statusCheckRollup` + list unresolved review threads. Summarize in one line.
2. **CI failing?** Fetch the failing job's log tail (`gh run view <id> --log-failed`), diagnose, apply the minimal fix, run the matching local gate first (repo make target), commit per CONTRIBUTING.md, push. Never re-run a failed workflow without a fix unless the failure is demonstrably infra flake (say which evidence).
3. **CI stuck?** A job queued/in-progress beyond ~15 min with no log progress: `gh run rerun <id>` (note it in the cycle summary).
4. **Unresolved review comments?** If the repo defines a dedicated review-feedback command (e.g. `/resolve-pr`), run that flow for this cycle — it owns classification, line mapping, thread resolution, test policy, and commit standards; do not re-implement any of that here. Loop adjustment: this command runs autonomously, so don't block on the delegated command's interactive gates — apply fixes for actionable threads, and treat anything genuinely needing a human decision as this loop's "blocked → report and stop" exit, not a mid-loop prompt. **Fallback only** (repos with no such command): classify fix-vs-reply per comment; apply fixes with their tests; reply on the thread with what changed (commit SHA) and resolve it. Push once per cycle, not per comment.
5. **Blocked on a human?** (changes requested that need a product decision, failing required review, merge conflict against a moving base the user should rebase deliberately): stop the loop and report exactly what is needed.
6. **Wait:** pace the next check to the slowest pending signal (CI run duration), not a fixed short poll.

## Exit conditions

- Success: all required checks green, no unresolved threads, `reviewDecision` not `CHANGES_REQUESTED` → final summary and stop.
- Blocked: a step needs a human decision → report and stop.
- Never merge the PR yourself unless explicitly told to.

## Output

Per cycle: one status line (`checks 3/5 green, 2 threads open — fixed X, pushed <sha>`).
Final: what was fixed, commits pushed, threads resolved, current PR state.
