# Assessment Methodology

Systematic verification framework for forensic artifact assessment.

## Reading strategy

1. **Full sequential read.** Read the artifact from top to bottom without skipping. Note structural issues (missing sections, inconsistent heading hierarchy, orphaned references) during this pass.
2. **Cross-reference identification.** List every external source the artifact depends on: code it describes, docs it references, systems it integrates with, standards it claims to follow.
3. **Cross-reference reads.** Read each external source. For large codebases, read the specific files/sections the artifact claims to describe rather than the entire codebase.
4. **Dimension-by-dimension assessment.** Apply each dimension below. Do not mix dimensions in a single finding — a factual error is not the same as a completeness gap.

## The six dimensions

### 1. Factual correctness

For every verifiable claim in the artifact:

- **Version claims.** Check the canonical dependency manifest (`pyproject.toml`, `package.json`, `go.mod`, lockfiles) for exact versions. "We use Python 3.11" is either true or false.
- **Tool and library claims.** Verify the tool exists in the project and is used as described. "We lint with ruff" — check `pyproject.toml` and CI config.
- **Configuration claims.** Check actual config files. "Line length is 100" — read the real linter/formatter config.
- **Behavioral claims.** "The service retries 3 times" — read the retry logic in the actual code. Quote the implementation.
- **Structural claims.** "The project has a services/ layer" — list the actual directory. Flag phantom directories (described but don't exist) and orphan directories (exist but aren't described).

**Evidence standard:** quote both the claim and the reality. "Artifact says X (line 12), but the actual value is Y (`pyproject.toml:7`)."

### 2. Completeness

After verifying what IS described, scan for what SHOULD be but ISN'T:

- **Missing sections.** For the artifact type, what sections are standard but absent? A deployment doc without rollback procedures. An API spec without error responses.
- **Thin sections.** Sections that exist but are suspiciously brief. A "Security" section that says "JWT authentication is used" and nothing else.
- **Undocumented conventions.** Patterns visible in the code that aren't captured in the artifact. If every service uses constructor injection but the doc doesn't mention it, that's a gap.
- **Missing edge cases.** For specs and designs: what happens when input is empty, null, oversized, malformed, concurrent, or timed out?

**Judgment call:** not every omission is a finding. An artifact's scope is finite. Flag gaps only when the omission would mislead a reader or cause implementation errors.

### 3. Internal consistency

Does the artifact contradict itself?

- **Terminology drift.** The same concept called different names in different sections ("pipeline" vs "workflow" vs "job" for the same thing).
- **Contradictory rules.** Section A says "always use UUIDs" but section B's example uses integer IDs.
- **Stale sections.** A section that describes an old version of the system while the rest describes the current version.
- **Example-rule mismatch.** The prose says one thing, the code example shows another.

### 4. External consistency

Does the artifact match the systems it describes?

- **Code divergence.** The spec describes behavior X, but the code implements behavior Y. Quote both.
- **Cross-doc divergence.** This doc says one thing, a referenced doc says another.
- **API contract mismatch.** The spec describes endpoints, parameters, or responses that don't match the actual API (OpenAPI spec, route definitions, running behavior).
- **Integration point accuracy.** For every described external service interaction, verify the client code exists and behaves as described.

### 5. Production-readiness

Would this artifact (and the system it describes) survive real-world conditions?

- **Failure modes.** Are error scenarios addressed? What happens when dependencies are unavailable?
- **Operational concerns.** Monitoring, alerting, logging, rollback, scaling — covered where relevant?
- **Security boundaries.** Authentication, authorization, input validation, secret management.
- **Data integrity.** Backup, migration, consistency guarantees.
- **Performance bounds.** Implicit assumptions about data volume, request rate, response time.

Only apply this dimension to artifacts where production-readiness is relevant (architecture docs, deployment specs, API designs). Do not assess a meeting-notes doc for failure modes.

### 6. Standards compliance

Does the artifact follow its own stated standards, this project's conventions, or industry conventions for its type?

- **Project conventions.** Does the artifact follow this repo's `AGENTS.md` (or the nearer directory-scoped `AGENTS.md`)?
- **Industry standards.** RFC compliance for API specs, OWASP for security docs. Verifying these requires outside documentation, not just the codebase.
- **Format conventions.** Markdown structure, heading hierarchy, link validity, code block syntax.

## Depth calibration

| Artifact complexity | Assessment depth |
|---|---|
| Trivial (< 30 lines, single concern) | Dimensions 1 and 2 only. Skip if no issues found. |
| Moderate (30–200 lines, multi-section) | All 6 dimensions, one pass each. |
| Complex (> 200 lines, cross-cutting) | All 6 dimensions, multiple passes. Cross-reference reads mandatory. |
| Multi-source comparison | Dimension 4 (external consistency) dominates. Others as needed. |
| Findings meta-review | Depth calibration does not apply — assess every finding's validity regardless of the report's length; a short report still needs full per-finding judgment. |
| Re-review after changes | Same trivial/moderate/complex bucketing as a standard review, by the artifact's own line count — but every dimension is reframed around the delta: are prior findings closed, did the patch introduce a new issue, is the patch itself correct. |

## Framing brief (allow-list)

Before assessing, extract what the artifact already declares about itself: stated scope, stated out-of-scope/non-goals, stated assumptions and constraints, acknowledged limitations. This is an **allow-list**: an artifact is never flagged for not covering what it explicitly declares out of scope, nor for a limitation it already acknowledges. Every assessing agent receives it; the synthesizer drops findings that overlap it. (Same mechanism `/devils-advocate` uses for prose ideas.)

## Calibration (mandatory report footer)

Every assessment ends by answering two questions about *itself* — a posture statement the author can react to:

1. **Weakest link** — which finding the assessment is least confident in, and why. One sentence.
2. **Pre-mortem** — the single most-likely 3-month break cause: if a reader follows this artifact in 3 months and produces a broken outcome, name the one most likely cause. Exactly one sentence — the single-answer constraint is the discipline that kills hand-waving.

Also list agents/dimensions that returned no findings or failed — an empty lens is signal (sometimes positive), not a no-op.

## Anti-patterns

These are the specific failure modes this methodology exists to prevent:

- **Shallow listing.** Findings that all say "could be improved" without quoting what's wrong or what "improved" means.
- **Scope creep.** Suggesting new sections/capabilities the artifact never claimed to cover. Distinguish "this is wrong" (finding) from "this is claimed but underspecified" (gap) from "wouldn't it be nice if it also covered X" (out of scope — omit).
- **Unlinked findings.** A finding or patch that doesn't trace to a specific location and quote — the reader can't independently verify or reject it.
- **Fabricated evidence.** Claiming "line 47 says X" without having read line 47. If you haven't read it, read it before citing it.
- **Over-generating for trivial artifacts.** A 10-line config file does not need 30 findings. "No significant findings" is a valid, complete outcome.
