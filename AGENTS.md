# exact

CLI Open Deep Research agent on LangGraph. Tools are **Exa** only; the Elicit client is dormant. Clarification is grounded in an Exa scout. Contract: [docs/spec.md](docs/spec.md) v1.4. Architecture: [docs/architecture.md](docs/architecture.md).

## Commands

```
make setup              # uv sync --extra dev + install-hooks
make test               # TEST=path K=expr VERBOSE=1
make lint / lint-fix
make format / format-fix   # FILE=path for one file
make complexity-check
make complexity-report FILE=path  # budget headroom of each function
make imports-check       # fail on any import cycle inside exact
make spec-check FILE=path  # validate one docs/specs/ specification
make spec-check-ready FILE=path  # require a committed Ready specification
make spec-check-index FILE=path  # validate staged specification bytes
make spec-check-all       # validate all tracked docs/specs/ specifications
make plan-check FILE=path  # validate a canonical .claude/artifacts/plan/ plan
make plan-init TOPIC=slug  # gate /plan inputs and print the plan metadata
make workflows-check    # syntax-check .claude/workflows/*.js
make check              # lint + format + specs + complexity + imports + workflows + pi + tests
make clean
```

Install hooks once after clone (`make setup` or `make install-hooks`). Commits then run `make lint-fix` (with re-stage), `make spec-check-index` over every tracked
specification, `make complexity-check` and `make imports-check`. Do not skip hooks.

`make check` reads the worktree; the commit gate reads the index. Stage a specification fix before
you commit, or the commit gate still sees the committed bytes.

Editor: Python format + lint-fix on save via the Ruff extension (`.vscode/settings.json`). Agent `Write`/`StrReplace` hit `make complexity-pre` first (deny before disk). After an allowed write, `afterFileEdit` runs `scripts/hooks/post-edit.sh` → `make lint-fix FILE=…`. `TabWrite` gets `make complexity-post` via `postToolUse`. After a `Bash` call,
`scripts/hooks/post-bash.sh` runs the complexity gate, the specification gate on a changed
`docs/specs/` file, and the plan gate on a plan the workflow opened. A shell write therefore
reaches the same gates a `Write` reaches.

## Bounds (do not loosen)

- Ceilings are the `max` profile: clarify turns ≤ 3; research waves ≤ 4; topics/wave ≤ 4 (follow-up ≤ 3); tool rounds/worker ≤ 6; hits/call ≤ 8. A default run is `normal`: 3; 3; 3 (2); 4; 5
- `EXACT_TEMPERATURE` default 0. Anthropic thinking: `EXACT_THINKING_BUDGET` (default `0` = off)
- Per-role models and max tokens via `EXACT_MODEL_*` / `EXACT_MAX_TOKENS_*`; empty model inherits `EXACT_MODEL`
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
- Ruff is lint + format. Match existing style: double quotes, 88 columns, isort with `exact` first-party
- Broad `except Exception` is allowed only at vendor/tool boundaries (`# noqa: BLE001`)
- Do not invent sources. Gaps go in `uncovered` / `Finding.gaps`, not in claims

## Complexity budgets

`.cursor/hooks/complexity-guard.py` owns the numbers. Do not restate them here. Tests, `alembic/`, and `scripts/dev/` are exempt. `make complexity-pre` denies a new or worse breach vs HEAD before the write lands. Ruff stays post-edit (`make lint-fix FILE=`). Commits run `make complexity-check`. The tree must have no over-budget functions. Do not park a breach.

Repair an over-budget function in this order. Stop at the first repair that works.

1. Remove a branch. A condition that cannot be false is dead weight.
2. Replace a nested conditional with an early return.
3. Move a whole responsibility to a new named unit. The caller then stops doing that work.
4. Extract a helper only when the helper has its own reason to exist.

Do not add a boolean parameter to merge two behaviours. Do not pass a bag of state to beat the parameter budget. Do not split a function into two halves that share most of their locals.

```
make complexity-check
```

## Done when

`make check` is clean (lint + format-check + complexity + imports + tests).

## MANDATORY rules

- Don't assume. Don't hide confusion. Surface tradeoffs.
- Minimum code that solves the problem. Nothing speculative.
- Touch only what you must. Clean up only your own mess.
- Define success criteria. Loop until verified.
- When writing plans or documentation use ASD-STE100 Simplified Technical English.
- When making technical decisions, do not give much weight to development cost. Instead, prefer quality, simplicity, robustness, scalability and long term maintainability.
- Review substantial changes you authored with a **fresh reviewer** (fresh context / subagent), not by re-reading in the same working context — in-context self-review under-catches wrong assumptions.
