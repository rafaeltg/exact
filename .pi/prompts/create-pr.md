---
description: Create a GitHub PR for the current branch with a generated title and description
argument-hint: (no args; uses the current branch)
---

Run this workflow only when the user explicitly invokes `/create-pr`. This command takes no
arguments. Apply the repository standards stated below: one concern per PR, imperative subjects
of at most 72 characters, defined CI when present, and no attribution byline.

## Workflow

### 1. Pre-flight checks

`EXACT_GITHUB_USER` names the account that creates the PR. Run every GitHub CLI call through
`scripts/gh-exact`, never bare `gh`. The wrapper uses the token of `EXACT_GITHUB_USER` for that one
process, so the global `gh` account never changes. If the first call fails with
"EXACT_GITHUB_USER is not set" or "gh has no token for …", explain that the variable must be set
or that `gh auth login` is required for that account, and STOP.

Detect the default branch and record it as `DEFAULT_BRANCH`:

```bash
scripts/gh-exact repo view --json defaultBranchRef --jq '.defaultBranchRef.name'
```

Run these checks in parallel:

- `git branch --show-current`, recorded as `BRANCH`.
- `git log --oneline $(git merge-base HEAD origin/$DEFAULT_BRANCH)..HEAD`, recorded as `COMMITS`.
- `git diff --stat $(git merge-base HEAD origin/$DEFAULT_BRANCH)..HEAD`, recorded as `DIFF_STAT`.
- `git status --short`, used to check for uncommitted changes.

If the merge base cannot be found, use `git log -n 10 --oneline` and `git diff --stat HEAD~10`.
If the current branch is `$DEFAULT_BRANCH`, explain that PRs cannot start from the default branch
and STOP. If there are uncommitted changes, warn the user and ask whether to proceed or stop.
Do not continue until the user confirms.

### 2. Publish the branch

Check for an upstream:

```bash
git rev-parse --abbrev-ref @{upstream} 2>/dev/null
```

If there is no upstream, run `git push -u origin $BRANCH`. If an upstream exists, run `git status -sb`
and push with `git push` only when the local branch is ahead.

### 3. Generate the PR content

Create an imperative title of at most 72 characters. Mirror Conventional Commit prefixes when
the branch commits use them. Otherwise use a plain imperative subject.

Create a body with:

- A one-paragraph `## Description` of one to three sentences.
- A `## Key Changes` section with three to six one-line outcome bullets.
- A ticket footer when an issue ID is derivable from the branch or commits.

Summarize commit messages without aggregating them. Do not include file paths, symbol names,
exhaustive test inventories, line counts, or test-only bullets. Do not add attribution bylines.

### 4. Create the PR

Use `scripts/gh-exact pr create` with a HEREDOC body and `--assignee "$EXACT_GITHUB_USER"`.

### 5. Report the URL

Display the created PR URL.
