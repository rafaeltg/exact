# Review Checklist

Authoritative item list for thorough, large, or unfamiliar reviews. Every unchecked applicable item is either cleared with evidence or filed as a finding. Skipping an applicable item is a failed review.

Sections 1–4 and 12 carry the design contract of `SKILL.md` § Design — landmines. Each item names the landmine it prevents. Omission and over-application both fail: an absent boundary abstraction and a Protocol with one implementation are each a finding. The complexity budgets are not restated here — `.cursor/hooks/complexity-guard.py` owns them and `SKILL.md` § Complexity budgets states them once.

## 1. Responsibility and boundaries

- [ ] Each class is described in one sentence without "and"
- [ ] Each class has one reason to change — one actor, one concern
- [ ] No class split by line count — a cohesive class stays whole; shrinking it by splitting raises coupling
- [ ] `__init__` stays inside the guard's parameter cap (`self` excluded); no state bag passed to beat it — that repair is forbidden (`SKILL.md` § Over-budget functions)
- [ ] Boundary code translates only — `src/exact/tools/` carries retrieval, never research decisions
- [ ] Domain models perform no I/O
- [ ] `utils.py` / `helpers.py` files hold one domain, never a catch-all bucket
- [ ] Configuration, validation, persistence, and prompting live in separate units
- [ ] Each file has a clear theme — the filename predicts the contents
- [ ] No Feature Envy — a function that reads another object's data more than its own belongs to that object

## 2. Dependencies and coupling

- [ ] High-level modules (graph, nodes) do not import a low-level client directly
- [ ] Abstractions exist at architectural boundaries — and nowhere else
- [ ] Dependencies are injected via `Runtime` or constructor, never constructed internally (module-level singleton → injection: `refactoring-patterns.md` §8)
- [ ] The composition root that wires concretes is separate from the logic that uses them
- [ ] No concrete infrastructure type appears in a public signature where a seam belongs
- [ ] Every external integration has a fake in `tests/fakes.py`
- [ ] Settings are injected, never read from the environment inside business logic
- [ ] Modules have high internal cohesion — the elements work toward one purpose
- [ ] Modules have low external coupling — few dependencies, on stable abstractions
- [ ] No circular dependencies between modules
- [ ] A change to one concept stays localised to one or a few modules
- [ ] No Shotgun Surgery — one change does not force edits across many files
- [ ] Data Clumps are extracted into value objects — the same field group repeated is one type

## 3. Abstractions and contracts

- [ ] Each Protocol covers a single concern
- [ ] No Protocol, Strategy, or Factory with a single implementation and no second real case
- [ ] No one-method interface cut from a cohesive Protocol — split only when consumers use distinct subsets
- [ ] Consumers depend only on the interface slice they use
- [ ] No implementor raises `NotImplementedError` for an interface method
- [ ] Related but distinct operations sit in separate Protocols — Reader and Writer, Querier and Mutator
- [ ] No Protocol combines query and command operations that consumers use independently
- [ ] No abstraction leaks its implementation — a seam that demands vendor-specific arguments is not a seam
- [ ] Subclasses honour the parent's behavioural contract — same preconditions, same postconditions
- [ ] No subclass raises `NotImplementedError` on an inherited method
- [ ] Subclasses do not narrow parameter types
- [ ] Subclasses do not widen return types or exceptions beyond the parent's contract
- [ ] Read-only variants do not extend read-write interfaces — the Protocols are separate
- [ ] Tests written for the parent pass against any subclass
- [ ] No marker subclass that exists only to be `isinstance`-checked elsewhere

## 4. Extensibility

- [ ] No if/elif chain switching on type or a string discriminator that grows with each new variant
- [ ] No `isinstance` chain used for dispatch — polymorphism or a registry when other modules add variants, `match/case` when this module owns a closed set
- [ ] Extension points exist where variation is real, and nowhere it is speculative
- [ ] New behaviour arrives by adding code, not by editing tested code
- [ ] Enum dispatch uses a mapping or registry, never if/elif
- [ ] Base classes are stable — a change to a base does not cascade to every subclass

## 5. Correctness

- [ ] Off-by-one in loops/slices
- [ ] Mutable default arguments
- [ ] Boolean / short-circuit mistakes
- [ ] Missing `await` on coroutines (async code)
- [ ] Naive vs aware datetime mixing
- [ ] `is` vs `==` (identity only for `None` / singletons)
- [ ] Generator exhaustion on reuse
- [ ] Variable shadowing that changes behavior
- [ ] Main path matches stated intent

## 6. Security

- [ ] External inputs validated
- [ ] Secrets absent from logs/errors (`Field(repr=False)`; no keys in fixtures)
- [ ] Injection risks addressed on SQL / command / path surfaces when present
- [ ] `secrets`, not `random`, for tokens
- [ ] User-facing errors do not leak internals

## 7. Performance

