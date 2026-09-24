# exact

CLI Open Deep Research agent on LangGraph. Retrieval is **Exa** only; the Elicit client is dormant. Contract: [docs/spec.md](docs/spec.md). Architecture: [docs/architecture.md](docs/architecture.md).

## Commands

```
make test               # TEST=path[::name] K=expr VERBOSE=1
make lint-fix           # FILE=path for one file
make complexity-report FILE=path  # budget headroom of each function
make check              # the full gate; `make help` lists every target
```

## Hooks

- Claude Code only: after a write to a `.py` file, a hook runs `make lint-fix` on it. The file can change.
- The commit gate checks the staged bytes of a specification. Stage a specification fix before you commit. The complexity gate takes its file list from the index, but it reads each file from the worktree. Do not skip hooks.

## Bounds (do not loosen)

- The `max` profile in `src/exact/config.py` is the ceiling. A default run is `normal`.
- CLI + SQLite checkpointer. No HTTP API, web UI, or extra retrieval vendors
- Out of scope: Firecrawl, MCP product, Elicit Reports, `create_supervisor`, parallel writers, PDF/paywall full text

If you change topology, bounds, tools, or citation rules, update `docs/spec.md` and `docs/architecture.md` in the same change.

## Graph invariants

- Scout before clarify. Questions must cite scout titles unless scout is empty.
- Isolated `research_agent` workers via `Send`. Parent never sees raw tool I/O. Prune to `Finding` before returning.
- Source ids: `src_{topic}_{i}`. Writer citations must resolve; `audit_citations` is code, not an LLM.
- Retrieval failure: append `errors` and `gaps=["lane <focus>: retrieval failed"]`. The graph still finishes.
- `messages` is the clarify thread only.

## Code

- Python 3.12+, `src/exact` layout, `from __future__ import annotations`
- Inject `Runtime` (settings + llm + `extras` for clients). Tests use `tests/fakes.py` — no live network in pytest
- Broad `except Exception` is allowed only at vendor/tool boundaries (`# noqa: BLE001`)
- Do not invent sources. Gaps go in `uncovered` / `Finding.gaps`, not in claims

## Complexity budgets

`.claude/hooks/complexity-guard.py` owns the numbers. Tests are exempt. In Claude Code, a `Write`/`Edit` with a new or worse breach vs HEAD is denied before it reaches disk. The tree must have no over-budget functions. Do not park a breach.

Repair an over-budget function in this order. Stop at the first repair that works.

1. Remove a branch. A condition that cannot be false is dead weight.
2. Replace a nested conditional with an early return.
3. Move a whole responsibility to a new named unit. The caller then stops doing that work.
4. Extract a helper only when the helper has its own reason to exist.

Do not add a boolean parameter to merge two behaviours. Do not pass a bag of state to beat the parameter budget. Do not split a function into two halves that share most of their locals.

## Done when

`make check` is clean.
