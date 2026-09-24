---
description: Create atomic git commits for all working-tree changes with clear messages, following CONTRIBUTING.md conventions
allowed-tools: Bash(git status*), Bash(git diff*), Bash(git add*), Bash(git reset*), Bash(git commit*), Bash(git log*)
disable-model-invocation: true
---

You are tasked with creating git commits for all uncommitted changes in the working tree.

Commit message standards: @CONTRIBUTING.md §7 ("Conventions") is the single source of
truth for subject/body — imperative subject ≤ 72, body wrapped at 72, no emoji, no
`Co-Authored-by` or other attribution trailer. Follow that file; do not invent
additional rules.

## Process

### 1. Think about what changed

- Run `git status` to see current changes.
- If there are any **staged** files, run `git reset HEAD` to unstage them first — all changes should start unstaged so you can group them properly.
- Run `git diff` to understand the modifications.
- **Goal:** commit **ALL** unstaged and untracked files, except temporary/generated files.

### 2. Plan your commit(s)

- Group files that belong to the same logical unit of work.
- Ensure **every** relevant file is assigned to a commit group.
- Draft messages per the CONTRIBUTING.md §7 standards above.
- Focus on *why* the changes were made, not just *what*.

### 3. Execute

- **Iterate** through your planned logical groups:
  a. Use `git add` for the specific files in the current logical group (avoid `-A` or `.` to ensure precision).
  b. Run `git commit` with the drafted message via a HEREDOC (see repo commit rules). Pre-commit runs `make lint-fix` and `make complexity-check` — do not skip hooks.
- **Repeat** until **ALL** relevant changes have been committed.
- Verify with `git status` that the working directory is clean (excluding ignored/temporary files).
- Never commit secrets (`.env`), dummy files, test scripts, or other files you created (or that appear generated) that were not part of the intended change.

## Remember

- Analyze the diffs to understand the intent behind each change.
- Group related changes together; keep commits focused and atomic.
- The user trusts your judgment — they asked you to commit.
- **This command is autonomous: never stop to ask the user for feedback mid-run.**
- **Never add a `Co-Authored-by` line or any attribution trailer** (CONTRIBUTING.md §7). Nothing rejects one mechanically, and a squash merge makes it permanent on `main`.
