#!/usr/bin/env bash
# scripts/hooks/post-plan.sh — PostToolUse(Write|Edit) adapter: plan gate
# for a canonical write under `.claude/artifacts/plan/<topic>/plan.md`.
#
# The explicit `make plan-check` command is authoritative. This adapter only
# forwards findings after a write and fails open when the adapter or guard is
# broken. It drops the two findings every incremental plan write produces.
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

# The gate has seen these bytes. `post-bash.sh` reads this stamp, so a plan
# written through the shell is checked once and a Write is not checked twice.
# Only a directory `make plan-init` opened is stamped: stamping an older plan
# would open it to that probe, and its findings are not this workflow's to fix.
#
# Written first, as `post-spec.sh` writes its own: a write that lands while the
# gate reads must stay newer than the stamp, or that write is never probed.
[ -f "${f%/plan.md}/.spec-plan-v1" ] &&
  { : >"${f%/plan.md}/.plan-checked" 2>/dev/null || true; }

report="$(make -C "$proj" plan-check FILE="$f" 2>&1)"

# Findings, or a broken guard? Only the guard's closing line proves the former.
total="$(printf '%s\n' "$report" |
  sed -nE 's/^plan-check: ([0-9]+) finding.*/\1/p')"
[ -z "$total" ] && exit 0

# `/plan` writes the head, then one Edit per phase, so a phase that holds no
# task, and a requirement no task cites yet, are the expected state between two
# writes. Reporting them trains the agent to read this hook's output as noise,
# and "repair it" reads as "cite that requirement somewhere", which corrupts
# the coverage data. The explicit `make plan-check` still reports all three,
# and that run is the one that gates the review.
INCOMPLETE='^(phase [1-9][0-9]* has no task|last phase has no task'
INCOMPLETE="$INCOMPLETE"'|active requirement R[1-9][0-9]* has no task)$'
expected="$(printf '%s\n' "$report" |
  grep -cE "$INCOMPLETE")"
[ "$total" -gt "$expected" ] || exit 0

printf '%s\n' "$report" |
  grep -vE "$INCOMPLETE" |
  sed -E "s/^plan-check: [0-9]+ finding/plan-check: $((total - expected)) finding/" >&2
exit 2
