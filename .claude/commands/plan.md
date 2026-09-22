---
description: >
  Write .claude/artifacts/plan/<topic>/plan.md — a canonical, phased, task-level plan that an LLM
  executes task by task. The only input is the Ready specification docs/specs/<topic>.md. Takes no
  product decision. A fresh agent reviews the plan against the tree before it is approved.
argument-hint: "<topic-slug>"
allowed-tools: Read, Glob, Grep, Write, Edit, AskUserQuestion, Agent, Task, SendMessage, Skill, Bash(make plan-init*), Bash(make plan-check*), Bash(make complexity-report*), Bash(git status*), Bash(shasum*)
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
the review. **Never re-explain a skill's method here.** The output shape below is the one copy of
the document format. Load each skill at the phase that needs it.

`.cursor/hooks/plan-guard.py` owns the validation rules. `make plan-check` is authoritative. The
lists below help you write; they never replace a run of the gate.

## Phase 0 — Gate the inputs

1. **Validate `$1` against `^[a-z0-9][a-z0-9._-]*$`. STOP when it fails.** Print the slug. It
   reaches a Make recipe and a path, and neither checks it before the shell does.
2. Run `make plan-init TOPIC=$1`. **STOP on any finding.** Print the findings.
3. It gates the slug again, with the Ready specification, the tree, and the topic directory. It
   writes the workflow marker, and it prints the five metadata lines of the plan head.
4. When it reports `(stale)`, the directory holds a plan for another specification. Ask the user
   whether to replace it. STOP on no.

## Phase 1 — Read the contract

1. Read `docs/specs/$1.md` in full.
2. The active `D<n>` and `R<n>` identifiers are the only ones a task may cite. A superseded entry
   is not citable.
3. The specification names are immutable. Use them verbatim.
4. Read `AGENTS.md`, and the code each requirement touches.

## Phase 2 — Draw the phases

1. Invoke `Skill(skill="phase-slicing")`. Follow it. Do not repeat its rules here.
2. Produce the phase list, the cross-phase contracts, and the file-ownership map.
3. **A path belongs to one phase only.** The gate rejects a reused owned path, and it rejects a
   task file outside its own phase's ownership.
4. A cross-phase signature the specification does not fix is a product decision. Go to `/spec`.

## Phase 3 — Decompose into tasks

1. Invoke `Skill(skill="task-structuring")`. Follow it. Do not repeat its rules here.
2. Produce `Decisions`, `Requirements`, `Do`, `Files`, `Provides`, and `Verify` for every task.
3. Run `make complexity-report FILE=<path>` on each Python file a task grows. It prints the
   measured metrics of every function against its budget. Use the headroom to decide the unit
   split. Keep the output for Phase 5.

## Phase 4 — Write the plan

Write only `.claude/artifacts/plan/$1/plan.md`, and write it with `Write` or `Edit` only. **A
Bash write skips the gate hook.** Write in ASD-STE100 Simplified Technical English (`AGENTS.md`).
The gate limits a sentence to 25 words. Keep an instruction to 20.

The metadata block is the five lines `make plan-init` printed. Copy them verbatim. Do not
recompute them, and do not write a plan against a different commit.

A `review.md` left by an earlier run is void the moment you write. Phase 5 replaces it.

### The plan is machine input. Write it lean

An LLM executes this document. It reads a task, and it acts. It does not need to be persuaded,
introduced, or reminded.

**Every line must change what the executor does. Delete every line that does not.**

Delete these on sight:

- Rationale, background, and motivation. Why the work matters changes no keystroke.
- Benefits, and summaries of what an earlier phase did. A `Goal` field states one observable
  result, and nothing else.
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
**Requirements:** R1, R3
**Do:** <complete implementation instruction>
**Files:** create: `path` | modify: `path`
**Provides:** test: `tests/test_x.py::test_name` | make-target: `target`
**Verify:** `make test TEST=tests/test_x.py K=test_name`
```

### What the two skills do not tell you

`phase-slicing` owns the phase block. `task-structuring` owns the task fields. These rules come
from the gate, and neither skill carries them:

- **Every task path appears verbatim in its own phase's `Owns files`.** The gate compares exact
  strings. A phase that owns `src/exact/` does not own `src/exact/graph.py`. List each file.
- A `modify:` path exists in the recorded commit, or an earlier task creates it. A `create:` path
  does neither.
- A provided test is `tests/<file>.py::test_<name>`. A provided Make target is a bare name. **The
  file that holds it must appear in the same task's `Files`,** and a Make target needs `Makefile`
  there.
- **A `Verify` may name only what already exists or was already provided.** Its Make target, its
  `TEST=` path, its `::selector` and its `K=` name each resolve in the recorded commit, or in the
  `Provides` of this task or an earlier one.
- **`Requirements` carries the coverage.** Every active `R<n>` needs at least one task, and a task
  that serves none writes `None`.

### Write it in steps. Never in one call

1. `Write` the head: the title, the metadata, `## Scope boundaries`, `## Phases` with every phase
   block complete, and `## Tasks` with the tasks of Phase 1 only.
2. Then one `Edit` per remaining phase. Each `Edit` appends that phase's `### Task N.n` blocks
   after the last task already written.
3. Split a phase of more than six tasks into two `Edit` calls.
4. **Never write a placeholder line.** The gate rejects one.
5. The post-write hook runs the gate after each step, and it drops the findings that a half-written
   plan always carries. Repair every finding it reports before the next `Edit`.

## Phase 5 — Independent review (hard gate)

A plan that asserts a false fact about the tree ships a bug that no gate catches.

1. Run `make plan-check FILE=.claude/artifacts/plan/$1/plan.md`. **Repair every finding before you
   send a reviewer.** The reviewer is told the gate already proved those facts, so a review over a
   failing gate wastes the round. A `review.md` left by an earlier run is the one exception:
   `review is not Approved` and `review digest does not match plan` stand until you write the new
   file at the end of this phase.
2. Send ONE `plan-reviewer` subagent with fresh context. Give it three things: the plan path,
   `docs/specs/$1.md`, and the `make complexity-report` output from Phase 3. **Do not restate its
   checklist, and do not give it your own criteria.** Its agent file owns both.
3. Repair each blocking row with `Edit`. Never rewrite the plan.
4. Send the repaired task IDs to **the same reviewer** with `SendMessage`. It verifies each repair,
   and reports any regression the repair caused. Repeat from step 3 until it reports no blocking
   row. A continuation round costs about a thirteenth of a fresh round.
5. Send a second fresh `plan-reviewer` only for a plan of more than 10 tasks, and verify its rows
   through step 3 and step 4. Continuations converge on a small plan; a large one earns one pass
   of fresh eyes.
6. **Never send more than two fresh reviewers in one run.** While a blocking row is open after the
   second, write `review.md` with `Status: Blocking` and its rows, and STOP. The user decides.
7. **STOP instead of claiming approval when no fresh reviewer is available.** A self-review in
   this context is not a review.

Write `.claude/artifacts/plan/$1/review.md` only after the last repair. It carries these exact
metadata lines, plus one row per finding that is still open:

```text
Reviewer: <identity or invocation ID>
Plan SHA-256: <64 lowercase hexadecimal characters>
Date: <YYYY-MM-DD>
Status: Blocking | Approved
```

- `Plan SHA-256` is `shasum -a 256` over the current `plan.md` bytes. Any later edit breaks it.
- **A repaired finding is not a row.** The gate rejects any row that ends in `→ blocking`, and
  it does not read a repair note. An approved review holds `non-blocking` rows only.

Run `make plan-check FILE=.claude/artifacts/plan/$1/plan.md` one last time. It must be clean,
unless step 6 stopped with `Status: Blocking`. The gate fails on a Blocking review, and that is
correct. Never flip a review to `Approved` to clear it.

## Phase 6 — Report

1. Print the plan path, the phase count, the task count, the review status, and the count of
   findings repaired.
2. State the possible next steps. **Do not run them. Do not stage. Do not commit. Do not open a
   pull request.**
   - "Review `.claude/artifacts/plan/$1/` before any code. The directory is gitignored."
   - "Execute Phase 1 of the plan."

A product decision you took yourself is a defect. Go to `/spec`.
