# Contributing to exact

Thanks for contributing. This document covers local setup, tests, the
pre-commit hook, the complexity gate, and the conventions that keep the
graph contract stable. Contract: [docs/spec.md](docs/spec.md). Architecture:
[docs/architecture.md](docs/architecture.md). Agent rules:
[AGENTS.md](AGENTS.md).

## 1. Local setup

Prerequisites:

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

```bash
# 1. Clone
git clone <repo-url> exact && cd exact

# 2. Sync deps + install pre-commit hooks (ruff + complexity gate)
make setup

# 3. Env file (live CLI only; pytest must not hit the network)
cp .env.example .env
# set EXA_API_KEY and ANTHROPIC_API_KEY (or OPENAI_API_KEY)
# optional: ELICIT_API_KEY for academic paper search
# set EXACT_GITHUB_USER for /commit and /create-pr (gh auth switch)

# 4. Run the gate (lint + format-check + complexity + tests)
make check
```

Raw equivalents: `uv sync --extra dev`, `uv run pytest -q`. See `make help`.

Editor: install the Ruff extension. `.vscode/settings.json` turns on format
and lint-fix on save. Agent `Write`/`StrReplace` hit `make complexity-pre`
before disk; after an allowed write, `afterFileEdit` runs
`scripts/hooks/post-edit.sh` → `make lint-fix FILE=…`.

## 2. Tests

One suite. All tests are offline. Use the fakes in `tests/fakes.py`. Do not
call Exa, Elicit, or any LLM provider from pytest.

| Command            | Requires                         | Time    |
|--------------------|----------------------------------|---------|
| `make test`        | `make setup`                     | seconds |
| `uv run pytest -q` | `uv sync --extra dev`            | seconds |

### Writing a new test

- Exercise public behaviour. Do not assert on private helpers or call order.
- Mock only at injection seams (`Runtime`, settings, client extras). Prefer
  hand-rolled fakes in `tests/fakes.py` over `unittest.mock.patch` on module
  internals.
- Name tests from spec scenarios when the behaviour is in `docs/spec.md`.
- For every numeric bound in the spec, cover the boundary, one below, and
  one above.
- Keep tests deterministic: no wall clock, no real network, no unseeded
  randomness.

Authoritative test rules live in the test-design skill under
`.cursor/skills/test-design/` (and the Claude mirror).

## 3. Pre-commit hook

`make install-hooks` (also part of `make setup`) symlinks
`scripts/hooks/pre-commit` into `.git/hooks/pre-commit`. Every commit runs:

1. **`make lint-fix`** — ruff format + safe lint fixes, then re-stage
   cleanly-staged files that the fixers changed (partial staging is left
   alone and warned).
2. **`make complexity-check`** — fail if any tracked function is over budget.

Do not skip hooks. `git commit --no-verify` is for emergencies only.

## 4. Complexity gate

`.cursor/hooks/complexity-guard.py` owns the budgets. Do not restate the
numbers here. Tests, `alembic/`, and `scripts/dev/` are exempt.

- Edit-time `make complexity-pre`: denies a **new or worse** breach vs HEAD
  before the write. Ruff lint/format remain post-edit via
  `make lint-fix FILE=…`.
- Commit / merge gate: `make complexity-check` fails if any tracked function
  is over budget. The tree must have no over-budget functions. Do not park
  a breach.

Repair order (stop at the first repair that works):

1. Remove a branch. A condition that cannot be false is dead weight.
2. Replace a nested conditional with an early return.
3. Move a whole responsibility to a new named unit.
4. Extract a helper only when the helper has its own reason to exist.

Do not add a boolean parameter to merge two behaviours. Do not pass a bag
of state to beat the parameter budget. Do not split a function into two
halves that share most of their locals.

```bash
make complexity-check
```

## 5. CI pipeline (not defined yet)

There is no `.github/workflows/` pipeline yet. When one lands, document the
jobs here. Until then, a change is ready when the local gates in §7 are
clean.

## 6. Conventions

- **Python:** 3.12+, `src/exact` layout, `from __future__ import annotations`
  in every module.
- **Formatting / lint:** Ruff (`ruff format`, `ruff check`). Double quotes,
  88 columns, isort with `exact` as first-party. Config is in
  `pyproject.toml`.
- **DI:** inject `Runtime` (settings + llm + `extras` for clients). Tests
  use fakes — no live network in pytest.
- **Exceptions:** broad `except Exception` only at vendor/tool boundaries
  (`# noqa: BLE001`).
- **Sources:** do not invent sources. Gaps go in `uncovered` /
  `Finding.gaps`, not in claims. Writer citations must resolve;
  `audit_citations` is code, not an LLM.
- **Bounds (do not loosen):** clarify turns ≤ 3; research waves ≤ 3;
  topics/wave ≤ 3; tool rounds/worker ≤ 4; hits/call ≤ 5.
- **Scope:** CLI + SQLite checkpointer only. No HTTP API, web UI, or extra
  retrieval vendors. Out of scope: Firecrawl, MCP product, Elicit Reports,
  `create_supervisor`, parallel writers, PDF/paywall full text.
- **Docs:** if you change topology, bounds, tools, or citation rules,
  update `docs/spec.md` and `docs/architecture.md` in the same change.
  Plans and documentation use ASD-STE100 Simplified Technical English.
- **Commits / PRs:** imperative subject, ≤ 72 chars, body wrapped at 72.
  One concern per PR. If a PR does two things, split it. No emoji. No
  `Co-Authored-by:` trailer and no "Generated with …" byline on commits or
  PR bodies — nothing rejects one mechanically, and a squash merge can make
  a trailer permanent on `main`.

- **Imports:** standard library, then third-party, then local. No wildcard
  imports.

Graph invariants (see also `AGENTS.md`):

- Scout before clarify. Questions must cite scout titles unless scout is
  empty.
- Isolated `research_agent` workers via `Send`. Parent never sees raw tool
  I/O. Prune to `Finding` before returning.
- Source ids: `src_{topic}_{i}`.
- Retrieval failure: append `errors` and `gaps=["retrieval failed"]`. The
  graph still finishes.
- `messages` is the clarify thread only.

## 7. Definition of done

A change is done when all of these are clean:

```bash
make check
```

## 8. Releasing (out of scope for this pass)

No release process is defined yet. When one is, link it from here.
