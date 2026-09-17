# Output Formats

Structured formats for artifact-assessment deliverables. `/forensic-review` writes the FINDINGS_REPORT to `.claude/artifacts/forensic-review/`; the PATCH_PLAN shape below is what a Plan-Mode session should produce once findings are accepted (see that command's Phase 7).

## FINDINGS_REPORT

```markdown
## Forensic Assessment: {artifact name}

**Artifact:** {file path or identifier}
**Cross-references read:** {list of external sources consulted, or "none"}
**Assessment depth:** {trivial / moderate / complex / multi-source}

### Summary

{1-3 sentences: overall health of the artifact and the critical finding count. Be direct.
Example: "The spec is structurally sound but contains 2 critical factual errors in the
deployment section and 3 major completeness gaps in error handling. 12 findings total."}

### Findings

#### F1: {concise title} [CRITICAL]
- **Location:** {file:line, section heading, or positional reference}
- **Evidence:** {exact quote from the artifact AND the contradicting source}
- **Issue:** {what is wrong and why it matters}
- **Recommendation:** {specific, actionable fix}

#### F2: {concise title} [MAJOR]
- **Location:** ...
- **Evidence:** ...
- **Issue:** ...
- **Recommendation:** ...

{Continue for all findings, ordered by severity: CRITICAL first, then MAJOR, MINOR, NIT}

### Scope of this assessment

{What was deliberately NOT examined — stated-out-of-scope items honored, cross-references not followed, dimensions skipped by depth calibration. "Nothing excluded" if none.}

### Calibration

- **Weakest link** (finding this assessment is least confident in, and why): {one sentence, or "n/a"}
- **Single most-likely 3-month break cause:** {exactly one sentence — if a reader follows this artifact in 3 months and produces a broken outcome, the single most likely cause}
- **Agents/dimensions that returned no findings or failed:** {list, or "none"}

### Statistics

| Severity | Count |
|----------|-------|
| Critical | N     |
| Major    | N     |
| Minor    | N     |
| Nit      | N     |
| **Total**| **N** |
```

### Severity definitions

| Severity | Meaning | Action |
|----------|---------|--------|
| **Critical** | Factually wrong, breaks production use, or creates a security/data-integrity risk. Must be fixed before the artifact can be relied on. | Always include in a patch plan. |
| **Major** | Significant gap, inconsistency, or missing coverage that would mislead a reader or cause implementation errors. | Include unless the user explicitly excludes it. |
| **Minor** | Improvement opportunity. Correct but could be clearer, more complete, or better structured. | Include if the user wants thoroughness. |
| **Nit** | Style, formatting, or preference. Not wrong, just different from convention. | Exclude unless the user requests it. |

---

## PATCH_PLAN

Produced inside Plan Mode (the plan file itself), not by the command directly — see `/forensic-review` Phase 7.

```markdown
## Patch Plan: {artifact name}

**Source:** Forensic Assessment at {report path}
**Findings addressed:** F{list of included finding numbers}
**Findings excluded:** F{list of excluded finding numbers}

### Constraints Applied

{List each constraint the user provided between the findings report and this plan.
If none, write "No user constraints — all critical and major findings included."}

### Patches

#### P1: {concise title} <- F{n}
- **Target:** {file path : section or line range}
- **Action:** {Add / Remove / Rewrite / Restructure / Update / Reconcile} — {specific description of the change}
- **Rationale:** Addresses F{n}: {one-line summary of why}

#### P2: {concise title} <- F{n}, F{m}
- **Target:** ...
- **Action:** ...
- **Rationale:** ...
- **Depends on:** P1 {if execution order matters}

{Continue for all patches, ordered by: dependency chain first, then severity, then file grouping}

### Excluded Findings

| Finding | Severity | Reason excluded |
|---------|----------|-----------------|
| F{x}    | Minor    | User constraint: "skip minor findings" |
| F{y}    | Major    | Not actionable without upstream decision |

### Execution Notes

{Ordering constraints, files needing careful sequencing, or which patches to verify together.
If a patch needs domain expertise, name the skill to load during execution: `python-quality` for code,
`test-design` for tests, `design-principles-expert` for structure.}
```

### Patch action vocabulary

| Action | When to use |
|--------|-------------|
| **Add** | New content that doesn't exist yet (missing section, missing edge case) |
| **Remove** | Content that is wrong and should be deleted, not replaced |
| **Rewrite** | Content that exists but is factually wrong or misleading — replace with corrected version |
| **Restructure** | Content that is correct but poorly organized — move, reorder, or split |
| **Update** | Content that is stale — refresh to match current reality (versions, paths, names) |
| **Reconcile** | Two sources disagree — align them to a single source of truth |
