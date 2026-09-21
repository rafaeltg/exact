---
name: test-design
description: >-
  Authoritative rules to write and review pytest tests of specced behavior: boundary analysis,
  spec-scenario test names, behavior over implementation, mocks only at dependency-injection
  seams. Use whenever tests are written or reviewed, with python-quality for the code under
  test.
---

# Test Design

These rules are authoritative. When existing tests in the codebase contradict them, new tests follow these rules; do not copy the surrounding style.

## Test behavior through public APIs — never implementation

- A test exercises the public API of the unit: exported functions, public methods, the compiled graph (`build_graph(...).invoke`), and the CLI entry point (`exact.cli.main`). Never call, patch, or assert on private functions, private methods, name-mangled or underscore-prefixed attributes, or module internals. If a private helper seems to need its own test, that is a design signal — either it belongs in the public contract of its own module, or it is covered through the public caller. Testing it directly is forbidden.
- Assert on observable outcomes: return values, raised exceptions, CLI exit code + stdout/stderr, graph state (`invoke` result, `get_state`) readable through the public API afterwards. Never assert on internal call order, internal call counts, private state, or intermediate variables.
- The refactor test: a correct test survives any refactor that preserves public behavior. If renaming a private method or inlining a helper would break the test, the test is wrong — rewrite it before it ships.

## Mocks — only at dependency-injection seams

- Mock only what is injected: a collaborator passed in through a constructor or function parameter — here, mostly the `Runtime` (`llm`, `extras["exa"]`, `extras["elicit"]`, `tracer`) and CLI parameters such as `checkpointer` and `new_id`. Use the fakes in `tests/fakes.py` (`runtime()`, `FakeLLM`, `FakeExa`, `graph_seed()`); extend them before writing a new stub.
- `unittest.mock.patch` on module internals is forbidden. If you cannot reach a dependency without patching, the code lacks a seam — inject the dependency, then mock it.
- A mock is configured with inputs → outputs of the collaborator's public contract. Asserting "the service called repo.save exactly once with these positional args" couples the test to implementation; asserting "the saved entity is retrievable / the returned object has id X" tests behavior. Verify interactions with a mock only when the interaction IS the contract (e.g., "a notification is sent on approval") — then assert that it happened and with what domain payload, nothing more.
- Never mock the unit under test, value objects, or pure functions. Pure logic is tested directly with real values.
- When a test makes two or more calls whose expected results depend on shared collaborator state, use a hand-rolled fake (an in-memory implementation of the Protocol), never a Mock. Mock objects are for single-interaction stubs only.

## Deriving the tests

- Test names come from spec scenarios verbatim: a spec bullet "a dangling `src_` citation appends an audit section" becomes `test_dangling_src_citation_appends_audit_section`. Traceability over cleverness; a reader maps suite to spec without opening the bodies.
- For every numeric boundary in the spec, test the triple: the boundary, one unit below, one unit above (e.g. clarify turns 2, 3, 4 against a ceiling of 3). Do the arithmetic against the spec's table, not against the implementation.
- For every enum and every error rule, one test per branch — the rejection paths are separate tests (an effort mismatch on resume, a resumed finished thread, and a dangling citation are three tests, not one), each asserting the outcome (exit code, `errors`, `gaps`) AND that no state change leaked.
- Parametrize boundary triples and enum sweeps (`pytest.mark.parametrize`); everything else is one behavior per test function with a body readable in isolation.

## Layering

- Pure functions and domain logic: exhaustive direct unit tests with real values.
- Graph: drive `build_graph(runtime(...))` with `graph_seed(...)` and a `thread_id` config. Test routing, interrupts, `Send` fan-out, and state reducers; retrieval failures must still finish the graph with `errors` and `gaps`.
- CLI: one happy path plus each error path through `main([...], runtime=..., checkpointer=InMemorySaver())` with `capsys`. Assert exit code and output. Do not re-test graph or pure-function logic through the CLI — the CLI tests argument parsing, wiring, and exit-code mapping.
- Every test builds its own fixtures; no test depends on another test's side effects or on execution order.

## Test honesty

- A test that never failed during development is unverified. Mutate one branch of the implementation, confirm the test fails, revert. Do this at least once per spec-derived behavior — any behavior a spec bullet, boundary row, or active decision (`D<n>`) in `docs/specs/<topic>.md` names.
- Tests are deterministic: no wall-clock reads (inject the clock and fix it), no real network, no unseeded randomness, no sleeps. A flaky test is a failing test.
- Never assert a value the test computed from the same code path it is testing. Expected values are literals derived from the spec.
- A failing test is never weakened, skipped, or deleted to reach green. It is either revealing a code bug (fix the code) or a wrong expectation traceable to a spec/assumption change (fix the test and cite the assumption).
