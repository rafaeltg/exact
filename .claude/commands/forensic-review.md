---
description: Forensic assessment of an existing artifact (doc, spec, config, schema, or instruction file) for correctness, completeness, and consistency — writes a findings report, then on request transitions to Plan Mode to turn accepted findings into a patch plan. Use when the artifact's CLAIMS ABOUT REALITY are in doubt; when its IDEAS/ASSUMPTIONS are in doubt use /devils-advocate; unsure → run this first (you can't harden an idea whose factual premises are false)
argument-hint: "<artifact path>  (or: compare <A> vs <B> | review findings in <path> | changes to <path>)"
allowed-tools: Workflow, Task, Read, Glob, Grep, Write, Bash(date*), Bash(mkdir*), EnterPlanMode
disable-model-invocation: true
---

You are running a forensic assessment on the scope in **$ARGUMENTS**. Ground-truth
gathering, the assessment-dimension fan-out, and synthesis run deterministically in the
committed workflow script `.claude/workflows/forensic-review.js` (SYNC: agent prompts,
schemas, and the evidence standard live THERE — this file owns variant/depth parsing, the
inline framing brief, citation verification, report rendering, and Phase 7 plan mode). The
full report is NEVER printed to the terminal — only a one-line summary plus the report path.

This assesses **existing artifacts** — documents, specs, configs, schemas, prompt templates,
instruction files (including this repo's own `SKILL.md`/command files) — for whether they
are *correct*, not whether an idea is sound (`/devils-advocate`) or a code diff has bugs
(`/bug-bash`). Load `forensic-assessment` for the full six-dimension methodology; the
workflow script inlines that skill's rubric into each agent's context.

Run Phases 0-6 autonomously — no mid-run user interaction. Read-only except the final report
under `.claude/artifacts/forensic-review/`. Phase 7 (patch planning) runs ONLY on explicit user
request, after Phase 6 has already stopped and the user has responded.

## Severity Definitions

- **critical** — Factually wrong, breaks production use, or creates a security/data-integrity risk.
- **major** — Significant gap or inconsistency that would mislead a reader or cause implementation errors.
- **minor** — Correct but could be clearer / more complete.
- **nit** — Style/formatting preference. Rare — only when explicitly asked for thoroughness.

(Four tiers by design — artifact reviews add the `nit` tier that `/devils-advocate`'s
prose reviews lack. SYNC: these definitions are duplicated in
`.claude/workflows/forensic-review.js` because both files consume them — this orchestrator
assigns severities itself on the `trivial`-depth inline path, where no workflow runs, and the
workflow's agents need them in their prompts. The residual risk of prose drift between the two
copies is accepted; edit both together.)

## Phase 0 — Parse Scope & Input Variant

Parse `$ARGUMENTS` to determine `INPUT_VARIANT` and the artifact path(s):

- Starts with `compare ` and contains ` vs ` → `INPUT_VARIANT = comparison`; `SOURCE_A`, `SOURCE_B` = the two paths.
- Contains `findings` together with a path to a markdown file under a report-shaped location (e.g. `.claude/artifacts/**/*.md`) → `INPUT_VARIANT = meta_review`; `FINDINGS_PATH` = that path; if the report names the artifact it assessed, also resolve `ARTIFACT_PATH` from it.
- Starts with `changes to ` or `re-review ` → `INPUT_VARIANT = re_review`; `ARTIFACT_PATH` = the named path.
- Otherwise → `INPUT_VARIANT = standard`; `ARTIFACT_PATH` = `$ARGUMENTS` (strip surrounding quotes, resolve to absolute).

If no path resolves to a real file, inform the user and **STOP**.

Derive `SLUG`: standard/re_review → the artifact's filename stem (prefix with the parent
directory name if the stem is generic — `SKILL`, `README`, `index`, `spec`, `design`,
`plan`, `config` — the same rule `/devils-advocate` uses, for the same reason: this repo
alone has 7 files literally named `SKILL.md`); comparison → `<stemA>-vs-<stemB>`; meta_review →
`meta-<findings-filename-stem>`. Slugify (lowercase, non-alphanumeric runs → `-`).

