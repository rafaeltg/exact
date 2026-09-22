---
description: Create a repository-grounded implementation plan from a ready specification.
argument-hint: "<topic-slug>"
---

Create a plan for topic `$1`.

The only specification is `docs/specs/$1.md`. Do not search for another specification. Do not
accept free-text product decisions. Do not create `assumptions.md`, `gaps.md`, or `contract.md`.
If a product decision is missing, stop and return the requirement and repository evidence to
`/spec`.

Before writing:

1. Run `make plan-init TOPIC=$1`. Stop on any finding.
2. It gates the slug, the Ready specification, the tree and the topic directory. It writes the
   workflow marker and prints the five metadata lines of the plan head.
3. Ask whether to replace the plan when it reports a stale topic directory.
4. Load `phase-slicing` before drawing phases.
5. Load `task-structuring` before writing tasks.

Write only `.claude/artifacts/plan/$1/plan.md` and, after independent review, `review.md`.
Copy the metadata lines that `make plan-init` printed. Do not recompute them.
Use the exact plan format below. Keep all task fields on one physical line.

```markdown
# <title> — plan

Spec: docs/specs/$1.md
Spec revision: <integer>
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

Rules:

- Every task has `Decisions`, `Requirements`, `Do`, `Files`, `Provides`, and `Verify`.
- Every active requirement of the specification needs at least one task that cites it.
- Use one simple backticked `make` Verify command. Do not use shell operators or Make options.
- `K=` is one identifier. Do not use boolean pytest expressions.
- A task may consume a file, test, or Make target from the baseline or an earlier task.
- A task may provide a test or Make target for itself and later tasks.
- A task cannot consume a later task's output.
- A task-level Verify cannot be bare `make check`.
- Do not leave a placeholder or draft marker.
- Do not repeat decision text. Reference active decision IDs.

Run `make plan-check FILE=.claude/artifacts/plan/$1/plan.md`. Repair every finding before review.
Ask for a fresh independent review. If no fresh reviewer is available, stop instead of claiming
approval. Record `review.md` with these exact metadata lines:

```text
Reviewer: <identity or invocation ID>
Plan SHA-256: <64 lowercase hexadecimal characters>
Date: <YYYY-MM-DD>
Status: Blocking | Approved
```

Add rows in this form:

```text
<task-or-section> → <claim> → <repository evidence> → blocking | non-blocking
```

Set `Status: Approved` only when no blocking row remains and the review digest matches the plan.
Run `make plan-check` again after every review repair.
