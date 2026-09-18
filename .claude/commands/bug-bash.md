---
description: Forensic multi-agent bug bash on a file, directory, or project — writes a severity-sorted report with proposed fixes
argument-hint: "[path]  (default: repo root)"
allowed-tools: Workflow, Read, Glob, Grep, Write, Bash(git*), Bash(date*), Bash(mkdir*)
disable-model-invocation: true
---

You are running a forensic bug bash on the scope in **$ARGUMENTS**. Scanner fan-out, rule
enforcement, and synthesis run deterministically in the committed workflow script
`.claude/workflows/bug-bash.js` (SYNC: agent prompts, false-positive rules, schemas, and the
severity DEFINITIONS live THERE — this file owns scope parsing, citation verification, and the
report). You verify the survivors' citations, write the report file, and print a one-line
summary — the full report is NEVER printed to the terminal.

Run the pipeline autonomously — no mid-run user interaction. Read-only except the final
report under `.claude/artifacts/bug-bash/` and a scratchpad sidecar holding the file inventory. Never
modify code, run tests/lint/build, commit, or push.

## Severity Definitions

Three tiers, hard floor: **critical**, **major**, **high**. **medium and below are DROPPED** —
they never appear in the report.

Severity definitions: canonical in `.claude/workflows/bug-bash.js` (`SEVERITY_DEFINITIONS`) —
the md never restates them.

(The `critical/major/high` scale with a hard floor is **intentional design**, not drift from
the family's `critical/major/minor` vocabulary: bug reports below `high` are noise by this
command's charter, so the lower tiers don't exist here. The workflow script's synthesizer
enforces the same scale — edit both together.)

## Phase 0 — Parse Scope

Parse `$ARGUMENTS`:

- Empty → `SCOPE_PATH` = the repo root (the working directory).
- Otherwise → treat as a single filesystem path; strip surrounding quotes; resolve to absolute.

If the path does not exist, inform the user and **STOP** — never silently fall back.

Classify: file → `SCOPE_TYPE = file`; directory with more than one file → `directory`; repo
root (path equals git toplevel, or no argument given) → `project`.

Capture `TIMESTAMP` via `date -u +%Y%m%d-%H%M%S`. Set `REPORT_PATH = .claude/artifacts/bug-bash/<TIMESTAMP>.md`.

## Phase 1 — Inventory & Inline Classification

1. **File inventory.** Walk `SCOPE_PATH` with Glob. When inside a git repo, filter noise via
   `git -C <repo_root> check-ignore --stdin < <list_of_paths>` and exclude every returned
   path. If not a git repo (or the command errors), drop files matching these shapes instead:
   dependency manifests/lock files; generated/compiled output (`*.min.*`, "DO NOT EDIT"
   headers); binary/media; build/cache/vendored directories. Survivors are `INVENTORY_FULL`;
   if empty, tell the user there is nothing to scan and **STOP**.
   `INVENTORY_TOTAL = len(INVENTORY_FULL)`.
2. **Churn signal.** `git -C <repo_root> log --since="6 months ago" --name-only --pretty=format: -- <SCOPE_PATH>`;
   keep up to 50 unique paths intersecting `INVENTORY_FULL` as `RECENT_CHURN` (soft hint, not
   a filter; `[]` on failure).
3. **Cap.** If `INVENTORY_TOTAL <= 400`: `INVENTORY = INVENTORY_FULL`, `INVENTORY_SAMPLED = false`.
   Otherwise keep at most 400 (`RECENT_CHURN` first, then lexicographic) and set
   `INVENTORY_SAMPLED = true`. `FILES_SCANNED = len(INVENTORY)`.

   **Write `INVENTORY` to a sidecar file**, one path per line, in the session scratchpad;
   `INVENTORY_PATH` is its absolute path. 400 paths measure ~16 KB and `args` is size-capped
   (`.claude/workflows/AGENTS.md`), so the list is passed as a path the agents Read — never as
   an array. The scratchpad is session-scoped, so there is nothing to clean up.
4. **Context files.** Glob for `AGENTS.md`, `.github/copilot-instructions.md`, `README*`
   (case-insensitive), `docs/*.md` at the repo root and each inventory directory. Record the
   unique set as `CONTEXT_FILES`. Do **not** read them — agents read on demand.

   **`RECENT_CHURN` and `CONTEXT_FILES` together must serialize to at most 2,500 bytes.** Fill
   that budget in this order: `CONTEXT_FILES` first, then `RECENT_CHURN`. Drop the tail of the
   list that overflows. `CONTEXT_FILES` comes first because an agent cannot find a convention
   doc that no one named to it. The budget exists because `args` is size-capped and the
   command-side total is 4,000 bytes (`.claude/workflows/AGENTS.md`). The remaining ~1,500
   bytes hold `inventoryPath`, `scopePath`, `languages`, `skillsToLoad` and the scalars — none
   of which is separately capped, which is why the two lists stop short of the total rather
   than fill it to the line. A dropped tail is safe
   for both lists: `RECENT_CHURN` is a soft hint, not a filter, and a dropped context file is
   only a doc that the agents do not get a pointer to.