Capture `TIMESTAMP` via `date -u +%Y%m%d-%H%M%S`. Set
`REPORT_PATH = .claude/artifacts/forensic-review/<TIMESTAMP>-<SLUG>.md`.

## Phase 1 — Full Read, Cross-References & Framing Brief

Read every artifact path resolved in Phase 0, completely — no partial reads. This is for **your
own** context: `ARTIFACT_LINE_COUNT` (the highest line number in the Read output) drives Phase 2's
depth calibration, and Phase 4 verifies every citation against what you read.

**Do not forward the bytes.** The workflow receives paths only — `artifactPath`,
`sourceAPath`/`sourceBPath`, `findingsPath` — and the agents Read them themselves. Documents have
no size bound and `args` is size-capped; 5 tracked `.md` files in this repo alone exceed the
observed failure point on their own. See `.claude/workflows/AGENTS.md`.

Identify what the artifact depends on: code it describes, other docs it references, canonical
sources of truth for any version/config/behavioral claim. If the reference web is small and
enumerated, read them directly. If non-trivial, spawn a single `Explore` subagent to locate
every dependency (file:line each; flag anything the artifact claims exists but cannot be
found) — `Explore` documents, it does not judge. Record the located sources as a
`CONTEXT_SOURCES` string of **at most 1,200 bytes**. If the reference web is larger than the
cap, keep the entries the findings are most likely to cite — the artifact's direct
dependencies and the canonical sources of truth for its claims — and drop the rest. The agents
can locate anything else themselves: `CONTEXT_SOURCES` is a pointer list, not the evidence.

**Framing brief (inline, orchestrator — you just read the artifact).** Extract what the
artifact already states about itself, as verbatim phrases or close paraphrases (empty where
silent): `stated_scope`, `stated_out_of_scope`, `stated_assumptions`, `stated_constraints`,
`known_limitations_acknowledged`. Record as `FRAMING_BRIEF` (a JSON object) of **at most 1,200
bytes serialized**. This is an allow-list — the workflow threads it through every agent and the
synthesizer. If the extraction is larger than the cap, shorten the individual phrases first
(they are already meant to be verbatim phrases or close paraphrases, not full sentences); drop
the least load-bearing entries only after that. A dropped entry leaves the allow-list short,
and costs a false finding on something the artifact did state — this is why shortening is
better than dropping.

## Phase 2 — Depth Calibration & Agent Selection

**Check `INPUT_VARIANT` before line count — it takes precedence:**

- `comparison` → `ASSESSMENT_DEPTH = multi_source`, unconditionally.
- `meta_review` → `ASSESSMENT_DEPTH = meta_review`, unconditionally; the trivial shortcut never applies.
- `standard`/`re_review` → classify by `ARTIFACT_LINE_COUNT`:
  - `trivial` (< 30 lines, single concern) → **do NOT run the workflow.** Apply dimensions 1 (factual correctness) and 2 (completeness) yourself, inline, against `CONTEXT_SOURCES`, honoring `FRAMING_BRIEF`; produce findings directly in the report schema; answer the two Calibration questions yourself; skip to Phase 4.
  - `moderate` (30-200 lines) → run the workflow, one pass per agent.
  - `complex` (> 200 lines, cross-cutting) → run the workflow at `complex` depth (agents do multiple passes, cross-reference reads mandatory).

Decide agent inputs (passed as workflow args):

