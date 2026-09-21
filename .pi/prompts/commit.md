---
description: Create atomic git commits for all working-tree changes with clear messages, following CONTRIBUTING.md conventions
---

You are executing the `/commit` workflow now. This command takes no arguments.
Apply the repository's commit subject and body conventions below. Do not invent additional rules.
Do not explain whether `/commit` was invoked; follow the workflow below.

## Workflow

### 1. GitHub account pre-flight

Verify that `EXACT_GITHUB_USER` is set. If it is empty or unset, explain that it must be
configured and STOP.

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

### 2. Inspect the working tree

- Run `git status`.
- If files are staged, run `git reset HEAD` so all changes begin unstaged.
- Run `git diff`.
- Commit all relevant unstaged and untracked files, excluding temporary or generated files.

### 3. Group the changes

Group related files into logical commits. Assign every relevant file to one group. Draft a
message for each group that explains why the change was made.

Use imperative subjects of at most 72 characters, wrap bodies at 72 characters, and omit
emoji, `Co-Authored-by`, and other attribution trailers.

### 4. Create commits

For each logical group:

1. Run `git add` with the specific files. Never use `git add -A` or `git add .`.
2. Run `git commit` with the drafted message through a HEREDOC.
3. Let repository hooks run. Never skip hooks.
4. Repeat until every relevant change is committed.

Verify with `git status` that the working tree is clean, excluding ignored or temporary files.
Never commit secrets, dummy files, test scripts, or unintended generated files.

### 5. Restore the GitHub account

After the account switch succeeds, always restore the original account, including every failure
path after the switch:

```bash
[ -n "$ORIGINAL_GH_USER" ] && gh auth switch -u "$ORIGINAL_GH_USER"
```

Report the final status after restoration.

This workflow is autonomous. Do not stop for feedback during execution.
