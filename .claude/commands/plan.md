---
description: >
  Write .claude/artifacts/plan/<topic>/plan.md — a canonical, phased, task-level plan that an LLM
  executes task by task. The only input is the Ready specification docs/specs/<topic>.md. Takes no
  product decision. A fresh agent reviews the plan against the tree before it is approved.
argument-hint: "<topic-slug>"
allowed-tools: Read, Glob, Grep, Write, Edit, AskUserQuestion, Agent, Task, SendMessage, Skill, Bash(make plan-check*), Bash(make spec-check-ready*), Bash(git status*), Bash(git rev-parse*), Bash(git ls-files*), Bash(shasum*), Bash(date*), Bash(mkdir*)
disable-model-invocation: true
---

You write a plan that an LLM executes task by task. The plan is the contract. The executor does
not read the specification, and it does not read this conversation.

**The only specification is `docs/specs/$1.md`.** Do not search for another. Do not accept a
free-text product decision. Do not create `assumptions.md`, `gaps.md`, or `contract.md`.
**When a product decision is missing, STOP.** Print the requirement and the repository evidence,
and send the user to `/spec $1`. `/spec` owns every behavior decision.

**Two skills own the method.** `phase-slicing` owns where the phase lines go. `task-structuring`
owns what a task and a `Verify` look like. This command owns the gates, the output contract, and
the review. **Never re-explain a skill's method here.** The output shape below repeats the
field layout only, so the document format sits in one place. Load each skill at the phase that
needs it.

`.cursor/hooks/plan-guard.py` owns the validation rules. `make plan-check` is authoritative. The
lists below help you write; they never replace a run of the gate.

## Phase 0 — Gate the inputs

1. **Validate `$1` against `^[a-z0-9][a-z0-9._-]*$`. STOP when it fails.** Print the slug.
2. STOP when `docs/specs/$1.md` does not exist. Print the path.
3. **STOP unless the specification carries the line `Status: Ready`.** Check the line yourself.
   No gate checks it: a committed `Status: Draft` document passes `spec-check-ready` and
   `plan-check`.
4. Run `make spec-check-ready FILE=docs/specs/$1.md`. **STOP on any finding.** Print the findings.
   The gate needs a tracked specification, a clean tracked worktree, and no difference from
   `HEAD`.
5. Run `git status --porcelain=v1 --untracked-files=all`. **The output must be empty.** STOP when
   it is not. A dirty tree breaks the `Repository commit` metadata the plan records.
6. **Inspect `.claude/artifacts/plan/$1/` before you write anything.**
   - It does not exist: go on.
   - It exists without `.spec-plan-v1`, or the marker holds other bytes: **STOP.** The directory
     holds an older plan format. Ask the user to move it. Never overwrite it.
   - It holds a valid marker and a `plan.md` whose metadata does not match the current
     specification: STOP. Ask whether to replace the plan.
7. Only now write `.claude/artifacts/plan/$1/.spec-plan-v1`. It holds exactly `version=1` and a
   final newline.

## Phase 1 — Read the contract

1. Read `docs/specs/$1.md` in full.
2. The active `D<n>` identifiers are the only decisions a task may cite. A superseded decision is
   not citable.
3. The specification names are immutable. Use them verbatim.
4. Read `AGENTS.md`, and the code each requirement touches.

## Phase 2 — Draw the phases

1. Invoke `Skill(skill="phase-slicing")`. Follow it. Do not repeat its rules here.
2. Produce the phase list, the cross-phase contracts, and the file-ownership map.
3. **A path belongs to one phase only.** The gate rejects a reused owned path, and it rejects a
   task file outside its own phase's ownership.
4. The skill sends you back when a cross-phase signature will not write. A signature the
   specification does not fix is a product decision. Go to `/spec`.

## Phase 3 — Decompose into tasks

1. Invoke `Skill(skill="task-structuring")`. Follow it. Do not repeat its rules here.
2. Produce `Decisions`, `Do`, `Files`, `Provides`, and `Verify` for every task.
3. The skill sends you back to the phase boundary when a task will not decompose. Go to Phase 2,
   and redraw it there.

