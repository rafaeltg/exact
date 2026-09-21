---
description: Create a GitHub PR for the current branch with a generated title and description
argument-hint: (no args; uses the current branch)
---

Run this workflow only when the user explicitly invokes `/create-pr`. This command takes no
arguments. Apply the repository standards stated below: one concern per PR, imperative subjects
of at most 72 characters, defined CI when present, and no attribution byline.

## Workflow

### 1. Pre-flight checks

Verify that `EXACT_GITHUB_USER` is set. If it is empty or unset, explain that it must be
configured and STOP.

Detect the default branch and record it as `DEFAULT_BRANCH`:

```bash
gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'
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

### 2. Switch the GitHub account

Record the active account:

```bash
ORIGINAL_GH_USER=$(gh api user --jq .login 2>/dev/null)
```

Switch to the exact account:

```bash
gh auth switch -u "$EXACT_GITHUB_USER"
```

If switching fails, explain that `gh auth login` is required and STOP. Nothing changed, so
there is no account to restore on this path.

### 3. Publish the branch

Check for an upstream:

```bash
git rev-parse --abbrev-ref @{upstream} 2>/dev/null
```

If there is no upstream, run `git push -u origin $BRANCH`. If an upstream exists, run `git status -sb`
and push with `git push` only when the local branch is ahead.

### 4. Generate the PR content

Create an imperative title of at most 72 characters. Mirror Conventional Commit prefixes when
the branch commits use them. Otherwise use a plain imperative subject.

Create a body with:

- A one-paragraph `## Description` of one to three sentences.
- A `## Key Changes` section with three to six one-line outcome bullets.
- A ticket footer when an issue ID is derivable from the branch or commits.

Summarize commit messages without aggregating them. Do not include file paths, symbol names,
exhaustive test inventories, line counts, or test-only bullets. Do not add attribution bylines.

### 5. Create the PR

Use `gh pr create` with a HEREDOC body and `--assignee "$EXACT_GITHUB_USER"`.

### 6. Restore the account and report the URL

After the account switch succeeds, always restore the original account, including every failure
or stop path after the switch:

```bash
[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"
```

Display the created PR URL after restoration.
