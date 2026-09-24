---
description: Create atomic git commits for all working-tree changes with clear messages, following CONTRIBUTING.md conventions
---

You are executing the `/commit` workflow now. This command takes no arguments.
Apply the repository's commit subject and body conventions below. Do not invent additional rules.
Do not explain whether `/commit` was invoked; follow the workflow below.

## Workflow

### 1. Inspect the working tree

- Run `git status`.
- If files are staged, run `git reset HEAD` so all changes begin unstaged.
- Run `git diff`.
- Commit all relevant unstaged and untracked files, excluding temporary or generated files.

### 2. Group the changes

Group related files into logical commits. Assign every relevant file to one group. Draft a
message for each group that explains why the change was made.

Use imperative subjects of at most 72 characters, wrap bodies at 72 characters, and omit
emoji, `Co-Authored-by`, and other attribution trailers.

### 3. Create commits

For each logical group:

1. Run `git add` with the specific files. Never use `git add -A` or `git add .`.
2. Run `git commit` with the drafted message through a HEREDOC.
3. Let repository hooks run. Never skip hooks.
4. Repeat until every relevant change is committed.

Verify with `git status` that the working tree is clean, excluding ignored or temporary files.
Never commit secrets, dummy files, test scripts, or unintended generated files.

Report the final status.

This workflow is autonomous. Do not stop for feedback during execution.