## Phase 4 — Write the plan

Write only `.claude/artifacts/plan/$1/plan.md`. Write it in ASD-STE100 Simplified Technical
English. Keep instruction sentences to 20 words or fewer. Keep descriptive sentences to 25 or
fewer.

Compute the metadata now:

- `Spec SHA-256` — `shasum -a 256 docs/specs/$1.md`, over the raw bytes.
- `Repository commit` — `git rev-parse HEAD`, all 40 characters.
- `Date` — today, as `YYYY-MM-DD`.

Recompute the digest and the commit ID when anything commits during the run. The gate
compares both live.

### The plan is machine input. Write it lean

An LLM executes this document. It reads a task, and it acts. It does not need to be persuaded,
introduced, or reminded.

**Every line must change what the executor does. Delete every line that does not.**

Delete these on sight:

- Rationale, background, and motivation. Why the work matters changes no keystroke.
- Benefits, goals prose, and summaries of what an earlier phase did.
- Restated decisions. Cite `D<n>`. Never repeat the text of a decision.
- Restated rules from `AGENTS.md` or from either skill. Cite the file.
- "Note that", "it is important to", "keep in mind", "as mentioned above".
- Alternatives you considered and rejected.
- Any sentence that would still be true if the task were dropped.

### Output shape

```markdown
# <title> — plan

Spec: docs/specs/<topic>.md
Spec revision: <positive integer>
Spec SHA-256: <64 lowercase hexadecimal characters>
Repository commit: <40-character HEAD ID>
Date: <YYYY-MM-DD>

## Scope boundaries

- <specific boundary>

## Phases

### Phase 1 — <title>
**Goal:** <observable result>
**Stop condition:** <safe-to-ship state>
**Owns files:** `path`, `path`
**Provides:** <cross-phase contract or None>
**Acceptance criteria:**
- [ ] <phase behavior>
- [ ] Full integration gate passes: `make check`

## Tasks

### Task 1.1 — <title>
**Decisions:** D1, D2
**Do:** <complete implementation instruction>
**Files:** create: `path` | modify: `path`
**Provides:** test: `tests/test_x.py::test_name` | make-target: `target`
**Verify:** `make test TEST=tests/test_x.py K=test_name`
```

The three sections appear once, in that order. `task-structuring` requires one field per line.
The gate reads a packed line as one long field, and reports the task as missing the others.

### What the two skills do not tell you

`phase-slicing` owns the phase block. `task-structuring` owns the task fields. These rules come
from the gate, and neither skill carries them:

- The metadata block sits under the title, before the first section.
- **Every task path appears verbatim in its own phase's `Owns files`.** The gate compares exact
  strings. A phase that owns `src/exact/` does not own `src/exact/graph.py`. List each file.
- A `modify:` path exists in the baseline, or an earlier task creates it. A `create:` path does
  neither.
- `Files` and `Provides` separate their kinds with ` | `. Each kind appears once. Paths are
  unique inside a task.
- A provided test is `tests/<file>.py::test_<name>`. A provided Make target is a bare name. **The
  file that holds it must appear in the same task's `Files`,** and a Make target needs `Makefile`
  there.
- `VERBOSE=` accepts `1`. `FILE=` accepts a repository-relative path.
- `Decisions` cites active `D<n>` identifiers from the specification. A superseded or unknown
  identifier fails the gate.
- `TBD`, `TODO`, "to be decided", and a `<!-- tasks: … -->` placeholder are all rejected.

### Write it in steps. Never in one call

One large write degrades the end of the document. The last tasks lose fields and become vague.

1. `Write` the head: the title, the metadata, `## Scope boundaries`, `## Phases` with every phase
   block complete, and `## Tasks` with the tasks of Phase 1 only.
2. Then one `Edit` per remaining phase. Each `Edit` appends that phase's `### Task N.n` blocks
   after the last task already written.
3. Split a phase of more than six tasks into two `Edit` calls.
4. **Never write a placeholder line.** The gate rejects one.
5. The post-write hook runs the full gate after each step. Before the last phase lands, it reports
   `phase N has no task` and `last phase has no task`. Those two findings are expected. Every
   other finding is real. Repair it before the next `Edit`.

