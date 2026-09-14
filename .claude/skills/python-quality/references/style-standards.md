# Style Standards — exact

Authoritative. Ground truth is `pyproject.toml` and `AGENTS.md`. New and changed code must match. Do not propose style that fights configured tooling.

## Ruff — required

```toml
[tool.ruff]
target-version = "py311"
line-length = 88

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "UP", "B", "BLE", "SIM", "RUF"]
ignore = ["SIM108"]

[tool.ruff.lint.isort]
known-first-party = ["exact"]
```

- Format: double quotes, 88 columns — mandatory
- `except Exception` without `# noqa: BLE001` outside vendor/tool boundaries is a finding
- Do not flag or "fix" ignored rules in the configured ignore list

## Commands — DoD

```bash
uv run ruff check
uv run ruff format --check
python3 .cursor/hooks/complexity-guard.py --check
uv run pytest -q
```

Use `uv run` for ruff/pytest. Host bare invocations that diverge from project habit are not the review standard.

## `from __future__ import annotations`

Required as the first import in every module. Omission in a new or touched file is a finding.

## Naming — required

| Construct | Convention |
|-----------|------------|
| Functions / vars | `snake_case` |
| Classes / exceptions | `PascalCase` (`Error` suffix for exceptions) |
| Constants | `UPPER_SNAKE` |
| Private | `_single_leading_underscore` |
| Protocols | `PascalCase`, no `I` prefix |
| Modules | `snake_case` |
| Booleans | `is_` / `has_` / `can_` predicates |

`__` name-mangling is forbidden in new/changed code.

## Import ordering — required

Ruff `I` groups, blank line between:

1. `from __future__ import annotations`
2. stdlib
3. third-party
4. first-party `exact`

Local imports are forbidden.

## Docstrings — required when applicable

Google-style for non-obvious public APIs. Skip when the signature is sufficient. First line: imperative mood. `Raises:` lists only exceptions callers must handle. Docstrings that restate types are forbidden.

## Pytest — required

- Layout: `tests/`, `pythonpath` includes `src`
- No live network
- Inject via `Runtime` / constructors; fakes in `tests/fakes.py`
- Obey `test-design` for behavior, mocking, and naming
- `tests/` is complexity-exempt — that exemption does not authorize god helpers in `src/`

## Complexity guard — required

`.cursor/hooks/complexity-guard.py` owns enforcement. Budgets and known breach
shapes live in the main skill (Gate 0). Inventing alternate budgets in a
review is forbidden.

| Hook | When | Effect |
|------|------|--------|
| `preToolUse --pre` | Before `Write` / `StrReplace` | Deny over-budget prospective content; nothing hits disk |
| `afterFileEdit` | After an allowed write | Ruff lint-fix + format only |
| `postToolUse` | `TabWrite` | Advisory complexity context |
| `--check` | Pre-commit / DoD | Fail if any tracked function is over budget |

Gotcha: a post-edit soft signal is not permission to park debt. `--pre` and
`--check` are the hard gates. Shell/paste bypasses `--pre`; `--check` still
applies.
