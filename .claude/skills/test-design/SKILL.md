---
name: test-design
description: Use when writing or reviewing tests for any specced behavior — boundary analysis, spec-scenario naming, behavior-vs-implementation discipline, mocking at DI seams. Applies to unit and API tests alike.
---

# Test Design

These rules are authoritative. When existing tests in the codebase contradict them, new tests follow these rules; do not copy the surrounding style.

## Test behavior through public APIs — never implementation

- A test exercises the public API of the unit: exported functions, public methods, HTTP endpoints. Never call, patch, or assert on private functions, private methods, name-mangled or underscore-prefixed attributes, or module internals. If a private helper seems to need its own test, that is a design signal — either it belongs in the public contract of its own module, or it is covered through the public caller. Testing it directly is forbidden.
- Assert on observable outcomes: return values, raised exceptions, response status + body, state readable through the public API afterwards. Never assert on internal call order, internal call counts, private state, or intermediate variables.
- The refactor test: a correct test survives any refactor that preserves public behavior. If renaming a private method or inlining a helper would break the test, the test is wrong — rewrite it before it ships.

## Mocks — only at dependency-injection seams

- Mock only what is injected: a collaborator passed in through a constructor, function parameter, or FastAPI dependency, standing behind an interface you own (a Protocol/ABC — repository, clock, notifier, external client).
- `unittest.mock.patch` on module internals is forbidden. If you cannot reach a dependency without patching, the code lacks a seam — inject the dependency, then mock it.
- A mock is configured with inputs → outputs of the collaborator's public contract. Asserting "the service called repo.save exactly once with these positional args" couples the test to implementation; asserting "the saved entity is retrievable / the returned object has id X" tests behavior. Verify interactions with a mock only when the interaction IS the contract (e.g., "a notification is sent on approval") — then assert that it happened and with what domain payload, nothing more.
- Never mock the unit under test, value objects, or pure functions. Pure logic is tested directly with real values.
- When a test makes two or more calls whose expected results depend on shared collaborator state, use a hand-rolled fake (an in-memory implementation of the Protocol), never a Mock. Mock objects are for single-interaction stubs only.

## Deriving the tests

- Test names come from spec scenarios verbatim: a spec bullet "same EIN, different address must merge" becomes `test_same_ein_different_address_merges`. Traceability over cleverness; a reader maps suite to spec without opening the bodies.
- For every numeric boundary in the spec, test the triple: the boundary, one unit below, one unit above. Money boundaries use the smallest currency unit. Do the arithmetic against the spec's table, not against the implementation.
- For every enum and every error rule, one test per branch — the rejection paths are separate tests (400 vs 404 vs 409 are three tests, not one), each asserting status AND that no state change leaked.
- Parametrize boundary triples and enum sweeps (`pytest.mark.parametrize`); everything else is one behavior per test function with a body readable in isolation.

## Layering

- Pure functions and domain logic: exhaustive direct unit tests with real values.
- Endpoints: one happy path plus each error path through the test client (`httpx` / `TestClient`), with injected fakes at the seams. Do not re-test the pure function's arithmetic through HTTP — the endpoint tests wiring, validation, and status mapping.
- Every test builds its own fixtures; no test depends on another test's side effects or on execution order.

## Test honesty

- A test that never failed during development is unverified. Mutate one branch of the implementation, confirm the test fails, revert. Do this at least once per spec-derived behavior — any behavior a spec bullet, boundary row, or A-entry in docs/assumptions.md names.
- Tests are deterministic: no wall-clock reads (inject the clock and fix it), no real network, no unseeded randomness, no sleeps. A flaky test is a failing test.
- Never assert a value the test computed from the same code path it is testing. Expected values are literals derived from the spec.
- A failing test is never weakened, skipped, or deleted to reach green. It is either revealing a code bug (fix the code) or a wrong expectation traceable to a spec/assumption change (fix the test and cite the assumption).