### Validate

Run `make plan-check FILE=.claude/artifacts/plan/$1/plan.md`. **Repair every finding before the
review.** The gate resolves every `Files` path, `TEST=` path, `K=` name, `Provides` value,
`Decisions` identifier, and `make` target the plan claims. It checks owned paths for syntax and
reuse only.

## Phase 5 — Independent review (hard gate)

A plan that asserts a false fact about the tree ships a bug that no gate catches.

1. Send ONE `fs-readonly-worker` subagent with fresh context. It holds no Bash and no web tools,
   so it verifies by reading this tree only.
2. Give it two paths: the plan, and `docs/specs/$1.md`. **Copy the delete-on-sight list and the
   20-word and 25-word limits from Phase 4 into the prompt.** A reviewer without the criteria
   applies its own taste.

   | Check | Method |
   |---|---|
   | Each `Files: modify:` path exists | `Glob` |
   | Each `Files: create:` path does not exist | `Glob` |
   | Each symbol a `Do` field names exists | `Grep` for the definition |
   | Each call-site or caller count | `Grep` for the name |
   | Each `make` target in a `Verify` exists | `Grep` the `Makefile` |
   | Every name matches the specification | Read `docs/specs/$1.md` |
   | Every active requirement has a task | Read the specification and the plan |
   | Every cited `D<n>` is active | Read `## Decisions` |
   | No task takes a decision the specification did not take | Read both documents |
   | Every line changes what the executor does | Apply the delete-on-sight list. Quote each line that fails |
   | STE compliance | 20 words for an instruction, 25 for a description |

3. Require this row format: `<task-or-section> → <claim> → <repository evidence> → blocking | non-blocking`.
   **Every row in the table above is blocking.** A leanness finding blocks the same as a wrong
   path.
4. Apply each fix with `Edit`. Never rewrite the plan. Run `make plan-check` again after every
   repair.
5. **STOP instead of claiming approval when no fresh reviewer is available.** A self-review in
   this context is not a review.

Write `.claude/artifacts/plan/$1/review.md` only after the last repair. It carries these exact
metadata lines, plus one row per finding that is still open:

```text
Reviewer: <identity or invocation ID>
Plan SHA-256: <64 lowercase hexadecimal characters>
Date: <YYYY-MM-DD>
Status: Blocking | Approved
```

- `Plan SHA-256` is the digest of the current `plan.md` bytes. **Any later edit to the plan breaks
  it.** Repair, then re-review, then rewrite `review.md`.
- **A repaired finding is not a row.** The gate rejects any row that ends in `→ blocking`, and
  it does not read a repair note. An approved review holds `non-blocking` rows only.
- Set `Status: Approved` only when no blocking finding remains open. While one is open, write
  `Status: Blocking` with its rows, and STOP. `make plan-check` fails on it, and that is correct.
- The gate reads `review.md` whenever it exists. A stale or blocking review fails `make
  plan-check`.

Run `make plan-check FILE=.claude/artifacts/plan/$1/plan.md` one last time. It must be clean.

## Phase 6 — Report

1. Print the plan path, the phase count, the task count, the review status, and the count of
   findings repaired.
2. State the possible next steps. **Do not run them. Do not stage. Do not commit. Do not open a
   pull request.**
   - "Review `.claude/artifacts/plan/$1/` before any code. The directory is gitignored."
   - "Execute Phase 1 of the plan."

## Remember

- You write **three** files, all under `.claude/artifacts/plan/$1/`: `.spec-plan-v1`, `plan.md`,
  and `review.md`. You never create or edit a file under `src/`.
- The specification is the only source of a product decision. A decision you took is a defect.
  Go to `/spec`.
- The two skills own the method. This file owns the gates, the contract, and the review.
- A line that does not change what the executor does is a defect. Delete it.
- One `Write` for the whole plan is a defect. Write the head, then one `Edit` per phase.
- A `review.md` written before the last repair is a defect. The digest proves it.
