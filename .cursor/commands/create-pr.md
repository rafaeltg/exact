---
description: Create a GitHub PR for the current branch with a generated title and description
disable-model-invocation: true
---

You are an expert developer tasked with creating a Pull Request for the current branch.

PR and commit standards are defined in @CONTRIBUTING.md — treat it as the single
source of truth (§6 "Conventions": one concern per PR, imperative subject ≤ 72
chars, no attribution byline; §5 CI when defined; §7 definition of done). Do not
invent standards not in that file.

## Process

### 1. Pre-flight Checks

Verify the `EXACT_GITHUB_USER` environment variable is set. If it is empty or unset,
inform the developer that `EXACT_GITHUB_USER` must be configured and **STOP**.

Detect the repository's default branch:

```bash
gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'
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

### 2. Switch GitHub CLI Account (and remember the original)

Record the currently active account so it can be restored afterward:

```bash
ORIGINAL_GH_USER=$(gh api user --jq .login 2>/dev/null)
```

Switch to the exact account:

```bash
gh auth switch -u "$EXACT_GITHUB_USER"
```

If the switch fails (e.g., account not found), inform the developer and **STOP** — they need to run `gh auth login` first with the correct account. (Nothing was changed, so no restore is needed on this path.)

### 3. Push Branch

Check if the branch has an upstream: `git rev-parse --abbrev-ref @{upstream} 2>/dev/null`

If no upstream exists, push with: `git push -u origin $BRANCH`

If upstream exists, check if local is ahead: `git status -sb`. If ahead, push: `git push`

### 4. Generate PR Content

- **Title:** Concise, imperative, ≤ 72 characters (matching the commit-subject rule in CONTRIBUTING.md §6). If the branch's commits use Conventional Commit prefixes, mirror that style; otherwise a plain imperative subject is correct.
- **Body:** Optimize for a reviewer scanning a PR list, not for someone reconstructing the change without reading the diff. **Summarize the commit messages — do not aggregate them.**
  - **Description** (1-3 sentences): what this PR does and why. Skip whatever the title already conveys. Write as one Markdown paragraph with no hard line breaks; let GitHub wrap long lines.
  - **Key Changes** (3-6 bullets total, each ≤ 1 line): high-level *outcomes*, not *implementation*.
  - **For multi-concern PRs:** prefer splitting (CONTRIBUTING.md §6: "one concern per PR"). If they genuinely belong together, use a single bold inline prefix per bullet (e.g. `**Test infra:** ...`).
  - **Ticket footer:** If a ticket/issue ID is derivable from the branch name or commits, include it in the footer.
  - **DO NOT include:** file paths, class/function names, exhaustive test inventories, line counts, or "added tests for X" bullets. The diff already shows these.
  - **No attribution byline.** Never end the body with "Generated with Claude Code", "Generated with Cursor", or any other tool credit, and never add a `Co-Authored-By` line (CONTRIBUTING.md §6).

### 5. Create the PR

Use `gh pr create` with a HEREDOC for the body:

```bash
gh pr create --title "the pr title" --body "$(cat <<'EOF'
## Description
[1-3 sentence summary as one paragraph with no hard line breaks]

## Key Changes
- [High-level outcome]
- [High-level outcome]
- [High-level outcome]
EOF
)" --assignee "$EXACT_GITHUB_USER"
```

### 6. Restore GitHub CLI Account & Report

Restore the developer's original active account so global `gh` state is unchanged:

```bash
[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"
```

Then display the PR URL to the developer.

## Remember

- `gh auth switch` mutates **global** CLI state — always restore `$ORIGINAL_GH_USER` in Step 6, including on any post-switch STOP path.
- Standards live in CONTRIBUTING.md; this command references them rather than duplicating them.
- **Never append an attribution byline to the PR body** — no tool credit, no `Co-Authored-By` (CONTRIBUTING.md §6). Nothing rejects one mechanically; the body is public the moment the PR is created.
