---
description: >
  Parallel divergent ideation under isolated cognitive frames — surfaces non-obvious
  solutions for open-ended design, architecture, naming, API surface, schema, and
  fuzzy-debugging decisions. Spawns N agents under different frames (hardware engineer,
  biology, speedrunner, 3am on-call, etc.), scores/clusters/prunes traps, deepens top
  survivors. Inline output (primary) + report file (secondary). Sits UPSTREAM of the
  SDLC pipeline — feed the deepened ★ pick into /devils-advocate to harden it, then
  into planning. Skip for closed questions with one right answer, syntax/lookups, and
  bugs with a known root cause (nothing to diverge on).
argument-hint: "<problem statement or file path>"
allowed-tools: Workflow, Read, Glob, Grep, Write, AskUserQuestion, Bash(date*), Bash(mkdir*)
disable-model-invocation: true
---

You are running a parallel divergent brainstorm on **$ARGUMENTS**. The frame table,
diverge/focus fan-out, scoring weights, and schemas live in `.claude/workflows/brainstorm.js`
(SYNC: edit frames and vantages THERE — this file owns input parsing, depth classification,
the inline rendering, and the report file). Inline output is the primary delivery; the file
is secondary reference.

Run autonomously after Phase 0. Read-only on the codebase; never modify source files, commit,
push, or run project commands. Only write under `.claude/artifacts/brainstorm/`.

## Phase 0 — Parse Input

Classification (problem kind, depth, frame/idea counts, whether to gather codebase context)
is **not** done here — the workflow script owns it deterministically in `classify()`. This
phase only acquires the input and the report identifiers.

Parse `$ARGUMENTS`:

1. **Empty** → use `AskUserQuestion`: "What problem, decision, or design question should I
   brainstorm about?" Then proceed with the answer.

2. **Resolves to an existing file path** → Read the file. **If it exceeds 200 KB, tell the
   user to point at a smaller artifact or an excerpt, then STOP** — nothing downstream can use
   that much, and it only floods your own context.
   `CONTEXT_FILE` = **the first 1,500 bytes of the file content, and no more**;
   `CONTEXT_FILE_PATH` = the path. Measure bytes, not characters: a file whose section rules
   are drawn with `─` spends 3 bytes per character, so a character count understates the wire
   size in the unsafe direction (`.claude/workflows/AGENTS.md` § Units). The truncation is
   mandatory, not an optimization: the workflow uses only that prefix, and `args` is
   size-capped, so forwarding the whole file breaks the run outright. `CONTEXT_FILE_PATH`
   travels with it and surfaces in the report's `relevant_files`, so a reader can find the
   source — but note that nothing instructs an agent to Read it, so treat that first 1,500
   bytes as the whole of what this file actually contributes. Then use
   `AskUserQuestion`: "I'll use this file as context. What specific question or decision should
   I brainstorm about?" Proceed with the user's answer as the problem statement.

3. **Under 30 characters** → too terse for good divergence. Use `AskUserQuestion` with up to
   3 clarifying questions: "What are the constraints?", "What's at stake if you pick the
   wrong approach?", "What have you already considered and rejected?" Concatenate the
   original + answers → problem statement.

4. **Otherwise** → treat all of `$ARGUMENTS` as the problem statement.

**Cap the problem statement at 1,500 bytes**, whichever branch made it. Branches 1, 3 and 4 are
unbounded. If the statement is longer than 1,500 bytes, do not forward it whole, and do not write
it to a sidecar: a workflow script cannot read a file, and `classify()` needs the statement text
in-process. Summarize it yourself to 1,500 bytes or less. Keep the question, the constraints and
the stated stakes. Remove the background narrative. You keep the full text in your own context,
which the `args` cap does not limit. The reason for the cap: `args` is size-capped, and the
command-side total is 4,000 bytes (`.claude/workflows/AGENTS.md`).

**Derive SLUG**: first 5 words of the problem statement, slugified (lowercase, non-alphanumeric
runs → `-`, collapse/trim hyphens, max 40 chars); fall back to `brainstorm`.

**Capture identifiers**: `TIMESTAMP` via `date -u +%Y%m%d-%H%M%S`, and `SEED` via `date +%s`
(the workflow uses `SEED` for deterministic frame rotation — `Date.now()` is unavailable inside
workflow scripts). Set `REPORT_PATH = .claude/artifacts/brainstorm/<TIMESTAMP>-<SLUG>.md`.

## Phase 1 — Run the Workflow

Invoke the `Workflow` tool with `name: "brainstorm"` (script:
`.claude/workflows/brainstorm.js`) and `args`:

```json
{
  "problemStatement": "<the problem statement, <= 1,500 bytes>",
  "contextFile": "<first 1500 bytes of the file content, or null>",
  "contextFilePath": "<file path, or null>",
  "seed": "<integer epoch seconds from Phase 0>"
}
```

Phase 0 caps both fields at 1,500 bytes each — bytes, not characters, because the 4,000-byte
command-side total is a byte total (`.claude/workflows/AGENTS.md` § Units). Never send a longer
problem statement, and never send the whole file. That prefix is what the workflow consumes.

Classification (`problemKind`, `depth`, `frameCount`, `ideasPerFrame`, and the grounding
decision) is computed inside the workflow's `classify()` — do not pass it. It comes back in
the return object below for rendering.

The workflow returns a schema-validated object:

