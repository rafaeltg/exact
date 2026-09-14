# exact

CLI Open Deep Research agent on LangGraph. Tools are **Exa** and **Elicit** only. Clarification is grounded in an Exa (optional Elicit) scout. Contract: [docs/spec.md](docs/spec.md) v1.2. Architecture: [docs/architecture.md](docs/architecture.md).

## Commands

```
uv sync --extra dev
uv run pytest -q
uv run ruff check --fix
uv run ruff format
python3 .cursor/hooks/complexity-guard.py --check
uv run pre-commit install
```

Install hooks once after clone. Commits then run Ruff lint (with fixes), format, and the complexity gate. Do not skip hooks.

Editor: Python format + lint-fix on save via the Ruff extension (`.vscode/settings.json`). Agent `Write`/`StrReplace` run `.cursor/hooks/complexity-guard.py --pre` first (deny before disk). After an allowed write, `afterFileEdit` runs `.cursor/hooks/ruff-after-edit.py` (lint-fix + format). `TabWrite` still gets a post-edit complexity advisory via `postToolUse`.

## Bounds (do not loosen)

- Clarify turns ≤ 3; research waves ≤ 3; topics/wave ≤ 3; tool rounds/worker ≤ 4; hits/call ≤ 5
- `EXACT_TEMPERATURE` default 0. GPT-5/6: `EXACT_REASONING_EFFORT` (default `none`). Anthropic thinking: `EXACT_THINKING_BUDGET` (default `0` = off)
- Per-role models and max tokens via `EXACT_MODEL_*` / `EXACT_MAX_TOKENS_*`; empty model inherits `EXACT_MODEL`
- CLI + SQLite checkpointer. No HTTP API, web UI, or extra retrieval vendors
- Out of scope: Firecrawl, MCP product, Elicit Reports, `create_supervisor`, parallel writers, PDF/paywall full text

If you change topology, bounds, tools, or citation rules, update `docs/spec.md` and `docs/architecture.md` in the same change.

## Graph invariants

- Scout before clarify. Questions must cite scout titles unless scout is empty.
- Isolated `research_agent` workers via `Send`. Parent never sees raw tool I/O. Prune to `Finding` before returning.
- Source ids: `src_{topic}_{i}`. Writer citations must resolve; `audit_citations` is code, not an LLM.
- Retrieval failure: append `errors` and `gaps=["retrieval failed"]`. The graph still finishes.
- `messages` is the clarify thread only.

## Code

- Python 3.11+, `src/exact` layout, `from __future__ import annotations`
- Inject `Runtime` (settings + llm + `extras` for clients). Tests use `tests/fakes.py` — no live network in pytest
- Ruff is lint + format. Match existing style: double quotes, 88 columns, isort with `exact` first-party
- Broad `except Exception` is allowed only at vendor/tool boundaries (`# noqa: BLE001`)
- Do not invent sources. Gaps go in `uncovered` / `Finding.gaps`, not in claims

## Complexity budgets

`.cursor/hooks/complexity-guard.py` owns the numbers. Do not restate them here. Tests, `alembic/`, and `scripts/dev/` are exempt. `preToolUse --pre` denies a new or worse breach vs HEAD before the write lands. Ruff stays post-edit. Commits run `--check`. The tree must have no over-budget functions. Do not park a breach.

Repair an over-budget function in this order. Stop at the first repair that works.

1. Remove a branch. A condition that cannot be false is dead weight.
2. Replace a nested conditional with an early return.
3. Move a whole responsibility to a new named unit. The caller then stops doing that work.
4. Extract a helper only when the helper has its own reason to exist.

Do not add a boolean parameter to merge two behaviours. Do not pass a bag of state to beat the parameter budget. Do not split a function into two halves that share most of their locals.

```
python3 .cursor/hooks/complexity-guard.py --check
```

## Done when

`uv run ruff check`, `uv run ruff format --check`, `python3 .cursor/hooks/complexity-guard.py --check`, and `uv run pytest -q` are clean.

## MANDATORY rules

- Don't assume. Don't hide confusion. Surface tradeoffs.
- Minimum code that solves the problem. Nothing speculative.
- Touch only what you must. Clean up only your own mess.
- Define success criteria. Loop until verified.
- When writing plans or documentation use ASD-STE100 Simplified Technical English.
- When making technical decisions, do not give much weight to development cost. Instead, prefer quality, simplicity, robustness, scalability and long term maintainability.
- Review substantial changes you authored with a **fresh reviewer** (fresh context / subagent), not by re-reading in the same working context — in-context self-review under-catches wrong assumptions.
