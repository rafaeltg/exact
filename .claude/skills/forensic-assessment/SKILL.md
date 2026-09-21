---
name: forensic-assessment
description: >-
  Six-dimension rubric to assess an existing document, spec, config, schema, or instruction
  file: factual correctness, completeness, internal and external consistency,
  production-readiness, standards compliance. Use for a single-pass check in chat: "is this
  correct", "is this production-ready", "find the gaps in this doc", "check this config against
  reality", "are these findings valid". /forensic-review runs the parallel version. Not for:
  code diffs (python-quality, test-design); pressure-testing an idea (/devils-advocate); bugs in
  running code (/bug-bash).
---

# Forensic Assessment

The methodology for verifying an existing artifact against reality: what claims does it make, are they true, what's missing, does it contradict itself, and does it hold up under real conditions. This skill is the "brain" — the six-dimension rubric, depth calibration, evidence standard, and severity taxonomy. It has no orchestration logic of its own.

**Primary caller:** `/forensic-review` — that command owns fan-out (parallel assessment agents), synthesis, citation verification, and the report format. It inlines this skill's rubric into each agent's context rather than telling agents to load it at runtime (the same choice `/bug-bash` makes for its own confidence-bar text).

**Secondary use:** load this skill directly for a quick, single-pass assessment in conversation — e.g. "is this YAML config correct" — when spinning up the full command's parallel pipeline would be overkill. Use the depth-calibration table below to decide. Render findings inline in chat using the FINDINGS_REPORT structure's `### Findings` shape (location/evidence/issue/recommendation per finding) without writing a file — the `.claude/artifacts/forensic-review/` file write is `/forensic-review`'s job, not this skill's.

## The six dimensions

Load `references/assessment-methodology.md` for the full checklist per dimension. Summary:

1. **Factual correctness** — do claims match reality? Versions, tool names, config values, behavioral assertions, structural claims (does the described directory/module actually exist?) — verify each against its canonical source.
2. **Completeness** — what's missing that should be covered? Missing sections, suspiciously thin sections, undocumented conventions visible in the real system but absent from the artifact, missing edge cases.
3. **Internal consistency** — does the artifact contradict itself? Terminology drift, contradictory rules across sections, stale sections describing an old version, examples that don't match the rule they illustrate.
4. **External consistency** — does the artifact match the systems it describes? Code divergence, cross-doc divergence, API contract mismatch, integration points that don't actually exist as described.
5. **Production-readiness** — would this survive real conditions? Failure modes, operational concerns (monitoring/rollback/scaling), security boundaries, data integrity, performance bounds. Only apply where relevant (architecture/deployment/API artifacts) — do not assess a meeting-notes doc for failure modes.
6. **Standards compliance** — does it follow its own stated conventions, or the project's (`AGENTS.md`), or an external standard it claims to follow (RFC, OWASP)? Internal-convention claims are verified against the codebase; external-standard claims need outside documentation.

## Evidence standard

No finding without evidence. Quote both the claim and the reality: *"Artifact says X (line 12), but the actual value is Y (`pyproject.toml:7`)."* A finding with a paraphrase instead of a verbatim quote is not a finding.

## Depth calibration

| Artifact complexity | Assessment depth |
|---|---|
| Trivial (< 30 lines, single concern) | Dimensions 1 and 2 only. Skip if nothing surfaces. |
| Moderate (30–200 lines, multi-section) | All 6 dimensions, one pass each. |
| Complex (> 200 lines, cross-cutting) | All 6 dimensions, multiple passes; cross-reference reads mandatory. |
| Multi-source comparison | Dimension 4 (external consistency) dominates; others as needed. |

Do not generate 40 findings for a trivial artifact. Scaling depth to complexity is part of the methodology, not an afterthought.

## Severity taxonomy and output formats

Load `references/output-formats.md` for the exact FINDINGS_REPORT / PATCH_PLAN shapes, the severity table (Critical / Major / Minor / Nit), and the patch action vocabulary (Add / Remove / Rewrite / Restructure / Update / Reconcile).

## Anti-patterns

Named failure modes to actively avoid — if you catch yourself doing one, stop and correct:

- **Shallow listing** — "could be improved" with no quote and no specific recommendation.
- **Scope creep** — flagging the artifact for not covering something it never claimed to cover. Distinguish "this is wrong" (finding) from "this is claimed but underspecified" (gap finding) from "wouldn't it be nice if it also covered X" (out of scope — omit).
- **Unlinked findings/patches** — a patch that doesn't trace back to a specific finding number; the reader can't evaluate or reject it individually.
- **Fabricated evidence** — citing a line or quote without having actually read it. If you haven't read it, read it first.
- **Over-generating for trivial artifacts** — a 10-line config does not need 30 findings. "No significant findings" is a valid, complete outcome.

## Input framing (for callers)

Four shapes this methodology handles differently — a caller should identify which applies before assessing:

- **Standard review** — one artifact, full dimension sweep.
- **Cross-source comparison** — two or more sources; findings are framed as divergence ("source A says X, source B says Y"), not absolute correctness.
- **Findings meta-review** — the input is a previous findings report, not the artifact itself. Assess each finding's *validity* (valid / invalid / partially valid), not the artifact directly.
- **Re-review after changes** — the artifact was already patched. Focus on: are the patches correct, did they introduce new issues, do they address the original findings.
