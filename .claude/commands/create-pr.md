---
description: Create a GitHub PR for the current branch with a generated title and description
argument-hint: (no args; uses the current branch)
allowed-tools: Bash(git branch*), Bash(git log*), Bash(git diff*), Bash(git status*), Bash(git merge-base*), Bash(git rev-parse*), Bash(git push*), Bash(scripts/gh-exact repo view*), Bash(scripts/gh-exact pr create*)
disable-model-invocation: true
---

You are an expert developer tasked with creating a Pull Request for the current branch.

PR and commit standards are defined in @CONTRIBUTING.md — treat it as the single
source of truth (§7 "Conventions": one concern per PR, imperative subject ≤ 72
chars, no attribution byline; §6 CI when defined; §8 definition of done). Do not
invent standards not in that file.

## Process

### 1. Pre-flight Checks

`EXACT_GITHUB_USER` must name the account that creates the PR. **Every `gh` call runs through
`scripts/gh-exact`**, never bare `gh`. The wrapper sets `GH_TOKEN` to the token of
`EXACT_GITHUB_USER` for that one process, so the global `gh` account never changes. The first call
below checks the variable: it fails with "EXACT_GITHUB_USER is not set" or "gh has no token for …".
On that failure, inform the developer and **STOP**. They must set the variable or run
`gh auth login` for that account.

Detect the repository's default branch:

```bash
scripts/gh-exact repo view --json defaultBranchRef --jq '.defaultBranchRef.name'
```

Record the result as `DEFAULT_BRANCH` (e.g., `main`).

Then run these commands in parallel:

- `git branch --show-current` — record as `BRANCH`
- `git log --oneline $(git merge-base HEAD origin/$DEFAULT_BRANCH)..HEAD` — record as `COMMITS`
- `git diff --stat $(git merge-base HEAD origin/$DEFAULT_BRANCH)..HEAD` — record as `DIFF_STAT`
- `git status --short` — check for uncommitted changes

If the merge base cannot be found, fall back to `git log -n 10 --oneline` and `git diff --stat HEAD~10`.

**If the current branch is `$DEFAULT_BRANCH`:** Inform the developer and **STOP**. Do not create PRs from the default branch.

**If there are uncommitted changes:** Warn the developer and ask whether to proceed or stop. Do not proceed until they confirm.

### 2. Push Branch

Check if the branch has an upstream: `git rev-parse --abbrev-ref @{upstream} 2>/dev/null`

If no upstream exists, push with: `git push -u origin $BRANCH`

If upstream exists, check if local is ahead: `git status -sb`. If ahead, push: `git push`

### 3. Generate PR Content

- **Title:** Concise, imperative, ≤ 72 characters (matching the commit-subject rule in CONTRIBUTING.md §7). If the branch's commits use Conventional Commit prefixes, mirror that style; otherwise a plain imperative subject is correct.
- **Body:** Optimize for a reviewer scanning a PR list, not for someone reconstructing the change without reading the diff. **Summarize the commit messages — do not aggregate them.**
  - **Description** (1-3 sentences): what this PR does and why. Skip whatever the title already conveys. Write as one Markdown paragraph with no hard line breaks; let GitHub wrap long lines.
  - **Key Changes** (3-6 bullets total, each ≤ 1 line): high-level *outcomes*, not *implementation*.
  - **For multi-concern PRs:** prefer splitting (CONTRIBUTING.md §7: "one concern per PR"). If they genuinely belong together, use a single bold inline prefix per bullet (e.g. `**Test infra:** ...`).
  - **Ticket footer:** If a ticket/issue ID is derivable from the branch name or commits, include it in the footer.
  - **DO NOT include:** file paths, class/function names, exhaustive test inventories, line counts, or "added tests for X" bullets. The diff already shows these.
  - **No attribution byline.** Never end the body with "Generated with Claude Code", "Generated with Cursor", or any other tool credit, and never add a `Co-Authored-By` line (CONTRIBUTING.md §7).

### 4. Create the PR

Use `scripts/gh-exact pr create` with a HEREDOC for the body:

```bash
scripts/gh-exact pr create --title "the pr title" --body "$(cat <<'EOF'
## Description
[1-3 sentence summary as one paragraph with no hard line breaks]

## Key Changes
- [High-level outcome]
- [High-level outcome]
- [High-level outcome]
EOF
)" --assignee "$EXACT_GITHUB_USER"
```

### 5. Report

Display the PR URL to the developer.

## Remember

- Standards live in CONTRIBUTING.md; this command references them rather than duplicating them.
- **Never append an attribution byline to the PR body** — no tool credit, no `Co-Authored-By` (CONTRIBUTING.md §7). Nothing rejects one mechanically; the body is public the moment the PR is created.