- `groundTruthQuery` — if any dimension-3/4/6 claim hinges on "what does this codebase actually do" (the artifact asserts a convention — constructor injection, a naming pattern, an error-handling shape), set it to that pattern description, **at most 300 bytes** — it is a query, not an excerpt; the workflow runs a `codebase-pattern-finder` pass first. Else `null`.
- `runProductionReadiness` — true iff the artifact type is architecture/deployment/API/config (not meeting notes or a simple instruction file).
- `externalStandards` — the named external standard(s) (RFC, OWASP, a vendor API contract) the artifact claims conformance to, **at most 5 entries and 200 bytes serialized** — name each standard, never quote it; else `[]`. Non-empty spawns a **two-agent** conformance pass: a `web-researcher` that researches the standard alone (it is never given the artifact — it has no filesystem access), then an `fs-readonly-worker` that reads the artifact completely — both sources on the `comparison` variant — and checks the researched requirements against what it read. The harness enforces the split from both sides: stage 1 holds the web and no filesystem, stage 2 holds the filesystem and no web tool, so neither agent holds both halves. It shows up as two agents, `std-research` and `std-compare`, under the one `external-standards` label.

## Phase 3 — Run the Workflow

Invoke the `Workflow` tool with `name: "forensic-review"` (script:
`.claude/workflows/forensic-review.js`) and `args`:

```json
{
  "variant": "standard|re_review|comparison|meta_review",
  "depth": "moderate|complex|multi_source|meta_review",
  "artifactPath": "...",
  "sourceAPath": "...", "sourceBPath": "...",
  "findingsPath": "...",
  "contextSources": "...", "framingBrief": { "stated_scope": [], "...": [] },
  "groundTruthQuery": null, "runProductionReadiness": false,
  "externalStandards": [], "priorFindingsPath": null
}
```

Omit the keys that don't apply to the variant. **Artifacts travel by path — there is no `*Text`
field.** Four fields are inline derived summaries rather than artifacts, and each carries its
own cap: `contextSources` and `framingBrief` at 1,200 bytes each (Phase 1), `groundTruthQuery`
at 300 and `externalStandards` at 200 (Phase 2). Those caps are a pre-check. They do not prove
the payload is in budget: measure the serialized payload, per `.claude/workflows/AGENTS.md` § 2.
This variant needs the measurement most. The five path fields carry no stated cap of their
own — with every key present and long absolute paths this variant runs closest to the ceiling
of the five commands, so keep paths short where you can. Pass absolute paths,
or paths the agents can resolve from the repo root.

The workflow returns — schema-validated, no
JSON parsing or retry needed:

- Standard/re_review/comparison: `{findings, calibration:{least_confident, premortem}, agentsFailed, prevailingPatternEvidence}`.
- meta_review: `{verdicts:[{finding_id, verdict, rationale, evidence}], agentsFailed, prevailingPatternEvidence}`.

## Phase 4 — Verify Citations

**Inline, orchestrator, no subagent.** For each finding (or meta-review verdict), re-read the
cited location and confirm `artifact_quote` and `reality_quote` (where not `'n/a'`) are
byte-exact (or near-exact — tolerate only trailing-newline/whitespace) substrings of what's
actually there. Drop failures; count as `N_DROPPED_VERIFICATION`.

Counts: `N_CRITICAL`, `N_MAJOR`, `N_MINOR`, `N_NIT`; `N_TOTAL` = their sum.

