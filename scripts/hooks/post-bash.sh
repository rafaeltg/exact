#!/usr/bin/env bash
# scripts/hooks/post-bash.sh — PostToolUse(Bash) adapter: the complexity,
# specification and plan gates, for writes the Write/Edit hooks cannot see.
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
#   - Each probe asks "did this file change", not "did this command touch it".
#     A probe is cheap before the first edit of a session and buys nothing
#     after it; it is here for the former, not as a per-command test.
#
# Fails open on anything that is not a clean verdict from one of the three
# gates. Each one is authoritative at commit; none of them may freeze the
# session.

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

# ─── complexity ────────────────────────────────────────────────────────
# First, because this is the gate that must not be bypassed. A finding from a
# document gate below must never mask it.
if git -C "$proj" status --porcelain -- '*.py' 2>/dev/null | grep -q .; then
  if ! report="$(make -C "$proj" complexity-check 2>&1)"; then
    # Debt, or a broken guard? Only the gate's closing line proves the former.
    if printf '%s' "$report" |
      grep -qF 'complexity-check: the tree has over-budget functions'; then
      printf '%s\n' "$report" >&2
      exit 2
    fi
  fi
fi

# ─── specifications ────────────────────────────────────────────────────
# A shell write leaves the same trace a Write leaves: a changed file. Probe for
# it, so `cat >>` and `sed -i` cannot land a specification the gate never read.
# A specification path is one slug, so word splitting is safe here.
#
# One stamp per specification, because one shared stamp would mark every other
# changed specification as seen after the first check. Without a stamp at all, a
# half-edited specification reports on every shell command of every session,
# which teaches the agent to skip this hook's output. `post-spec.sh` renews the
# same file, so a write through that hook is not reported twice.
#
# The stamp is written before the gate runs: a write that lands while the gate
# reads must stay newer than the stamp, or it is never probed. Two writes inside
# one clock second still tie. That miss is quiet, never a false report, and the
# explicit gate run at the end of `/spec` and `/plan` is the one that decides.
mkdir -p "$proj/.test-reports" 2>/dev/null || true
for spec in $(git -C "$proj" status --porcelain -- docs/specs 2>/dev/null |
  sed -E 's/^...//; s/^.* -> //'); do
  [ -f "$proj/$spec" ] || continue
  stamp="$proj/.test-reports/spec-$(basename "$spec")"
  [ -f "$stamp" ] && [ ! "$proj/$spec" -nt "$stamp" ] && continue
  : >"$stamp" 2>/dev/null || true
  report="$(make -C "$proj" spec-check FILE="$proj/$spec" 2>&1)" && continue
  printf '%s' "$report" | grep -qE '^spec-check: [0-9]+ finding' || continue
  printf '%s\n' "$report" >&2
  exit 2
done

# ─── plans ─────────────────────────────────────────────────────────────
# The plan directory is gitignored, so git reports no change there. The stamp
# carries the same fact: the gate has seen these bytes. `make plan-init` opens
# it, and `post-plan.sh` renews it after each checked write.
#
# No stamp means no probe. A directory without one holds a delivered or older
# plan that this workflow never opened, and reporting its findings on every
# shell command would teach the agent to skip this hook's output.
#
# The check runs through `post-plan.sh` with the payload that hook expects, so
# both paths share one report filter and one stamp rule.
for plan in "$proj"/.claude/artifacts/plan/*/plan.md; do
  [ -f "$plan" ] || continue
  # The same two conditions `post-plan.sh` uses to renew the stamp. A predicate
  # it does not share would probe a plan whose stamp can never advance, and
  # report the same findings on every later shell command.
  [ -f "${plan%/plan.md}/.spec-plan-v1" ] || continue
  stamp="${plan%/plan.md}/.plan-checked"
  [ -f "$stamp" ] || continue
  [ "$plan" -nt "$stamp" ] || continue
  delegate="$(dirname "$0")/post-plan.sh"
  [ -x "$delegate" ] || continue
  printf '{"tool_input":{"file_path":"%s"}}' "$plan" | "$delegate"
  # 2 is that hook's findings verdict. Any other non-zero is a broken hook, and
  # reporting it as findings is the mistake this file's header names.
  [ "$?" -eq 2 ] && exit 2
done

exit 0
