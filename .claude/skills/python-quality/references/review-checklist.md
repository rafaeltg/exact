# Review Checklist

Authoritative item list for thorough, large, or unfamiliar reviews. Every unchecked applicable item is either cleared with evidence or filed as a finding. Skipping an applicable item is a failed review.

## Correctness

- [ ] Off-by-one in loops/slices
- [ ] Mutable default arguments
- [ ] Boolean / short-circuit mistakes
- [ ] Missing `await` on coroutines (async code)
- [ ] Naive vs aware datetime mixing
- [ ] `is` vs `==` (identity only for `None` / singletons)
- [ ] Generator exhaustion on reuse
- [ ] Variable shadowing that changes behavior
- [ ] Main path matches stated intent

## Security

- [ ] External inputs validated
- [ ] Secrets absent from logs/errors (`Field(repr=False)`; no keys in fixtures)
- [ ] Injection risks addressed on SQL / command / path surfaces when present
- [ ] `secrets`, not `random`, for tokens
- [ ] User-facing errors do not leak internals

## Performance

- [ ] Collections bounded (respect repo hits/call, topics/wave, and similar limits)
- [ ] No N+1 or repeated identical I/O in a loop
- [ ] No blocking I/O on async paths without `asyncio.to_thread`
- [ ] No string `+=` in loops
- [ ] HTTP clients reused — not constructed per request

## Type safety

- [ ] Public signatures typed
- [ ] No unjustified `Any` across public boundaries
- [ ] `X | None`, not `Optional`, in new/changed code
- [ ] `@override` on Protocol/base implementations
- [ ] Every `# type: ignore` has `[code]` and a reason

## Error handling

- [ ] No bare `except:`
- [ ] No swallow-without-log / policy
- [ ] `raise ... from` on chains
- [ ] Domain errors from business logic — not raw `ValueError`/`RuntimeError` spray
- [ ] `except Exception` only at vendor/tool boundaries with `# noqa: BLE001`
- [ ] No sibling-`except` relied on to catch errors raised inside another handler
- [ ] Retrieval/tool failure still finishes with `errors` / gaps (exact graph)

## Pydantic and boundaries

- [ ] `Field()` constraints on bounded external inputs
- [ ] Secrets use `repr=False`
- [ ] Internal vs external shapes not illegally conflated
- [ ] Settings via pydantic-settings — not ad-hoc `os.environ` sprawl

## Testing

- [ ] No private/protected access from tests
- [ ] Behavior assertions only — no internal call-sequence coupling
- [ ] Mocks only at DI / `Runtime` seams; fakes for multi-step collaborator state
- [ ] No live network
- [ ] Error and edge paths covered
- [ ] Spec-scenario names when behavior is specced — obey `test-design`

## exact-specific (graph / tools)

- [ ] Scout before clarify; questions cite scout titles unless scout empty
- [ ] Research workers isolated via `Send`; parent never sees raw tool I/O
- [ ] Source ids `src_{topic}_{i}`; writer citations resolve; `audit_citations` is code
- [ ] No invented sources; gaps in `uncovered` / `Finding.gaps`
- [ ] Bounds not loosened
- [ ] `docs/spec.md` and `docs/architecture.md` updated when topology, bounds, tools, or citation rules change