For `trivial` depth (no workflow ran), you already produced findings and answered the
Calibration questions inline. `AGENTS_RUN` = the dimension agents that ran (from the
workflow's implicit set + `agentsFailed`), or `inline (trivial depth)`.

## Phase 5 — Write FINDINGS_REPORT

Write to `$REPORT_PATH` (create `.claude/artifacts/forensic-review/` first via `mkdir -p`). Do NOT
print the report body.

````markdown
## Forensic Assessment: $SLUG

**Artifact:** $ARTIFACT_PATH (or $SOURCE_A vs $SOURCE_B, or "findings in $FINDINGS_PATH")
**Input variant:** $INPUT_VARIANT
**Cross-references read:** $CONTEXT_SOURCES (or "none")
**Assessment depth:** $ASSESSMENT_DEPTH
**Verification:** $N_DROPPED_VERIFICATION findings dropped   ← include ONLY if > 0

### Summary

{1-3 sentences: overall health and the critical finding count. Be direct.}

### Findings

#### F1: {title} [CRITICAL]
- **Location:** ...
- **Evidence:** {artifact_quote} vs {reality_quote}
- **Issue:** ...
- **Recommendation:** ...

{Continue, ordered critical → major → minor → nit. For meta_review, render verdicts instead:
finding id, verdict, rationale, evidence.}

### Scope of this assessment

{What was deliberately NOT examined: framing-brief exclusions honored, cross-references not followed (and why), dimensions skipped by depth calibration. One bullet each; "Nothing excluded" if none.}

### Calibration

- **Weakest link** (finding this assessment is least confident in, and why): {calibration.least_confident}
- **Single most-likely 3-month break cause** (if a reader follows this artifact and produces a broken implementation): {calibration.premortem — exactly one sentence}
- **Agents that returned no findings or failed:** {agentsFailed, or "none"}

### Statistics

| Severity | Count |
|----------|-------|
| Critical | N |
| Major    | N |
| Minor    | N |
| Nit      | N |
| **Total**| **N** |
````

If `N_TOTAL` is 0: omit the Findings section, write "No significant findings — the artifact
holds up under all applicable dimensions." under Summary.

**No overall verdict, by design:** this command reports findings + severity counts and lets
the author decide; verdict language (`solid/harden/rework`) belongs to `/devils-advocate`,
whose subject is a single idea. This divergence is intentional, not drift.

## Phase 6 — Terminal Summary, then STOP

Print exactly this — nothing more:

```text
Forensic assessment written to: $REPORT_PATH
Findings: $N_TOTAL total — $N_CRITICAL critical, $N_MAJOR major, $N_MINOR minor, $N_NIT nit
Depth: $ASSESSMENT_DEPTH; variant: $INPUT_VARIANT; artifact: $ARTIFACT_LINE_COUNT lines
3-month break cause: $CALIBRATION.premortem
Verification: $N_DROPPED_VERIFICATION dropped   ← include only if > 0
Agents failed: <list>   ← include only if non-empty
Top findings:
  1. <highest-severity title>
  2. <second>
  3. <third>
```

Show up to 3 top findings (omit the line entirely if `N_TOTAL = 0`).

**Do not proceed further unless the user explicitly asks for a plan.** This is the Phase 1→2
gate from the original methodology, held structurally.

## Phase 7 — Patch Plan (only on explicit request, in a LATER turn)

When the user asks to turn the findings into a plan ("plan the fixes," "patch this,"
similar): call `EnterPlanMode` yourself, in the main session — do not delegate this to a
subagent; Plan Mode is session-level and only the top-level agent can call `ExitPlanMode` to
close the gate.

Seed the plan with `$REPORT_PATH`'s findings. Apply any constraints the user states as
filters before drafting. Write the plan file using the PATCH_PLAN shape from
`forensic-assessment`'s `references/output-formats.md`: patches traced to finding numbers,
Target/Action/Rationale/Dependencies, an Excluded Findings table. If a patch needs domain
expertise, name the skill to load during execution: `python-quality` for code and structure,
`test-design` for tests.

`ExitPlanMode` is the approval gate. Once approved, execution proceeds as normal.

## Behavioral Rules

1. **Read-only through Phase 6.** Only `.claude/artifacts/forensic-review/` is written. Never modify the assessed artifact, commit, or push. Phase 7 only runs on explicit request and only edits what an approved plan says to.
2. **No finding without a verbatim quote on both sides** (except legitimate pure-gap findings, where the reality side is `'n/a'`).
3. **Citations are re-read in Phase 4.** Paraphrased or fabricated findings are dropped and counted.
4. **The orchestrator never invents findings and never prints the report body** — only the Phase 6 summary and path.
5. **Depth is calibrated, not maximized.** A trivial artifact skipping straight to a two-dimension inline pass is correct behavior, not a shortcut.
6. **`EnterPlanMode` is reachable only from Phase 7**, and only on explicit user request — never auto-triggered after Phase 6's summary.
7. **No tests, lint, typecheck, or build.** Static reading and, in Phase 7, plan-approved edits only.
