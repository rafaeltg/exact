#!/usr/bin/env bash
# scripts/hooks/post-plan.sh — PostToolUse(Write|Edit) adapter: plan gate
# for a canonical write under `.claude/artifacts/plan/<topic>/plan.md`.
#
# The explicit `make plan-check` command is authoritative. This adapter only
# forwards findings after a write and fails open when the adapter or guard is broken.
#
# Two details the obvious one-liner gets wrong, both copied from post-bash.sh:
#   - `plan-check` prints findings on stdout. A hook that exits 2 hands the
#     agent stderr only, so the report has to be moved.
#   - A non-zero `make` means "references do not resolve" OR "the guard died".
#     Reporting the second as the first turns one traceback into a report on
#     every later plan write. Only the guard's own closing line may exit 2.
#
# Fails open on anything that is not a clean findings verdict: the report is
# advisory, and a broken advisory hook must not freeze the session.

set -u

input="$(cat)"

# Anchor where the siblings anchor: `.claude/settings.json` passes
# CLAUDE_PROJECT_DIR, and the guard's own `_repo_root()` prefers it.
proj="${CLAUDE_PROJECT_DIR:-}"
[ -z "$proj" ] && proj="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$proj" ] && proj="${PWD:-}"
[ -z "$proj" ] && exit 0
proj="${proj%/}"

command -v jq >/dev/null 2>&1 || exit 0
command -v make >/dev/null 2>&1 || exit 0

# Cursor afterFileEdit: file_path (top-level or tool_input).
# Claude / serena: tool_input.file_path or tool_input.relative_path.
f="$(printf '%s' "$input" | jq -r '
  .file_path
  // .tool_input.file_path
  // .tool_input.path
  // .tool_input.relative_path
  // empty
' 2>/dev/null)" || exit 0

[ -z "$f" ] && exit 0

case "$f" in
/*) ;;
*) f="$proj/$f" ;;
esac

case "$f" in
*/.claude/artifacts/plan/*/plan.md) ;;
*) exit 0 ;;
esac

[ -e "$f" ] || exit 0

report="$(make -C "$proj" plan-check FILE="$f" 2>&1)" && exit 0

# Findings, or a broken guard? Only the guard's closing line proves the former.
printf '%s' "$report" |
  grep -qE '^plan-check: [0-9]+ finding' || exit 0

printf '%s\n' "$report" >&2
exit 2
