---
name: task-structuring
description: |
  TRIGGER: breaking a phase or feature into concrete implementation tasks — "break this down", "what should I work on first", "give me ordered subtasks", expanding a ticket or phase into single-concern tasks with Do / Files / Verify fields.
  EXCLUDE: drawing phase boundaries (use phase-slicing); requirement extraction from a messy ticket or thread.
  SIGNAL: decomposing the inside of a phase into committable tasks that pair code with tests.
---

# Task Structuring Expert

A phase tells you *what ships together*. This skill tells you *how to break that phase into a stack of commits a developer can land one at a time without ever taking the system out of green.*

Tasks are the unit of work the implementer actually executes. Too big: a risky merge. Too small: overhead crushes the schedule. Implementation with no test: the next task inherits the doubt.

The phase already exists when this skill applies. Slicing decisions (where phase boundaries go, what phases ship in what order) belong to the structure stage and to `phase-slicing`. Here you are decomposing the *inside* of a phase.

## What a good task looks like

A good task is **single-concern, self-contained, and independently committable**:

- **Single-concern** — one coherent change. "Create the model AND wire the service AND add the endpoint" is three tasks pretending to be one.
- **Self-contained** — the code change and its tests are in the same task. Never separate them.
- **Independently committable** — after this task, the codebase compiles, the test suite is green, and no half-built feature is visible to users.

The "independently committable" property is the load-bearing one. It means a reviewer can merge this PR on its own merits, and if the project pauses tomorrow, nothing is broken.

## The two non-negotiables

### Code and tests ship together

Splitting "implement X" from "write tests for X" creates a window where X exists without a verification path. The next task inherits the question of whether X actually works. This is how regressions sneak in.

- **Good**: Task 1.1 — create `UserService.create()` and `tests/services/test_user_service.py::test_create`.
- **Bad**: Task 1.1 — create `UserService.create()`. Task 1.2 — write its tests.

A test for an existing untouched function does not count as "code+tests together". If a task adds behavior, the test for that new behavior lives in the same task.

### No planned-red language

A task that admits the system will be broken at the end of it is a task that has accepted a window where bugs hide. Phrases that signal this trap:

- "will fail until phase 2"
- "expected to fail"
- "placeholder for now"
- "atomic batch with task X.Y" (means two tasks must land together — they are actually one task)
- "tests pass only after task X.Y"

Every task leaves the system green. If you find yourself wanting to write planned-red language, the underlying problem is that two tasks are really one task, or the phase boundary is in the wrong place. Fix the structure rather than the words.

## Writing the Do field

The Do field is what a developer will read at 11pm on a deadline. It has to be specific enough that they don't have to go re-read the design to act on it.

Include the concrete artifacts the change will introduce: file paths, function and method signatures, parameter names and types, return shapes, and the key piece of logic that distinguishes this from any other function with the same name.

**Good** — a developer can implement this from the Do field alone:

> Add `async def get_user_metrics(user_id: UUID) -> MetricsResponse` to `src/services/metrics.py`. Query the `user_events` table filtering by `user_id` and `event_type IN ('login', 'export')`. Return `MetricsResponse(total_events=count, last_event=max_timestamp)`.

**Bad** — vague enough to mean five different implementations:

> Implement the metrics service method.

The point is not bureaucratic detail. The point is that the design document was where decisions got made; the plan is where those decisions become implementable, so the decisions need to be carried forward concretely. If you can't write a specific Do field, the design didn't decide enough — go back instead of guessing.

Name **every** participating field when a Do field gives a key, a tuple, a filter or a comparison. A dedupe key that names two of its four fields ships a silent bug. No test catches it.

## Writing the Verify command

Each task gets a verification command that proves *this task's change* works. Not "run the whole suite" — that's the phase's integration gate. The task-level Verify is targeted and fast.

**Good** — runs the specific test the task added (inline form for one command; in this repo tests run through `make test`, never bare `pytest`):

```markdown
**Verify:** `make test TEST=tests/test_research.py K=test_research_agent_returns_only_pruned_deltas`
```

**Bad** — runs everything and tells you nothing about whether this change worked:

```markdown
**Verify:** `pytest`
```

A good Verify command:

- Names the test file or test case introduced by this task.
- Uses real, runnable commands from the project (check the Makefile or `package.json`).
- Follows the project's test path conventions (e.g., `test_*.py` vs. `*.test.ts`).

If the project has no convention for the test layer the task touches, surface that as a gap rather than inventing one.

**Repo-specific Verify rules** — tasks touching these surfaces carry the matching gate:

- **Any test Verify:** `make test TEST=<path>` — optionally `K=<keyword>` to narrow and `VERBOSE=1` for `-vv -x`. A bare `pytest` Verify may not run inside the project's uv environment; write `make test TEST=…`.
- **Complexity budget:** keep every function a task touches inside the guard budgets. `.cursor/hooks/complexity-guard.py` owns the numbers. Never restate them. `make complexity-check` fails on any function over budget, and the git pre-commit hook runs it. It therefore rejects the commit. **Two changes are ONE task when the first pushes a function over budget until the second lands.** Extract the new named unit and split the function it shrinks in one commit.
- **Contract changes:** a task that changes graph topology, bounds, tools, or citation rules must update `docs/spec.md` and `docs/architecture.md` in the same task. Name both files in the Files field.
- **Graph or node changes:** the Verify must exercise the node through the graph, not through a private helper. Tests use `tests/fakes.py`; no task adds live network to pytest.
- **Full gate:** `make check` runs lint, format-check, complexity, and tests. Use it for the final task of a phase, not for every task — a targeted `make test TEST=…` is the better per-task Verify.

### When a task needs multiple Verify commands

Prefer a single targeted command. When that's genuinely insufficient — for example, when a task introduces both a unit test and an integration test that must both pass — use either a fenced block or a bullet list:

````markdown
**Verify:**
- `make test TEST=tests/test_research.py` — the node's own tests
- `make test TEST=tests/test_graph.py` — the wiring the node changed
````

````markdown
**Verify:**
```bash
make test TEST=tests/test_research.py
make test TEST=tests/test_graph.py
```
````

Both shapes are equivalent: the implementer runs each command in order and the task only passes when all pass. If you find yourself listing more than two or three commands, the task is too large — split it.

## Phase acceptance criteria

A phase's Acceptance Criteria sit above the tasks. They include:

- **Targeted criteria** for the phase's specific behavior (often a couple of bullet points naming the user-observable outcomes).
- **A broad integration gate** that catches regressions across the codebase, written exactly as: `- [ ] Full integration gate passes: \`<command>\``.

The per-task Verify proves *this task did its job*. The phase integration gate proves *the tasks together didn't break something else*. Both are needed; neither replaces the other.

## Risk-ordered task sequencing within a phase

Inside a phase, tasks still have to respect their own dependency order — types before code that uses them, models before services that query them, services before the endpoints that call them. Beyond that, when tasks are independent, sequence them by risk:

1. **Most uncertain or technically risky tasks first** — failing fast lets the rest of the phase adjust if the approach was wrong.
2. **Tasks that touch shared / critical code paths** — surfaces conflicts early.
3. **Tasks with external dependencies** (third-party APIs, databases, infrastructure) — fail-fast applies again.
4. **Mechanical and low-risk tasks last** — they're safe to push to the end.

The principle: surface unknowns while you still have time to react.

## Avoiding common task-decomposition traps

### Verification-only tasks

A task whose Files list contains only test entries, or no Files entries at all, isn't a task — it's a checkpoint. Move it into the phase's Acceptance Criteria. Every real task has at least one `create` or `modify` entry in its Files list.

### Grab-bag tasks

A task titled "Misc cleanup and the new endpoint" is two or more tasks. Single-concern doesn't mean small; it means coherent. Refactoring a helper *and* adding a new endpoint are different concerns even if they touch the same file. Split.

### Tasks that depend on later tasks within the same phase

A task that references a file or function created by a later task in the same phase fails the independently-committable test. Either reorder so the producer comes first, or merge them.

### Vague Verify commands

`make test`, `pytest`, `npm test` — these are integration gates, not task-level Verify commands. If you find yourself writing one as a task's Verify, the test you actually want to run hasn't been named yet. Name it.

### Hidden interface breaks

A task that changes a signature shared with callers in the same phase or later phases sneaks coupling into the plan. The compatibility-first sequence: introduce the new signature alongside the old one (adapter), migrate callers task by task, remove the old signature last. Never break an interface in one task and clean it up in another.

## What this skill is *not* for

- **Drawing phase boundaries** — that's the structure stage. Use `phase-slicing`.
- **Deciding what to build** — that's the spec/design stage.
- **Writing implementation code** — the plan describes the work; implementation happens later.

If a task feels impossible to write as single-concern with code+tests together, the most common cause is that the phase boundary is wrong, not that the task needs to be unusual. Push back to the structure stage.

## Author checklist

Before finalizing a plan:

- [ ] Every task is single-concern — one coherent change.
- [ ] Every task is independently committable — system stays green after each task.
- [ ] Code changes and their tests live in the same task — never separated.
- [ ] No planned-red language anywhere — no "will fail until", "atomic batch", "placeholder", "expected to fail".
- [ ] Every task has at least one `create` or `modify` Files entry — no verification-only tasks.
- [ ] Do fields name file paths, function signatures, parameter and return types, and key logic.
- [ ] Verify commands are targeted at the task's specific test, not generic runners.
- [ ] Phase Acceptance Criteria include a broad integration gate exactly as `- [ ] Full integration gate passes: \`<command>\``.
- [ ] Within each phase, tasks are ordered by dependency first, then by risk.
- [ ] No task depends on a file or function created by a later task in the same phase.
- [ ] Every `TEST=` path starts with `tests/` and names a file that exists.
- [ ] Every `K=` filter names a test function that exists in that file.
- [ ] No task leaves a function over the complexity budget for a later task to fix.
- [ ] Every Do field naming a key, tuple, filter or comparison names all participating fields.
