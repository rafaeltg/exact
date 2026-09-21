---
name: harden-doc
description: >-
  Gets a user decision on each finding of an advisory document review, then edits the document
  to carry the accepted ones, uncommitted. Use when acting on a
  .claude/artifacts/devils-advocate/* report, or any review whose findings argue that an idea is
  unsound, not that a fact is wrong. Not for: findings that cite a checkable error
  (fix-findings); forensic-review reports (its own Phase 7); producing the review
  (/devils-advocate); brainstorm reports (feed the ★ pick to /devils-advocate).
---

# Harden Doc

Turn an advisory review into decisions, then carry those decisions into the reviewed
document. A devil's-advocate finding is not a defect to be corrected; it is an argument
that something may be unsound. It cannot be verified true or false against the code, and
**the decision to accept or reject it is always the user's, never yours.**

This skill decides before it edits. That is its whole difference from `fix-findings`, which
always executes because its findings are checkably wrong. Here, an accepted finding often
means a new constraint or a reversed choice — so acceptance can change the graph contract,
and silent execution would be writing architecture on the user's behalf.

## Inputs

- `REPORT`: path to the review report. Required — if missing, ask.
- `SUBJECT`: the reviewed document, read from the report's `**Source:**` header — the only
  place most reports name it. Findings are anchored by verbatim quotes, not paths, so
  resolve `SUBJECT` first and treat every accepted change as landing there.
  - The anchor quote appears in both the report and `SUBJECT`; a search matches both. The
    match inside `.claude/artifacts/` is never the edit target.
  - If `Source:` is `inline`, there is no document on disk. Produce the decisions and stop;
    ask where they should be recorded.
- Commit policy: **never commit or push.** The user reviews the diff and commits with
  `/commit`.

## Steps

1. **Read the report fully and state the shape of it.** Record the verdict
   (`solid` / `harden` / `rework`), the counts per severity, and the lenses that
   contributed. Build a table: `id | severity | title | lens`. The report restarts its
   numbering in every section, so `id` is `<section-key>-<N>` (`premise-1`, `failure-1`,
   `operational-2`, …), and `lens` is the section's lens unless the finding's
   `_Flagged independently by_` line names several.

   **If the verdict is `rework`, say so before doing anything else.** That verdict means
   the criticals are numerous or spread across many lenses — evidence that the design needs
   rethinking, not patching. Working through such a report finding by finding can produce a
   document that answers every objection and still describes the wrong system. Recommend
   the rethink; continue only if the user chooses to.

2. **Present the findings for decision, worst first.** The report itself says to address
   critical severity before implementation, so triage in that order. For each finding show
   the title, the argument, and the suggested change, compactly enough to decide from.

   Group the decision by severity tier rather than asking about fourteen findings one at a
   time. Offer, per tier: accept all, choose individually, defer all. Accept free-text
   answers naming ids.

   **Never infer a decision.** An unanswered finding is deferred, not accepted.

3. **Check each accepted finding for a contract change it implies.** exact has no ADR
   ledger; the contract is `docs/spec.md` and `docs/architecture.md`, and `AGENTS.md` fixes
   the rule for changing it: topology, bounds, tools and citation rules change in those two
   files in the same change as the code. Before editing, ask three questions of each
   accepted finding:

   - **Does it change topology, a bound, a tool, or a citation rule?** Then it is a change
     to the graph contract. If `SUBJECT` is a `docs/plans/*.md`, land the decision in the
     plan — body and locked-decisions section — and confirm the plan's own docs-update step
     names `docs/spec.md` and `docs/architecture.md` (`AGENTS.md`; `CONTRIBUTING.md` §6
     "Docs"). Do not edit `docs/spec.md` or `docs/architecture.md` ahead of the code they
     describe. Edit them directly only when `SUBJECT` is one of them, and then tell the user
     that the code must follow in the same change.
   - **Does it loosen a bound in `AGENTS.md` § Bounds?** Do not apply it. Those bounds carry
     "do not loosen". Report it as a decision the user takes in `AGENTS.md` itself, and leave
     the finding deferred until they do.
   - **Does it reverse an entry in the document's `Locked decisions` section?** Most
     `docs/plans/*.md` carry one (`## 2. Locked decisions`; `user-preferences.md` calls it
     `## 3. Locked taxonomy`). When the section exists, edit that entry, not only the body.
     A locked list that disagrees with the body it locks is worse than no list.

   These are decisions about the system, not edits to a file. Confirm them with the user
   before writing.

4. **Apply the accepted findings to `SUBJECT`.** Write the substance of the decision, not a
   reference to the review — a reader must never need the report to understand the
   document. Match the document's existing voice and structure; put each change where the
   topic already lives rather than appending a section of patches. Keep every edit
   traceable to an accepted finding id in your summary.

5. **Record the rejections in `SUBJECT`.** One line each, stating the reasoning, in a
   section titled `Ideas considered and rejected`, numbered like the document's other
   sections — create it when absent (`docs/plans/user-preferences.md` §9 is the precedent).
   This is what the report asks for, and it is what stops the next review from raising the
   same finding again. A rejection recorded only in this session is a rejection that will be
   re-litigated.

   Deferred findings are *not* recorded this way. They stay open, and belong in the summary
   only.

6. **Report.** Give the counts (accepted / rejected / deferred), what changed in `SUBJECT`,
   which contract changes the plan's docs-update step now carries (or which contract
   documents changed, when `SUBJECT` was one of them), and the deferred list. Do not print
   the document.

## Output

- `SUBJECT`, edited: accepted findings incorporated, rejections recorded with reasoning.
- `docs/spec.md` and `docs/architecture.md`, edited only when `SUBJECT` is one of them;
  otherwise the plan's docs-update step, confirmed to name both.
- All of it uncommitted, for the user to review.

## Guardrails

- **Every accept and reject is the user's call.** This skill has no authority to decide
  that an argument about the system is right.
- **The report is a read-only input.** Never edit it to mark findings handled.
- **An accepted finding that changes the contract is not done until the contract will
  follow.** A plan plus its spec/architecture update step, or spec plus architecture plus
  the code change — never the spec alone, and never the spec ahead of the code.
- Do not weaken a finding to make it easy to accept. If the honest change is large, say
  that it is large and let the user defer it.
- If two accepted findings conflict, stop and surface the conflict. Do not reconcile them
  silently — the reconciliation is itself a decision.
