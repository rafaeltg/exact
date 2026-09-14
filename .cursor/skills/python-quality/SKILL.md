---
name: python-quality
description: |
  TRIGGER: writing, refactoring, or reviewing Python — implement a module/node/tool, "review this diff", PR audit, bug-hunt, "what's wrong with this code".
  EXCLUDE: test-only work owned by test-design (still load test-design whenever tests are written or reviewed); non-Python surfaces.
  SIGNAL: Python authoring or a quality question on existing Python.
---

# Python Quality

These rules are authoritative. `AGENTS.md`, `pyproject.toml`, and this skill are the contract. When existing code contradicts them, new and changed code follows these rules — do not copy the surrounding violation.

Two modes. **Implement** when writing or refactoring. **Review** when evaluating existing code. Run both when you implement then verify your own diff. Load `test-design` whenever tests are in scope — it is authoritative for tests.

## Mode selection

| Intent | Mode |
|--------|------|
| Write, refactor, fix, implement | Implement |
| Review, audit, PR feedback, what's wrong | Review |
| Implement then verify | Implement, then Review on the diff |

---

# Implement mode

## Gate 0 — required before writing

Do not write until you have read:

1. `AGENTS.md` (structure, invariants, bounds)
2. `pyproject.toml` (ruff, pytest — the configured tool rules)
3. Two or three neighboring files for import shape and naming already compliant with this skill

If a neighbor violates this skill, do not propagate the violation.

## Definition of Done — mandatory gates

Work is not done until every gate passes. Run the commands. Do not eyeball.

```bash
uv run ruff check
uv run ruff format --check
python3 .cursor/hooks/complexity-guard.py --check
uv run pytest -q
```

Required:

- Ruff lint and format clean
- Complexity guard clean — no new or worse breach; do not park a breach
- New behavior covered by a test that fails without the change; tests obey `test-design`
- Pytest green for the touched area — no silent `xfail` / skip used to hide failure
- No live network in pytest — fakes and injected seams only (`tests/fakes.py`)
- Diff contains none of the [Forbidden](#forbidden--landmines) items
- Every module starts with `from __future__ import annotations`
- Public signatures typed; all imports at module top
- Dependencies injected via `Runtime` or constructors — module-level client singletons that block fakes are forbidden

Do not invent mypy/`type: ignore` policy the repo never configured. Do not leave public signatures untyped.

## Language

- Obey `requires-python` in `pyproject.toml` (this repo: 3.11+)
- Use `X | None`, not `Optional[X]`; use `list[str]`, not `List[str]`
- Use `@override` on every method that implements a Protocol or overrides a base — omitting it is forbidden

## Naming — required

- Modules: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE`
- Private: single leading `_` only — `__` name-mangling is forbidden
- Booleans: predicate names only (`is_active`, `has_items`, `can_retry`) — noun booleans are forbidden
- Abbreviations: only `id`, `url`, `http`, `llm`, and equally universal terms

## Type hints — required

- Return concrete types
- Use `Protocol` for injectable seams; every Protocol must have at least one concrete implementation — Protocols without impls are forbidden
- `Any` must not leak across a public boundary; if unavoidable, wrap and confine with `# type: ignore[code]  # reason` — bare `# type: ignore` is forbidden
- Match existing compliant parameter style in the module (`Mapping` vs `dict`); do not introduce a second style in the same module

## Docstrings and comments — required / forbidden

- Google-style docstrings only where the signature does not already state the contract; write why and non-obvious contracts, never restate types
- Forbidden in source: plan/spec anchors (`Decision 4`, `spec line 31`, `see plan.md`) — paraphrase the why
- Forbidden: numbered step narration on self-documenting calls (`# 1. Existence check`)
- Forbidden: comments that justify a claim you have not verified against the referenced code — verify first or delete the comment

## Dependency injection — required

- Inject collaborators through `Runtime` or constructors
- `unittest.mock.patch` on module internals is forbidden — see `test-design`
- Speculative Protocols (no concrete class) are forbidden

## Error handling — required

- Business logic raises domain errors, not bare `ValueError` / `RuntimeError` sprayed from core paths
- Catch specific exceptions; chain with `raise ... from original`
- `except Exception` only at vendor/tool boundaries, and only with `# noqa: BLE001`
- Bare `except:` is forbidden
- An exception raised inside an `except` block must not rely on a sibling `except` on the same `try` — nest or extract a helper

## Pydantic — required at boundaries

- External data (settings, tool payloads, structured LLM outputs) goes through Pydantic (or an equally validating boundary)
- Secrets: `Field(repr=False)`
- Immutable value objects: `frozen=True` unless mutation is required

## Imports — required

- All imports at module top — local imports are forbidden
- Circular-import pressure is fixed by redesigning boundaries, not by hiding imports

## Forbidden — landmines

Shipping any of these is a DoD failure:

- Mutable default arguments
- Bare `except:` or catch-and-ignore without logging/re-raise policy
- String concatenation in a loop — use `"".join` or equivalent
- Nesting depth 3+ when an early return removes a level
- Magic numbers/strings that need decoding — name them
- Local imports
- Single-use local aliases (`x = self._x` then one read) — inline
- The same small derivation computed in two layers for one request — one layer only
- N helpers that each re-parse the same input — share a base or hoist once
- Plan/spec anchors in comments
- Invented sources or unsourced claims — gaps go in `uncovered` / `Finding.gaps`, never in claims

## Over-budget functions — mandatory repair order

`.cursor/hooks/complexity-guard.py` owns the budgets — do not restate the numbers. Stop at the first repair that works:

1. Remove a dead branch
2. Replace nesting with an early return
3. Move a whole responsibility to a new named unit
4. Extract a helper only when the helper has its own reason to exist (state that reason in one sentence that does not name the caller)

Forbidden repairs:

- Boolean parameter to merge two behaviours
- State bag / dict to fake a lower parameter count
- Split into two halves that share most of the caller's locals

---

# Review mode

These review rules are authoritative. A review that skips them is invalid.

## Before review — mandatory

Do not start Pass 1 until you have:

1. Stated purpose (PR / ticket / spec / user ask)
2. Read `AGENTS.md` and `pyproject.toml`
3. Classified scope: bugfix | feature | refactor
4. Noted test seams (`tests/fakes.py`, DI / `Runtime`)

Scope order is mandatory:

- **Bug fix:** verify fix and root cause, then regressions, then the rest
- **Feature:** architecture, contracts, tests for important behaviors
- **Refactor:** behavior preserved; flag any new behavior that crept in

## Passes — mandatory order

Run all five. Do not skip ahead to polish.

### Pass 1 — Architecture

Flag: wrong abstractions; dependencies not flowing inward; files outside `src/exact/...` placement; singletons that block injection; circular deps; layer leaks.

### Pass 2 — Contracts

Flag: unclear public signatures; Protocols without concrete impls; unvalidated external input; generic errors where domain errors belong; APIs that cannot evolve without breaking callers.

### Pass 3 — Correctness

Flag: main path ≠ stated intent; missing edge cases; illegal `except Exception`; mutable defaults; `is` vs `==` abuse; naive/aware datetime mix; generator reuse; exact invariant breaks (scout-before-clarify, source id shape, invented sources, citation audit must remain code).

### Pass 4 — Testing

Flag every `test-design` violation: private access, implementation assertions, mocks not at DI seams, live network, missing error/edge coverage, non-scenario names.

### Pass 5 — Polish

Flag: naming violations; comment/docstring hygiene breaks; any [Forbidden](#forbidden--landmines) item; untyped public signatures; complexity-guard breaches or forbidden repairs.

## Severity — mandatory classification

Every finding gets exactly one:

| Level | Use when |
|-------|----------|
| **Critical** | Bug, data loss, security hole, production incident if merged |
| **Major** | Serious correctness / maintainability / perf — must fix before merge |
| **Minor** | Contract/quality violation without immediate functional break |
| **Suggestion** | Optional improvement only — never use for a rule violation |

Inflating Critical or burying Critical under Suggestions is forbidden. Rule violations are never Suggestions.

## Definition of Done — review

Review is not complete until:

- Intent was read before code
- All five passes ran
- Forbidden list was checked against the diff
- Every finding has `file:line`, WHY (consequence), and a concrete fix
- Findings ordered critical → major → minor; minors grouped
- Output matches the format below

## Output format — mandatory

### Summary

2–3 sentences: merge-ready or not; highest-severity blocker.

### Findings

```markdown
### [Severity] Brief title

**File:** `path/to/file.py:line`

**Issue:** What is wrong and WHY it matters.

**Suggestion:** Concrete fix.
```

When proposing a fix, use [references/refactoring-patterns.md](references/refactoring-patterns.md) where a pattern applies — vague advice ("clean this up") is forbidden.

### Positive callouts

Name 2–3 specific strengths. Required when the change has any.

## Reviewer discipline — required

- Do not invent findings to fill space
- Critique the code, not the author
- Uncertainty must be labeled uncertainty — guessing a finding is forbidden; ask instead
- Do not demand rewrites of working, tested, rule-compliant code for taste
- Diffs >500 lines: Passes 1–3 before Pass 5
- Substantial self-authored changes: review in a fresh context / subagent (`AGENTS.md`) — in-context self-review does not satisfy this rule

## References — load when needed

- [references/review-checklist.md](references/review-checklist.md) — mandatory item list for thorough / large / unfamiliar reviews
- [references/refactoring-patterns.md](references/refactoring-patterns.md) — required catalog for concrete Suggestions
- [references/style-standards.md](references/style-standards.md) — exact tool and naming ground truth