- [ ] Collections bounded (respect repo hits/call, topics/wave, and similar limits)
- [ ] No N+1 or repeated identical I/O in a loop
- [ ] No blocking I/O on async paths without `asyncio.to_thread`
- [ ] No string `+=` in loops
- [ ] HTTP clients reused — not constructed per request

## 8. Type safety

- [ ] Public signatures typed
- [ ] No unjustified `Any` across public boundaries
- [ ] `X | None`, not `Optional`, in new/changed code
- [ ] `@override` on Protocol/base implementations
- [ ] Every `# type: ignore` has `[code]` and a reason

## 9. Error handling

- [ ] No bare `except:`
- [ ] No swallow-without-log / policy
- [ ] `raise ... from` on chains
- [ ] Domain errors from business logic — not raw `ValueError`/`RuntimeError` spray
- [ ] `except Exception` only at vendor/tool boundaries with `# noqa: BLE001`
- [ ] No sibling-`except` relied on to catch errors raised inside another handler
- [ ] Error handling stays separate from business logic — each layer handles or translates the layer below
- [ ] Retrieval/tool failure still finishes with `errors` / gaps (exact graph)

## 10. Pydantic and boundaries

- [ ] `Field()` constraints on bounded external inputs
- [ ] Secrets use `repr=False`
- [ ] Internal vs external shapes not illegally conflated
- [ ] Settings via pydantic-settings — not ad-hoc `os.environ` sprawl

## 11. Testing and testability

- [ ] No private/protected access from tests
- [ ] Behavior assertions only — no internal call-sequence coupling
- [ ] Mocks only at DI / `Runtime` seams; fakes for multi-step collaborator state
- [ ] No live network
- [ ] Error and edge paths covered
- [ ] Spec-scenario names when behavior is specced — obey `test-design`
- [ ] No module-level side effect that runs on import
- [ ] Every architectural boundary has a seam a test double can take
- [ ] Pure functions where the work is a computation — no side effect, deterministic
- [ ] Time, randomness, and I/O are injected, never called from business logic
- [ ] A test that needs a wall of setup is a coupling finding, not a test finding
- [ ] Each class has one clear seam for isolation — constructor injection, no hidden dependency

## 12. Clean Code and smells

### Functions

- [ ] Every function stays inside the guard budgets — `SKILL.md` § Complexity budgets (`.cursor/hooks/complexity-guard.py` owns the numbers)
- [ ] Each function does one thing at one level of abstraction
- [ ] No high-level orchestration mixed with low-level detail in one body
- [ ] A parameter list that needs a comment to read is a parameter object
- [ ] No boolean parameter used to merge two behaviours
- [ ] Guard clauses used for preconditions — early return instead of deep nesting

### Naming

- [ ] Class names are nouns that state the responsibility — `Manager`, `Handler`, `Processor`, `Helper` without context is a finding
- [ ] Function names are verbs that state what happens
- [ ] Booleans use `is_` / `has_` / `can_` / `should_`
- [ ] No abbreviation beyond `id`, `url`, `http`, `llm`, and equally universal terms
- [ ] Names communicate intent without implementation knowledge
- [ ] One vocabulary across the codebase — `create` / `make` / `build` not mixed for one concept

### Structure

- [ ] Command-Query Separation: a function changes state or returns data
- [ ] No hidden side effect — the name reflects every effect
- [ ] DRY by knowledge — one business rule in one place; two blocks that carry different concepts stay apart
- [ ] No premature abstraction — Rule of Three
- [ ] Composition carries behaviour reuse
- [ ] Inheritance only for behavioural is-a, a framework base, or an interface-only base
- [ ] Mixins stay minimal and focused — a mixin past a few methods is a service to inject
- [ ] Protocols used over ABC for interface definitions
- [ ] No multiple-inheritance diamond
- [ ] Objects are told what to do, never queried for state and acted on from outside
- [ ] No chain-calling through behaviour-rich objects (`a.b.c.d`) — Pydantic models and DTOs are exempt, they are meant to be traversed
- [ ] Decision logic sits in the object that owns the data
- [ ] Methods talk only to immediate collaborators — own object, parameters, created objects, direct dependencies
- [ ] No Primitive Obsession — email, money, and date ranges are value objects
- [ ] No Speculative Generality — abstractions exist for a current need
- [ ] No Middle Man — a class that delegates everything adds nothing
- [ ] No Refused Bequest — a subclass that ignores most of the parent
- [ ] No Message Chain on a domain object

## 13. exact-specific (graph / tools)

- [ ] Scout before clarify; questions cite scout titles unless scout empty
- [ ] Research workers isolated via `Send`; parent never sees raw tool I/O
- [ ] Source ids `src_{topic}_{i}`; writer citations resolve; `audit_citations` is code
- [ ] No invented sources; gaps in `uncovered` / `Finding.gaps`
- [ ] Bounds not loosened
- [ ] `docs/spec.md` and `docs/architecture.md` updated when topology, bounds, tools, or citation rules change