```json
{
  "problemKind": "code|design|general",
  "frameCount": 5,
  "ideasPerFrame": 6,
  "frames": ["frame name", ...],
  "totalIdeas": 30,
  "contextSource": "codebase (auto-gathered) + file: <path> | none",
  "clusters": [{ "angle": "...", "ideas": [{ "text": "...", "frame": "...", "novelty": 8, "viability": 7, "fit": 9 }] }],
  "traps": [{ "text": "...", "reason": "..." }],
  "shortlist": [{ "text": "...", "frame": "...", "novelty": 8, "viability": 7, "fit": 9, "weighted_score": 7.85, "why_shortlisted": "...", "is_star": false }],
  "deepened": [{ "idea": "...", "frame": "...", "weighted_score": 7.85, "is_star": false, "sketch": "...", "load_bearing_risk": "...", "first_step": "...", "child_ideas": ["..."] }],
  "provocation": "...",
  "lowDivergence": false,
  "codeContext": { "relevant_files": [...], "key_patterns": [...], "summary": "..." } | null,
  "agentsFailed": [...],
  "depth": "default"
}
```

`weighted_score` and `lowDivergence` are computed deterministically by the workflow (not by an
agent); the ★ pick is always among `deepened`.

## Phase 2 — Inline Output (Primary)

Print the brainstorm results directly to the terminal. This is the PRIMARY output — the user
reads it now and picks a direction. Use this exact structure:

```
── Brainstorm ──────────────────────────────────────────────────────────────────
Problem: <problem statement, first 120 chars>
Depth: <depth> (<frameCount> frames × <ideasPerFrame> ideas = <totalIdeas> generated)
Frames: <comma-separated frame names>
Context: <contextSource>

─── Shortlist ──────────────────────────────────────────────────────────────────
```

Then for each shortlist item (numbered, ★ prefix on the is_star item):

```
N. <idea text> [N<novelty> V<viability> F<fit>] (<frame>)
   └─ <why_shortlisted>
```

The shortlist items carry their own `novelty`, `viability`, `fit` scores directly.

Then:

```
─── Deep Dives ─────────────────────────────────────────────────────────────────
```

For each deepened item (★ prefix on the is_star one):

```
### N. <idea text> (<frame>)

<sketch>

**Risk:** <load_bearing_risk>
**First step:** <first_step>
**Child ideas:**
  • <child_idea_1>
  • <child_idea_2>
  • ...
```

Then:

```
─── Traps (<count>) ────────────────────────────────────────────────────────────
  • <idea text> — <reason>
  • ...
```

(Omit the Traps section entirely if there are no traps.)

Then:

```
─── Provocation ────────────────────────────────────────────────────────────────
<provocation text>
```

If `lowDivergence` is true, append:

```
⚠ Low divergence: all ideas clustered into ≤ 2 angles. Consider re-running with
  more context or a reframed problem statement.
```

If `agentsFailed` is non-empty, append:

```
Agents failed: <comma-separated list>
```

## Phase 3 — Write Report File (Secondary)

Create `.claude/artifacts/brainstorm/` via `mkdir -p`. Write the full report to `$REPORT_PATH`.
The report contains EVERYTHING — the wide set (all ideas clustered with individual scores),
the shortlist, traps, deep dives, provocation, and metadata. This is reference material for
"what else was considered."

Report format:

````markdown
# Brainstorm — <SLUG>

**Problem:** <full problem statement>
**Kind:** <code|design|general>
**Depth:** <depth> (<frameCount> × <ideasPerFrame> = <totalIdeas>)
**Date:** <TIMESTAMP>
**Frames:** <comma-separated frame names>
**Context:** <contextSource> (summary: <codeContext.summary>, if any)

---

## Wide Set

### <cluster angle>
- <idea text> `[N<n> V<v> F<f>]` _(<frame>)_
- ...

### <cluster angle>
- ...

(Repeat for all clusters)

---

## Traps

| Idea | Reason |
|---|---|
| <text> | <reason> |

(Omit section if no traps)

---

## Shortlist

1. **<idea>** `[N_ V_ F_]` _(<frame>)_ — <why_shortlisted>
★ 2. **<idea>** `[N_ V_ F_]` _(<frame>)_ — <why_shortlisted>
3. **<idea>** `[N_ V_ F_]` _(<frame>)_ — <why_shortlisted>

---

## Deep Dives

### 1. <idea> _(<frame>)_

<sketch>

**Risk:** <load_bearing_risk>

**First step:** <first_step>

**Child ideas:**
- <child_idea>
- ...

### ★ 2. <idea> _(<frame>)_

...

---

## Provocation

<provocation text>

---

## Metadata

- Agents failed: <list or "none">
- Low divergence: <true|false>
- Code context gathered: <yes|no>
- Report generated by: `/brainstorm`
````

After writing the file, print one final line:

```
────────────────────────────────────────────────────────────────────────────────
Full report (wide set + all scores): <REPORT_PATH>
```

## Behavioral Rules

1. **Read-only on source.** Only write under `.claude/artifacts/brainstorm/`. Never edit source files,
   commit, or push.
2. **Inline output is primary.** The user reads the terminal, not the file. The file is
   reference — do not tell the user to "go read the report."
3. **No mid-run user interaction** after Phase 0. Once the workflow is invoked, run to
   completion autonomously.
4. **The isolation invariant is sacred.** The workflow enforces parallel isolated agents —
   never attempt to simulate divergence by generating ideas sequentially in one context.
5. **No code-edit suggestions.** Ideas are approaches and directions, not code patches.
6. **No tests, lint, typecheck, build, or git operations.** Static reading only (context
   gathering phase reads code structure, never executes it).
7. **Commit to a position.** The shortlist and ★ pick are opinions. "Here are 30 ideas, you
   decide" is a failure mode. Generate wide, but converge with conviction.
