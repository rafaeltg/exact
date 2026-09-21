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

1. Validate `$1` with `^[a-z0-9][a-z0-9._-]*$`.
2. Run `make spec-check-ready FILE=docs/specs/$1.md`.
3. Require a clean tracked repository and no non-ignored untracked files.
4. Require `docs/specs/$1.md` to be tracked and unchanged from `HEAD`.
5. Create `.claude/artifacts/plan/$1/.spec-plan-v1` with exactly `version=1` and a final newline.
6. Stop when the topic directory exists without that marker or has mismatched plan metadata.
7. Load `phase-slicing` before drawing phases.
8. Load `task-structuring` before writing tasks.

Write only `.claude/artifacts/plan/$1/plan.md` and, after independent review, `review.md`.
Compute the specification SHA-256 from its raw bytes. Record the current 40-character `HEAD` ID.
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
**Do:** <complete implementation instruction>
**Files:** create: `path` | modify: `path`
**Provides:** test: `tests/test_x.py::test_name` | make-target: `target`
**Verify:** `make test TEST=tests/test_x.py K=test_name`
```

Rules:

- Every task has `Decisions`, `Do`, `Files`, `Provides`, and `Verify`.
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
