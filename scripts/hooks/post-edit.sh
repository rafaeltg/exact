#!/usr/bin/env bash
# scripts/hooks/post-edit.sh — PostToolUse(Write|Edit) adapter: stdin JSON → make lint-fix FILE=.
#
# Claude Code hooks only get a static command string. The edited path
# arrives in the stdin payload, so this thin shell bridges payload → Make.
# Same shape as pipeline-engine's post-edit.sh, scoped to Python only.
#
# Fails open: missing jq/make/path → exit 0. A broken hook must not freeze edits.

set -u

input="$(cat)"

proj="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$proj" ] && proj="${PWD:-}"
[ -z "$proj" ] && exit 0
proj="${proj%/}"

command -v jq >/dev/null 2>&1 || exit 0
command -v make >/dev/null 2>&1 || exit 0

# Claude Code: tool_input.file_path. serena: tool_input.relative_path.
# `post-bash.sh` sends tool_input.file_path. The other keys are fallbacks.
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

[ -e "$f" ] || exit 0

case "$f" in
*.py | *.pyi)
  make -C "$proj" lint-fix FILE="$f" >/dev/null 2>&1 || true
  ;;
esac

exit 0
