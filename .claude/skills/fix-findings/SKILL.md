---
name: fix-findings
description: >-
  Re-verifies each finding of a defect report against the current code, writes a patch plan, and
  applies the fixes uncommitted. Use when the user asks to fix findings that each cite a file
  and a checkable defect: .claude/artifacts/bug-bash/*, .claude/artifacts/review-pr/* dry-run
  reports, or pasted audit output. Not for: producing findings (/bug-bash, /review-pr);
  arguments that an idea is unsound (harden-doc); forensic-review reports (its own Phase 7);
  brainstorm reports; GitHub PR review comments, even when pasted (/babysit-pr); asking whether
  findings are valid (/forensic-review).
allowed-tools: Read, Glob, Grep, Write, Edit, Bash(date*), Bash(mkdir*), Bash(git status*), Bash(git diff*), Bash(git merge-base*), Bash(make test*), Bash(make workflows-check*), Bash(rtk proxy make*)
---

# Fix Findings

Turn a defect report into a verified patch plan, then apply it. Findings reports go stale
and contain false positives; **never fix a finding you have not re-verified against the
current code.**

This skill always executes the plan it writes — the plan is a specification, not a proposal.
That is safe only because every finding here asserts something checkably wrong in a named
place. When a "fix" is a judgment call instead — a design tradeoff, a new constraint, an
alternative worth weighing — it is a decision for the user, not a fix. When such findings
review a document (a `/devils-advocate` report), `harden-doc` runs that decision flow. A
report that mixes both kinds (a `/review-pr dry-run` report's `## Approach` section, a
"consider …" recommendation) is handled by classifying each finding in step 1: this skill
executes the defects and returns the judgment calls to the user.

## Inputs

- `REPORT`: path(s) to the findings report(s), or the pasted findings text. Required — if
  missing, ask.
- **Load only on an explicit request to fix.** A question about a report is not a request to
  fix it. Answer the question; do not enter the steps below.
- `SUBJECT`: what the fixes apply to — **never the report itself**. Each finding's own
  `file:line` is the target. The report's header bounds what may be touched:
  - `**Scope:**` (bug-bash) — bounds the code that may be touched; a code finding pointing
    outside that path is reported, not silently applied. A `documentation` finding names a
    doc outside the scan scope by construction — the doc-vs-code agent compares docs against
    the scanned code — and is in bounds.
  - `**Repo:**` + `**Head SHA:**` (review-pr dry-run) — the report is pinned to a commit.
    Before verifying anything, run `git merge-base --is-ancestor <Head SHA> HEAD`. If it
    fails, **STOP** and name the PR whose head must be checked out (the `pr<PR>` in the
    report filename); on the wrong branch every finding verifies as STALE or mislocates, and
    both outcomes are wrong.
  - If a finding names no path and none can be resolved, mark it `UNLOCATABLE` and treat it
    like REJECTED — do not guess.
- Commit policy: **never commit or push.** The result is an uncommitted working-tree diff
  that the user reviews and commits with `/commit`. That diff is their only rollback point,
  so this rule is not optional. Nothing enforces it mechanically — the `allowed-tools` list
  above pre-approves, it does not restrict — so hold it as a rule.

## Steps

1. **Enumerate.** Read `REPORT` fully. Build a checklist:
   `id | file:line | claim | severity | class`. Count the entries; the final summary must
   account for every one.

   `class` is one of:
   - `defect` — names a place and asserts something checkably wrong there. Bug-bash findings
     and review-pr inline findings are this by construction.
   - `judgment` — argues for a different choice rather than a correction: a review-pr
     `## Approach` note (`A1`, `A2`, …), a "consider …" or "it would be cleaner to …"
     recommendation, anything whose *claim* is that a design decision is wrong. These are
     never executed here. They go straight to the excluded table in step 3 as
     `NEEDS DECISION`.

   `class` is decided by the finding's claim, not by the wording of its proposed `**Fix:**`.
   A defect whose proposed fix would reverse a design decision is still a defect: confirm it,
   and plan a fix that does not.

2. **Verify each `defect` finding against the current code or prose.** Use Grep/Glob/Read to
   locate the cited location, then compare it to the claim. Mark each finding:
   - `CONFIRMED` — evidence: an excerpt of the current state.
   - `STALE` — already fixed; cite the current state that shows it.
   - `REJECTED` — false positive; give a one-line refutation.

   Only CONFIRMED findings proceed.

3. **Write the patch plan** to `.claude/artifacts/fix-findings/<TIMESTAMP>-<slug>.md`, where
   `TIMESTAMP` is `date -u +%Y%m%d-%H%M%S` and `<slug>` is the report's filename stem — join
   several with `+`; use `pasted` for pasted text (create the directory if it does not
   exist). For each confirmed finding record:
   - Root cause, in one sentence.
   - The exact change: file, symbol, and a before → after description precise enough to
     execute without re-deriving the intent.
   - **The complexity budget.** `make complexity-pre` denies any `Write`/`Edit` that creates a
     new or worse breach vs HEAD (`AGENTS.md` § Complexity budgets). If the fix grows a
     function, name the repair now — a branch removed, an early return, a responsibility
     moved to a named unit — in the `AGENTS.md` repair order. Do not discover it at write
     time.
   - The test to add or update, and what it asserts. Tests pair with fixes; a code fix with
     no test is incomplete unless the item says why.
   - The verification gate for the touched files, from this table and no other source:

     | Touched path | Gate |
     | --- | --- |
     | `src/exact/**/*.py`, `tests/**` | `rtk proxy make test TEST=<the test file the item names>` per item; `rtk proxy make check` once after the last item |
     | `.claude/hooks/*.py` | `rtk proxy make test TEST=tests/test_complexity_guard.py` per item; `rtk proxy make check` once after the last item (lint, format and complexity cover this path) |
     | `.claude/workflows/*.js` | `make workflows-check` — if it prints `WARNING: node not on PATH`, report the gate as not run, never as passed |
     | anything else (`docs/**`, `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, `.claude/**/*.md`, `Makefile`, `pyproject.toml`, `scripts/**`, config files) | "no gate covers this file" |

     Do not invent a command outside that table.

   Order the items so the tree stays valid after every one. Add the excluded table at the
   bottom — one row per STALE, REJECTED, UNLOCATABLE and NEEDS DECISION finding with its
   one-line reason — so that no finding disappears silently.

4. **Execute the plan.** Work item by item, in plan order. Load `python-quality` for the code
   change and `test-design` for the paired test. Touch only what the confirmed finding
   requires.

   A denied `Write`/`Edit` from `make complexity-pre` is not a reason to skip the item. Apply
   the `AGENTS.md` repair order and write again. Never park a breach.

   Run every `make` gate through `rtk proxy` and judge it from that output only — the RTK
   hook filters `make` output, and a filtered run can render as "No tests collected" when
   the suite actually ran. After the last item, run `rtk proxy make check`. If no gate covers
   what was touched, report that — never substitute reasoning for a gate.

   If no finding is CONFIRMED, write the plan with its excluded table, execute nothing, and
   say so.

5. **Report.** Print the plan path, the counts (confirmed / stale / rejected / unlocatable /
   needs-decision / fixed), the title of every NEEDS DECISION item, and the verification
   results. Do not print the plan body.

## Output

- `.claude/artifacts/fix-findings/<timestamp>-<slug>.md` — the plan (gitignored, like every
  artifact under `.claude/artifacts/`).
- The applied fixes, as an uncommitted working-tree diff.
- Terminal: a one-line summary, the paths, the NEEDS DECISION titles, and pass/fail per gate.

## Guardrails

- **The report is a read-only input.** Never edit it to mark findings handled. Anchor
  quotes appear in both the report and the subject, so a search for one matches both —
  the match inside `.claude/artifacts/` is never the fix target.
- No speculative fixes: touch only what a confirmed finding requires.
- A finding with no reproducible failure scenario gets verified harder, not skipped.
- A `judgment` finding is never executed, however small the change looks. It is returned to
  the user as NEEDS DECISION; `harden-doc` handles the equivalent for document reviews.
- If two findings conflict, record the conflict in the plan, skip those items during
  execution, and report them as needing a decision. Do not choose silently.
