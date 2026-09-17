---
description: Devil's-advocate review of an idea or document — surfaces hidden assumptions, failure modes, alternatives, second-order effects, and open questions through parallel adversarial lenses; writes a hardening report. Use when the artifact's IDEAS/ASSUMPTIONS are in doubt; when its CLAIMS ABOUT REALITY are in doubt use /forensic-review; unsure → /forensic-review first (you can't harden an idea whose factual premises are false)
argument-hint: "<file path | pasted document text>"
allowed-tools: Workflow, Read, Glob, Grep, Write, AskUserQuestion, Bash(jq*), Bash(date*), Bash(mkdir*)
disable-model-invocation: true
---

You are running a devil's-advocate adversarial review on **$ARGUMENTS**. The framing brief,
adversarial lens fan-out, and synthesis run deterministically in the committed workflow
script `.claude/workflows/devils-advocate.js` (SYNC: lens prompts, anti-FUD rules, schemas,
and the severity DEFINITIONS live THERE — this file owns input parsing, the citation pass,
the verdict formula, and the report). The report is NEVER printed to the terminal — only a
concise summary plus the path.

This reviews **prose artifacts** — specs, designs, plans, RFCs, proposals, postmortems,
architecture docs, free-form ideas. It does not review code; use `/bug-bash` for that.

Run autonomously after Phase 0. Read-only on the source; never modify the reviewed document,
commit, push, or run project commands.

## Severity Definitions

Three tiers: **critical**, **major**, **minor** (no `nit` — prose reviews don't have one).

Severity definitions: canonical in `.claude/workflows/devils-advocate.js` (interpolated into
each lens's `sharedContext`) — the md never restates them.

(Three tiers by design — prose reviews have no `nit` tier; `/forensic-review` adds one
for artifact reviews. The names align with the family's shared critical/major/minor
vocabulary. The workflow script's schemas enforce the same tiers — edit both together.)

## Phase 0 — Parse Scope

Parse `$ARGUMENTS`:

- Empty → use `AskUserQuestion` to ask the user to paste the document text or provide a file path, then proceed with the answer.
- If it resolves to an existing file path:
  - If the extension is a code file (`.py`, `.ts`, `.tsx`, `.js`, `.go`, `.rs`, `.java`, `.rb`, `.sql`, `.sh`, and similar), tell the user: "This command reviews prose, not code. Try `/bug-bash <path>` for a code audit." and **STOP**.
  - If the file exceeds 200 KB, tell the user to split it and re-run, then **STOP**.
  - Read it → `DOCUMENT_TEXT`; `SOURCE_PATH` = the path; `INPUT_KIND = "file"`.
- Otherwise (not a path):
  - If under 100 characters (a bare idea — the input where adversarial review is most valuable): switch to **question mode**. Use `AskUserQuestion` (or plain questions if the idea needs open-ended answers) to ask up to 5 Socratic clarifying questions — goal, constraints, alternatives already rejected, success criteria, what's at stake if wrong. Concatenate the original input + answers → `DOCUMENT_TEXT`; `SOURCE_PATH = "inline"`; `INPUT_KIND = "inline-enriched"`. Then proceed normally.
  - Else treat all of `$ARGUMENTS` as the document → `DOCUMENT_TEXT`; `SOURCE_PATH = "inline"`; `INPUT_KIND = "inline"`.

**Delivery decision (size-based, not source-based).** `args` is size-capped
(`.claude/workflows/AGENTS.md`) and a document has no size bound, so decide how the text
reaches the agents by **measuring it**, never by where it came from — the inline modes above
produce documents just as large as a file does:

- `DOCUMENT_TEXT` **at or under 2,500 bytes** → pass `documentText`, and omit `documentPath`.
- **Over 2,500 bytes** → pass `documentPath` instead, and omit `documentText` entirely. For
  `INPUT_KIND = "file"` the path **is** `SOURCE_PATH` — resolve it to an absolute path, no copy.
  For the inline kinds there is no source file, so write `DOCUMENT_TEXT` to a
  session-scratchpad sidecar and pass that absolute path.

2,500 is the inline threshold, not the whole budget: `domainSkillMap`, `subject`, `sourcePath`
and `inputKind` also travel inline and cost about 755 bytes together — `domainSkillMap` alone is
403. Those numbers are a pre-check, not the guarantee. They measure raw values, so their sum
does not establish the serialized total, and `sourcePath` carries no cap of its own.

**2,500 raw bytes of `DOCUMENT_TEXT` is not 2,500 bytes of payload.** Quotes, backslashes, and
newlines grow under JSON escaping — a document dense with those can add close to its own length
again. Before invoking `Workflow`, write the intended `args` object to a session-scratchpad file — bind its absolute
path to `ARGS_PROBE` in the same `Bash` call — and
measure the actual serialized total per `.claude/workflows/AGENTS.md` §2:

```bash
jq 'tojson | utf8bytelength' "$ARGS_PROBE"
```

If over 4,000 bytes even with `documentText` at or under the 2,500-byte guideline, take the
`documentPath` branch above instead — `SOURCE_PATH` for `INPUT_KIND = "file"`, a new
session-scratchpad sidecar for the inline kinds — and measure again.

Either way set `SUBJECT` = the first line of `DOCUMENT_TEXT`, trimmed to 200 bytes. The
workflow needs a subject in-process when the framing agent fails, and it must never reconstruct
one from document text it may not have.

Derive `SLUG`: for a file, the filename stem (prefix with the parent dir name if the stem is
generic like `README`/`spec`/`design`/`plan`/`notes`/`proposal`/`rfc`); for inline, the
first 5 words. Slugify (lowercase, non-alphanumeric runs → `-`, collapse/trim hyphens); fall
back to `inline-review`.

Capture `TIMESTAMP` via `date -u +%Y%m%d-%H%M%S`. Set
`REPORT_PATH = .claude/artifacts/devils-advocate/<TIMESTAMP>-<SLUG>.md`.

## Phase 1 — Run the Workflow

Invoke the `Workflow` tool with `name: "devils-advocate"` (script:
`.claude/workflows/devils-advocate.js`) and `args`:

```json
{
  "documentText": "<the document, <= 2,500 bytes>",
  "subject": "...", "sourcePath": "...", "inputKind": "file|inline|inline-enriched",
  "domainSkillMap": [
    { "pattern": "architecture|coupling|abstraction|design|topology|graph", "skill": "design-principles-reviewer" },
    { "pattern": "test|pytest|fixture|fake|coverage", "skill": "test-design" },
    { "pattern": "python|cli|pydantic|langgraph|node|tool|prompt", "skill": "python-quality" }
  ]
}
```

That is the **inline** shape. Over the budget, swap `documentText` for `documentPath` and send
nothing else differently:

```json
  "documentPath": "<absolute path>",
```

**Send one key or the other, never both.** The workflow branches on **key presence** — there is
no companion `documentInline` flag, deliberately: a flag restates what presence already encodes
and, omitted or mistyped, silently shipped the agents `DOCUMENT TEXT: undefined`. Sending
neither key now **throws before any agent spawns**; sending both logs a warning and uses
`documentPath` (the copy with no size bound).

Phase 2's citation pass still uses your own `DOCUMENT_TEXT`; orchestrator context is not subject
to the args cap.

`domainSkillMap` is this repo's regex→skill table (regex source strings, matched
case-insensitively against the framing brief's `domains` to pick the domain critic). The
workflow compiles each pattern with `new RegExp(pattern, 'i')` and defaults to `[]` (no domain
lens) when the arg is absent — that repo-specificity lives here, not in the shared script.

The workflow returns — schema-validated, no JSON parsing or retry needed:

```json
{
  "findings": [ { "lens": "...", "lenses": ["..."], "section": "...", "kind": "...",
                  "severity": "critical|major|minor", "title": "...", "doc_anchor": "...",
                  "argument": "...", "suggestion": "..." } ],
  "calibration": { "least_confident": "...", "premortem": "..." },
  "framingBrief": { "subject": "...", "artifact_type": "...", "...": [] },
  "fragilePoints": [ { "lens": "...", "fragile_point": "..." } ],
  "domainSkills": ["..."], "lensesEmpty": ["..."], "agentsFailed": ["..."]
}
```

## Phase 2 — Citation Pass, Verdict & Write Report

**Citation pass (orchestrator, inline — no subagent).** For each finding: if `doc_anchor` is
`"not addressed"` (valid only for `alternative`/`open_question` kinds), pass; otherwise
confirm the quote (or a close substring, allowing minor whitespace differences) appears in
`DOCUMENT_TEXT`. Drop findings that cannot be located. Survivors are `FINAL_FINDINGS`; count
drops as `N_DROPPED_VERIFICATION`.

Counts: `N_CRITICAL`, `N_MAJOR`, `N_MINOR`; `N_TOTAL` = their sum. Compute the **verdict**:
`solid` (0 critical AND ≤ 3 major); `harden` (1-3 critical OR ≥ 4 major); `rework`
(≥ 4 critical OR critical-severity findings spanning ≥ 4 distinct lenses).

Cross-lens consensus (a finding's `lenses` array length) never changes severity or the
verdict — it is an ordering and annotation signal only. The synthesizer already orders
multi-lens findings first within each severity tier; preserve its order in the report.

`CALIBRATION` = the workflow's `calibration`. `LENSES_EMPTY` = the workflow's `lensesEmpty`
(+ note: the `alternative` lens returning empty is a **positive signal** — the doc's choice
among strong options, including over doing nothing, holds). `FRAGILE_POINTS` = the workflow's `fragilePoints` (one entry per
non-alternative lens that ran, returned zero findings, and emitted a non-`'n/a'`
`fragile_point`; a zero-finding lens may therefore lack an entry — the rendering rule in the
report template covers that case). `LENSES_CONTRIBUTING` = the deduplicated `lenses` union from
`FINAL_FINDINGS`. `AGENTS_RUN` = `framing, premise, failure, operational, alternative,
second-order, reversibility, synthesizer`, plus `domain (<domainSkills>)` if it ran, plus
`(failed: <name>)` per `agentsFailed` entry.

**Write the report** to `$REPORT_PATH` (create `.claude/artifacts/devils-advocate/` first via
`mkdir -p`). Do NOT print the report body. Render Markdown:

````markdown
# Devil's Advocate Review — <SLUG>

**Source:** `<SOURCE_PATH>`
**Artifact type:** <framingBrief.artifact_type>
**Date:** <TIMESTAMP>
**Verdict:** <solid|harden|rework>
**Findings:** <N_TOTAL> total — <N_CRITICAL> critical, <N_MAJOR> major, <N_MINOR> minor
**Lenses:** <LENSES_CONTRIBUTING>
**Artifact:** <line count of DOCUMENT_TEXT> lines, <artifact_type>, input: <INPUT_KIND>
**Verification:** <N_DROPPED_VERIFICATION> findings dropped   ← include ONLY if > 0

---

## Framing

**Subject:** <framingBrief.subject>
**Goals / Assumptions / Constraints / Non-goals / Risks already discussed:** <each as a bullet list, or "Not stated" / "None">

### Scope of this assessment

<What was deliberately NOT examined: e.g. referenced files not read, domain lens not run (and why), sections excluded by the framing brief. One bullet each; "Nothing excluded" if none.>

---

## Premises Worth Re-examining
## Failure Modes Not Discussed
## Operational Realities
## Alternatives Worth Considering
## Second-Order Effects
## Reversibility & Rollback
## Domain-Specific Concerns
## Open Questions

---

## Calibration

- **Weakest link** (finding this review is least confident in, and why): <CALIBRATION.least_confident>
- **Single most-likely 3-month break cause:** <CALIBRATION.premortem — exactly one sentence>
- **Lenses that returned no findings or failed:**
  - For each lens in LENSES_EMPTY except `alternative`: `<lens> — no findings; most fragile assumption: <its FRAGILE_POINTS entry>`. If it has no FRAGILE_POINTS entry, render `<lens> — no findings`.
  - If `alternative` is in LENSES_EMPTY: `alternative — no genuinely-different alternative (including doing nothing) worth considering (positive signal)`
  - For each name in agentsFailed: `<name> — agent failed`
  - If all three lists are empty: `None — every lens contributed findings.`

---

## How to use this report

- Address critical-severity findings before implementation.
- For findings you consciously reject, note the reasoning in your source document so the next reviewer does not re-raise them.
- This report is advisory and read-only.
````

Finding block (number continuously within each section, restarting at 1 per section):

````markdown
### N. <title> — <severity>

> _"<doc_anchor>"_   ← omit this blockquote if doc_anchor is "not addressed"

**Argument:** <argument>

**Suggestion:** <suggestion>

_Flagged independently by <count> lenses: <comma-separated lenses>_   ← include only if the lenses array has > 1 entry
````

**Omit empty sections entirely.** If `N_TOTAL` is 0, omit all finding sections and add under
Framing: `No finding cleared the discipline bar.` — then, if `agentsFailed` is empty, append
`That is not a clean bill of health — see Calibration for the most fragile assumption each lens
still names.`; if `agentsFailed` is non-empty, append instead `Not every lens ran — see
Calibration for the lenses that failed. Their concerns are unknown, not addressed.` Add no
commentary beyond "How to use this report."

## Phase 3 — Terminal Summary

Print exactly this — nothing more.

**If `$N_TOTAL > 0`:**

```text
Devil's Advocate review written to: $REPORT_PATH
Verdict: $VERDICT
Findings: $N_TOTAL total — $N_CRITICAL critical, $N_MAJOR major, $N_MINOR minor
Artifact: <line count> lines, <artifact_type>, input: $INPUT_KIND
3-month break cause: $CALIBRATION.premortem
Lenses: $LENSES_CONTRIBUTING
Alternative lens: no genuinely-different alternative (including doing nothing) worth considering (positive signal)   ← include only if the alternative lens ran and returned []
Verification: $N_DROPPED_VERIFICATION dropped   ← include only if > 0
Agents failed: <list>   ← include only if non-empty
Top findings to address:
  1. <highest-severity title> (consensus: <N> lenses)   ← the suffix applies PER FINDING on each of the up-to-3 lines: include it only when that finding's lenses array has > 1 entry; omit it otherwise
  2. <second> (consensus: <N> lenses)
  3. <third> (consensus: <N> lenses)
```

Show up to 3 top findings (fewer if fewer exist).

**If `$N_TOTAL == 0`:**

```text
Devil's Advocate review written to: $REPORT_PATH
No finding cleared the discipline bar — see Calibration for each lens's most fragile assumption.   ← if `agentsFailed` is non-empty, print instead: `No finding cleared the discipline bar, and not every lens ran — the failed lenses' concerns are unknown, not addressed.`
Agents failed: <list>   ← include only if non-empty
```

## Behavioral Rules

1. **Read-only on the source.** Only write under `.claude/artifacts/devils-advocate/`, plus two session-scratchpad files: the Phase 0 document sidecar, written when Phase 0 takes the `documentPath` branch **for an inline kind** — because the raw text exceeded the inline threshold **or** because the measured payload exceeded the command-side total; a `file` input reuses `SOURCE_PATH` and is never copied — and the Phase 0 `args` probe file the measurement step reads. Never edit the reviewed document, commit, or push.
2. **The framing brief is the noise-reduction spine** — the workflow threads it through every lens and the synthesizer as an allow-list.
3. **Verdict is signal, not a gate** — it never blocks anything; the author reads and decides.
4. **The orchestrator never prints the report body** — only the summary + path.
5. **No code-edit suggestions** — suggestions are prose ("add a section about X", "document the rollback plan").
6. **No tests, lint, typecheck, build, or git operations.** Static reading only.
7. **No mid-run user interaction** after Phase 0.
8. **Code-file inputs are rejected** with a pointer to `/bug-bash`.
