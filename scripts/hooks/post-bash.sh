#!/usr/bin/env bash
# scripts/hooks/post-bash.sh — PostToolUse(Bash) adapter: complexity gate for
# writes the Write/Edit pre-hook cannot see.
#
# `make complexity-pre` denies an over-budget edit before it reaches disk, but
# it only sees the Write/Edit tool payload. A shell redirect, `sed -i` or a
# heredoc writes Python without that payload. This hook closes the loop after
# the fact: the write already landed, so it reports instead of denying, and
# exit 2 puts the report in front of the agent that made it.
#
# Three details the obvious one-liner gets wrong:
#   - `complexity-check` prints violations on stdout. A hook that exits 2
#     hands the agent stderr only, so the report has to be moved.
#   - A non-zero `make` means "debt found" OR "the guard died". Reporting the
#     second as the first turns one merge conflict into a traceback on every
#     later shell command, because the probe below stays true until the file
#     parses again. Only the gate's own debt sentinel may exit 2.
#   - The probe asks "is any `.py` uncommitted", not "did this command touch
#     Python". It is free before the first Python edit of a session and buys
#     nothing after it; it is here for the former, not as a per-command test.
#
# Fails open on anything that is not a clean debt verdict. `make
# complexity-check` at commit is the gate that must not be bypassed; this one
# must not freeze the session.

set -u

# Anchor where the siblings anchor: `.claude/settings.json` passes
# CLAUDE_PROJECT_DIR to `complexity-pre`, and the guard's own `_repo_root()`
# prefers it. Deriving a different root here would measure one tree and
# report on another inside a linked worktree.
proj="${CLAUDE_PROJECT_DIR:-}"
[ -z "$proj" ] && proj="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$proj" ] && exit 0
proj="${proj%/}"

command -v make >/dev/null 2>&1 || exit 0

git -C "$proj" status --porcelain -- '*.py' 2>/dev/null | grep -q . || exit 0

report="$(make -C "$proj" complexity-check 2>&1)" && exit 0

# Debt, or a broken guard? Only the gate's closing line proves the former.
printf '%s' "$report" |
  grep -qF 'complexity-check: the tree has over-budget functions' || exit 0

printf '%s\n' "$report" >&2
exit 2