5. **Inline domain classification** (no subagent). Map files to reviewer skills:

   | Signal | Skill |
   | --- | --- |
   | `.py` outside `tests/`, Pydantic models, graph nodes, `src/exact/tools/` | `python-quality` |
   | `tests/`, `tests/fakes.py` | `test-design` |

   Record matches as `SKILLS_TO_LOAD` (possibly empty). `RUN_DOMAIN_AGENT` = non-empty
   `SKILLS_TO_LOAD`; `RUN_DOC_VS_CODE_AGENT` = non-empty `CONTEXT_FILES` AND `SCOPE_TYPE`
   is not `file`. Record `LANGUAGES` from inventory extensions.

## Phase 2 — Run the Workflow

Invoke the `Workflow` tool with `name: "bug-bash"` (script: `.claude/workflows/bug-bash.js`)
and `args`:

```json
{
  "scopePath": "...", "scopeType": "...", "languages": "...",
  "filesScanned": 0, "inventoryTotal": 0, "inventorySampled": false,
  "inventoryPath": "...", "recentChurn": ["..."], "contextFiles": ["..."],
  "skillsToLoad": ["..."], "runDomainAgent": false, "runDocVsCodeAgent": false
}
```

Pass arrays as real JSON arrays, not strings. `inventoryPath` carries the scan list — never an
`inventory` array; the agents Read it. `recentChurn` and `contextFiles` stay inline because
Phase 1 caps the two lists to a combined budget of 2,500 serialized bytes. The workflow returns
`{findings, docClaimsChecked, skillsLoaded, agentsFailed}` — schema-validated, no JSON
parsing or retry needed. Each finding carries a `category` (one of `correctness`, `security`,
`integrity`, `contracts`, `domain`, `documentation`). Record `DOC_CLAIMS_CHECKED` and
`agents_failed` from it.

## Phase 3 — Verify Citations & Write Report

**Verify inline (orchestrator, no subagent).** For each finding, Read the cited `file` at
`start_line..end_line` (and every entry in `locations`). Confirm the file exists, the range
exists, and `evidence` is a byte-exact substring of the cited range (tolerate only
trailing-newline and a single leading/trailing-space difference). Drop failures; count them
as `N_DROPPED_VERIFICATION`. Survivors are `FINAL_FINDINGS`.

Counts: `N_CRITICAL`, `N_MAJOR`, `N_HIGH`; `N_TOTAL` = their sum.

Build `AGENTS_RUN`: always `correctness, security, integrity & contracts, synthesizer`;
append `domain (<SKILLS_TO_LOAD>)` and `doc-vs-code (<DOC_CLAIMS_CHECKED> claims checked)`
when they ran; append `(failed: <name>)` for each entry in `agents_failed`.

**Write the report** to `$REPORT_PATH` (create `.claude/artifacts/bug-bash/` first via `mkdir -p`).
Do NOT print the report body.

````markdown
# Bug Bash Report — $TIMESTAMP

**Scope:** `$SCOPE_PATH`
**Scope type:** $SCOPE_TYPE
**Files scanned:** $FILES_SCANNED of $INVENTORY_TOTAL (sampled: $INVENTORY_SAMPLED)
**Languages detected:** $LANGUAGES
**Agents run:** $AGENTS_RUN
**Doc claims checked:** $DOC_CLAIMS_CHECKED   ← include ONLY when doc-vs-code ran
**Verification:** $N_DROPPED_VERIFICATION findings dropped during citation verification   ← include ONLY if > 0
**Findings:** $N_TOTAL total — $N_CRITICAL critical, $N_MAJOR major, $N_HIGH high (capped at top 10)

---

## Critical ($N_CRITICAL)
## Major ($N_MAJOR)
## High ($N_HIGH)
````

Finding block (number continuously across tiers, starting at 1):

````markdown
### N. <title>

**Location:** `<file>:<start_line>-<end_line>`
**Category:** <category>
**Witnesses:** <witnesses>   ← omit if witnesses ≤ 1

**Evidence:**

```
<verbatim evidence>
```

**Trigger:** <trigger_scenario>

**Entry point:** `<entry_point>`   ← omit if "n/a"

**Impact:** <impact>

**Fix:** <proposed_fix>

**Additional locations:** `<file>:<line>`, ...   ← include only if locations has > 1 entry
````

Skip empty severity sections. If `N_TOTAL` is 0, omit all severity sections and add:
`No findings at or above high severity. Scanners ran on $FILES_SCANNED files.`

## Phase 4 — Terminal Summary

Print exactly this — nothing more.

**If `$N_TOTAL > 0`:**

```text
Bug Bash report written to: $REPORT_PATH
Findings: $N_TOTAL total — $N_CRITICAL critical, $N_MAJOR major, $N_HIGH high
Agents run: $AGENTS_RUN
Verification: $N_DROPPED_VERIFICATION dropped   ← include only if > 0
```

**If `$N_TOTAL == 0`:**

```text
Bug Bash report written to: $REPORT_PATH
No findings at or above high severity (scanned $FILES_SCANNED files).
Agents run: $AGENTS_RUN
```

## Behavioral Rules

1. **Read-only** except `.claude/artifacts/bug-bash/` and the Phase 1 inventory sidecar in the session
   scratchpad. Never modify code, commit, push, or auto-fix.
2. **Citations are re-read in Phase 3.** Paraphrased/shifted/moved findings are dropped and counted.
3. **The orchestrator never invents findings** and never prints the report body — only the one-line summary + path.
4. **No severity below `high`.** No effort estimates.
5. **No tests, lint, typecheck, or build.** Static analysis only.
6. **Failure on a missing scope path is fatal** — stop with a clear error; never silently fall back.
