#!/usr/bin/env bash
# scripts/hooks/post-spec.sh — advisory specification gate after a document write.
#
# A draft is valid during incremental authoring, but a malformed document must
# be visible immediately. The explicit Make targets and pre-commit gate remain
# authoritative. This adapter fails open when its dependencies are unavailable.

set -u

input="$(cat)"
proj="${CLAUDE_PROJECT_DIR:-}"
[ -z "$proj" ] && proj="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$proj" ] && proj="${PWD:-}"
[ -z "$proj" ] && exit 0
proj="${proj%/}"

command -v jq >/dev/null 2>&1 || exit 0
command -v make >/dev/null 2>&1 || exit 0

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
*/docs/specs/*.md) ;;
*) exit 0 ;;
esac

[ -e "$f" ] || exit 0
report="$(make -C "$proj" spec-check FILE="$f" 2>&1)" && exit 0
printf '%s' "$report" | grep -qE '^spec-check: [0-9]+ finding' || exit 0
printf '%s\n' "$report" >&2
exit 2
