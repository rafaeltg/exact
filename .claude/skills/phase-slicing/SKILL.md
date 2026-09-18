---
name: phase-slicing
description: |
  TRIGGER: breaking an implementation into phases — "how should I split this", "what order should I build this in", "break this into milestones", phase ordering, vertical slicing, phase-safe boundaries, cross-phase contracts.
  EXCLUDE: task-level decomposition inside a phase (use task-structuring); requirement extraction from a messy ticket or thread.
  SIGNAL: drawing the boundaries between phases that group files and declare interfaces.
---

# Phase Slicing Expert

This skill is about one decision: **where to draw the line between phases.** A good split lets you stop after any phase and still have a working, valuable system. A bad split creates a house of cards where nothing works until everything works.

Phases are not arbitrary chapters in a plan. They are commit boundaries — points where the codebase has to be green, deployable, and useful on its own. The reason vertical slicing matters isn't aesthetic; it's that horizontal slicing (all models, then all services, then all APIs) maximises the time the system spends in a half-built state, where bugs hide in incomplete pipelines and rollback means giving up everything.

## The core test: stop-after-this-phase

For every phase you draw, ask:

> If the team stops here and never builds the next phase, is the system still working and worth shipping?

- **Yes** → the phase is a real vertical slice.
- **No** → the phase is scaffolding pretending to be a slice. Merge it with whatever phase finally makes it useful.

This single question catches most slicing mistakes. A phase titled "Add user model and repository" usually fails the test — a model nobody calls is dead weight. The fix is to grow that phase until it includes the first caller (e.g., the signup endpoint) so the slice actually delivers an observable behavior.

The point is risk reduction. Any phase that fails this test means the team has accepted a window of time where the system is broken, and broken windows hide bugs.

## What a vertical slice contains

A vertical slice cuts through every layer needed for one piece of behavior:

- The schema/model change for that behavior
- The service or business logic for that behavior
- The entry point (API, CLI, UI) that exposes it
- The tests that prove it works

A slice does not have to include *every* future caller, *every* edge case, or *every* UI polish — just enough that the behavior works end-to-end for at least one realistic path.

### Common shapes that look like slices but aren't

- **Type-only phase** ("Add all TypeScript types for the feature") — no behavior, no value if you stop.
- **Schema-only phase** ("Run the migration and add models") — tables nobody reads or writes are inert.
- **Setup phase** ("Wire up the new module and register it") — the wiring exists but routes nothing.
- **Test-only phase** ("Add the integration test suite") — tests for code that doesn't exist yet.

When you see one of these, look for the smallest change in a later phase that would make it useful, and pull that change into the same phase.

## When horizontal phasing is justified

Sometimes the language, type system, or schema physically forbids a vertical slice. In those cases a horizontal phase is fine — but document the constraint so reviewers can verify it's real.

Legitimate cases:

- **Closed type unions / exhaustive maps**: Adding a value to a TypeScript discriminated union, or a key to a `Record<Enum, ...>`, forces every consumer to handle the new case in the same commit. You cannot split the enum addition from the map updates.
- **Multi-table migrations with foreign keys**: A migration that introduces parent and child tables with FK constraints often has to be one atomic step.
- **Shared graph state**: A new field on `ExactState`, or a new key a node writes, forces every reader to handle it in the same commit. You cannot split the field from the readers.
- **Shared build configuration**: A change to a tsconfig path alias or a Python package layout that affects every module simultaneously.

Two rules to keep horizontal phases honest:

1. **Make it as small as possible.** If the constraint only forces *some* of the changes to be atomic, don't sweep extra unrelated work into the same phase.
2. **Write the constraint into the phase.** State explicitly *why* this phase is horizontal (e.g., "Type-system constraint: enum value and exhaustive map must land together"). A future reader should be able to verify or challenge that constraint.

## Phase ordering

### Across phases

Order by dependency first, then by risk and value:

1. **Dependencies first** — each phase's inputs must come from earlier phases. Models before services that read them. Shared utilities before modules that import them. Interfaces before the implementations that satisfy them.
2. **Risk-ordered when dependencies allow** — when two phases are independent, do the riskier one first. Failing fast on the unknown lets you adjust the rest of the plan before sunk cost grows.
3. **Value-ordered as the tiebreaker** — if neither risk nor dependency forces an order, ship the slice that delivers more user-observable value first.

### Capstone check

Walk through the phase list in order and mentally apply each phase. After every phase, the system should:

- Compile and run.
- Pass its existing tests.
- Be deployable without coordinated rollouts of later phases.

If a phase forces a coordinated rollout to stay green ("we have to deploy phases 2 and 3 together"), that's two phases pretending to be separate. Either merge them or insert a compatibility shim.

## Cross-phase contracts

When phase 2 depends on something phase 1 produces (a function, a type, a module export), the producing phase has to **declare that interface explicitly** in its outputs. Not "phase 2 will use whatever phase 1 builds" — that's an implicit contract, and implicit contracts drift.

For each cross-phase dependency, record:

- **What** the consumer needs (a function name, a type, an event payload).
- **The signature** — parameter names and types, return type, error modes.
- **Invariants** — what must be true after the producing phase ships (e.g., "the function is non-blocking", "the type is exhaustive over status values").
- **Verification** — the producing phase's acceptance criteria must include a test that exercises the interface, not just internal behavior.
- **Design DoD** — when the producing phase introduces a module, class, or Protocol: its responsibility in one sentence without "and", and the fake in `tests/fakes.py` that exercises it. See `python-quality` § [Design — landmines](../python-quality/SKILL.md#design--landmines).

If you can't write the interface down concretely in the producing phase, the design isn't ready — go back and refine before drawing phases.

### Phase-locking constraints in this repo

Some artifacts here LOCK on merge — a phase that ships one commits every later phase to it:

- **The complexity baseline is a per-commit gate, not a merge gate.** The git pre-commit hook runs `make complexity-check`. `.cursor/hooks/complexity-guard.py` owns the budgets. The tree must hold no function over budget. A commit that leaves one over budget therefore fails before CI sees it. **Never park a function over budget for a later phase to fix.** Plan the extraction, and the split it enables, into the same phase.
- **`docs/spec.md` and `docs/architecture.md` are the contract.** A phase that changes graph topology, bounds, tools, or citation rules must update both documents in the same change. A later phase cannot correct a shipped contract without a new contract change.
- **Graph state is a shipped interface.** A phase that adds or reshapes a field on `ExactState`, or on a model in `src/exact/models.py`, binds every later node that reads it. Treat a state-shape change as an explicit cross-phase interface.
- **The SQLite checkpointer persists state between runs.** A phase that changes the stored shape must say how an existing `exact.sqlite` behaves. Never split one state-shape change across phases.
- **Bounds do not loosen.** Clarify turns, research waves, topics per wave, tool rounds per worker, and hits per call have fixed ceilings in `AGENTS.md`. No phase raises one.

## Scope boundaries at the structure level

The structure document inherits scope boundaries from the spec and design, but it adds new ones tied to phase choices. Examples:

- "Phase 1 does not migrate existing data — only new records use the new schema."
- "Phase 2 does not change the public API surface — additive fields only."

Each boundary should be **specific enough to reject an out-of-scope request during planning**. "Does not include unrelated features" fails this test; it doesn't help anyone reject anything.

## Verification checkpoints per phase

Each phase needs at least one concrete, executable verification command. Vague criteria ("ensure it works") leak past reviewers and fail in production.

A good checkpoint:

- **Is executable** — `make test TEST=tests/test_clarify.py K=test_academic_signal_is_true_for_spec_heuristics`, `make lint && make test`, not "run the tests".
- **Detects partial failure** — reports what passed and what failed, so the team can decide whether to proceed or stop.
- **Doesn't corrupt earlier phases** — a failed checkpoint for phase 3 should not require rolling back phases 1 and 2.

Pair the scoped checkpoint with a broad integration gate (full test suite, full type-check). The scoped one proves the phase did its job; the broad one proves the phase didn't break something else.

## File assignment rules

- **Every file from the design's Changes section appears in exactly one phase.** No file split across phases, no file orphaned.
- **A file's tests live in the same phase as the file's code.** Splitting them produces a phase that can't actually be verified on its own.
- **Tightly coupled files belong together.** If file A only exists to be called by file B, putting them in different phases creates a phase that has nothing exercising the new code.

## Common slicing mistakes

### "Setup phase"

A phase that does plumbing (registering modules, scaffolding config) without exercising any new behavior. Fails the stop-after-this-phase test.

*Fix:* Don't draw the boundary until the plumbing is connected to a real caller, even a minimal one.

### "Big-bang final phase"

A trail of small phases ("add types", "add models", "add service") leading to a final phase that wires everything together. The earlier phases are technically green but useless; the final phase is huge and risky.

*Fix:* Reverse the bias. Start with a minimal end-to-end slice and grow capability slice by slice. Each slice replaces a hard-coded value or a stub with a real implementation.

### "Hidden coupling between phases"

Two phases that look independent but actually rely on each other implicitly — phase 2 reads a config flag phase 1 sets, phase 1's tests assume an endpoint phase 2 will add.

*Fix:* Either declare the coupling as a cross-phase contract and verify it at the producing phase, or restructure so the coupling lives inside one phase.

### "Tests-later phase"

A phase that adds behavior, with a follow-up phase to add the tests. The first phase's verification can only be a type-check, which doesn't prove the behavior works.

*Fix:* Tests live with the code that produces the behavior. Always.

## Author checklist

Before finalizing a structure document:

- [ ] Every phase passes the stop-after-this-phase test (or the horizontal-phasing constraint is documented and minimal).
- [ ] Phase ordering follows dependencies; risk and value break ties.
- [ ] Each phase has at least one concrete verification checkpoint.
- [ ] Cross-phase interfaces are declared in the producing phase's contract with signatures and invariants.
- [ ] Every file from the design appears in exactly one phase.
- [ ] Code and tests for the same behavior are never split across phases.
- [ ] Scope boundaries at the structure level are specific enough to reject out-of-scope requests.
- [ ] After mentally walking the phases in order, each leaves the system green and deployable.
- [ ] No phase leaves a function over the complexity budget for a later phase.
- [ ] Every new module, class, or Protocol in a cross-phase contract states its one-sentence responsibility and its test fake.
