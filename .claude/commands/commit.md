---
description: Create atomic git commits for all working-tree changes with clear messages, following CONTRIBUTING.md conventions
allowed-tools: Bash(git status*), Bash(git diff*), Bash(git add*), Bash(git reset*), Bash(git commit*), Bash(git log*), Bash(gh auth*), Bash(gh api user*)
disable-model-invocation: true
---

You are tasked with creating git commits for all uncommitted changes in the working tree.

Commit message standards: @CONTRIBUTING.md §6 ("Conventions") is the single source of
truth for subject/body — imperative subject ≤ 72, body wrapped at 72, no emoji, no
`Co-Authored-by` or other attribution trailer. Follow that file; do not invent
additional rules.

## Process

### 1. Pre-flight — GitHub CLI account

Verify the `EXACT_GITHUB_USER` environment variable is set. If it is empty or unset,
inform the developer that `EXACT_GITHUB_USER` must be configured and **STOP**.

Record the currently active account so it can be restored afterward:

```bash
ORIGINAL_GH_USER=$(gh api user --jq .login 2>/dev/null)
```

Switch to the exact account:

```bash
gh auth switch -u "$EXACT_GITHUB_USER"
```

If the switch fails (e.g., account not found), inform the developer and **STOP** — they
need to run `gh auth login` first with the correct account. (Nothing was changed, so no
restore is needed on this path.)

### 2. Think about what changed

- Run `git status` to see current changes.
- If there are any **staged** files, run `git reset HEAD` to unstage them first — all changes should start unstaged so you can group them properly.
- Run `git diff` to understand the modifications.
- **Goal:** commit **ALL** unstaged and untracked files, except temporary/generated files.

### 3. Plan your commit(s)

- Group files that belong to the same logical unit of work.
- Ensure **every** relevant file is assigned to a commit group.
- Draft messages per the CONTRIBUTING.md §6 standards above.
- Focus on *why* the changes were made, not just *what*.

### 4. Execute

- **Iterate** through your planned logical groups:
  a. Use `git add` for the specific files in the current logical group (avoid `-A` or `.` to ensure precision).
  b. Run `git commit` with the drafted message via a HEREDOC (see repo commit rules). Pre-commit runs Ruff and the complexity gate — do not skip hooks.
- **Repeat** until **ALL** relevant changes have been committed.
- Verify with `git status` that the working directory is clean (excluding ignored/temporary files).
- Never commit secrets (`.env`), dummy files, test scripts, or other files you created (or that appear generated) that were not part of the intended change.

### 5. Restore GitHub CLI account

Restore the developer's original active account so global `gh` state is unchanged:

```bash
[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"
```

Always restore in this step, including on any post-switch failure path after Step 1 succeeded.

## Remember

- `gh auth switch` mutates **global** CLI state — always restore `$ORIGINAL_GH_USER` after Step 1 succeeded.
- Analyze the diffs to understand the intent behind each change.
- Group related changes together; keep commits focused and atomic.
- The user trusts your judgment — they asked you to commit.
- **This command is autonomous: never stop to ask the user for feedback mid-run.**
- **Never add a `Co-Authored-by` line or any attribution trailer** (CONTRIBUTING.md §6). Nothing rejects one mechanically, and a squash merge makes it permanent on `main`.
