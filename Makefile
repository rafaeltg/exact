.PHONY: help setup install-hooks \
        test test-failed \
        lint lint-fix format format-fix \
        complexity-check complexity-pre complexity-post complexity-report \
        spec-check spec-check-ready spec-check-index spec-check-all \
        plan-check plan-init imports-check \
        workflows-check pi-test \
        check clean

.SHELLFLAGS := -eu -o pipefail -c
SHELL := /bin/bash

.DEFAULT_GOAL := help

# ─── Project ───────────────────────────────────────────────────────────
PROJECT ?= exact
export PROJECT

# ─── Tunables ──────────────────────────────────────────────────────────
# TEST=<path>::<name>  → narrow to one test (or path under tests/)
# K=<keyword>          → pytest -k filter
# VERBOSE=1            → -vv -x; default is quiet (-q)
# FILE=<path>          → lint-fix / format / format-fix one .py / .pyi file
#                        complexity-report one .py / .pyi file
#                        plan-check one .md plan artifact
# TOPIC=<slug>         → plan-init one docs/specs/<slug>.md topic
TEST  ?=
K     ?=
FILE  ?=
TOPIC ?=

PYTHON_SRC = src tests .cursor/hooks

ifeq ($(VERBOSE),1)
PYTEST_ARGS = -vv -x
AT          =
else
PYTEST_ARGS = -q
AT          = @
endif

# Single quotes: K may contain spaces (`a or b`).
ifneq ($(K),)
PYTEST_ARGS += -k '$(K)'
endif

UV     = uv run
RUFF   = $(UV) ruff
PYTEST = $(UV) pytest
GUARD       = python3 .cursor/hooks/complexity-guard.py
SPEC_GUARD  = python3 .cursor/hooks/spec-guard.py
PLAN_GUARD  = python3 .cursor/hooks/plan-guard.py

define require_python_file
	@case "$(FILE)" in \
	  *.py|*.pyi) ;; \
	  *) printf 'error: FILE= only accepts .py / .pyi (got: %s)\n' "$(FILE)" >&2; exit 2 ;; \
	esac
endef

define require_md_file
	@case "$(FILE)" in \
	  *.md) ;; \
	  *) printf 'error: FILE= only accepts .md (got: %s)\n' "$(FILE)" >&2; exit 2 ;; \
	esac
endef

# ─── Self-documentation ────────────────────────────────────────────────
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} \
	     /^[a-zA-Z0-9_.-]+:.*##/ { printf "  %-22s %s\n", $$1, $$2 }' \
	     $(MAKEFILE_LIST)

# ─── Bootstrap ─────────────────────────────────────────────────────────
setup: ## Sync deps (dev extras) and install git pre-commit hook
	$(AT)printf '==> setup\n' >&2
	@command -v uv >/dev/null 2>&1 || { \
	  printf 'error: uv is required — https://docs.astral.sh/uv/\n' >&2; exit 2; }
	uv sync --extra dev
	@$(MAKE) install-hooks
	@printf '\nSetup complete. Run: make test\n' >&2

install-hooks: ## Symlink scripts/hooks/pre-commit into .git/hooks/
	$(AT)printf '==> install-hooks\n' >&2
	@HOOK_SRC="$(CURDIR)/scripts/hooks/pre-commit"; \
	HOOK_DST="$(CURDIR)/.git/hooks/pre-commit"; \
	chmod +x "$$HOOK_SRC"; \
	if [ -L "$$HOOK_DST" ] && [ "$$(readlink "$$HOOK_DST")" = "$$HOOK_SRC" ]; then \
	  printf '  pre-commit hook: already installed\n' >&2; \
	else \
	  ln -sf "$$HOOK_SRC" "$$HOOK_DST"; \
	  printf '  pre-commit hook: installed → %s\n' "$$HOOK_DST" >&2; \
	fi

# ─── Lint / format ─────────────────────────────────────────────────────
lint: ## Run ruff lint (no writes)
	$(AT)printf '==> lint\n' >&2
	$(AT)$(RUFF) check $(PYTHON_SRC)

lint-fix: ## Apply ruff format + safe lint auto-fixes. FILE=<path> for one file
	$(AT)printf '==> lint-fix%s\n' "$(if $(FILE), ($(FILE)),)" >&2
ifdef FILE
	$(call require_python_file)
	$(AT)$(RUFF) format "$(FILE)"
	$(AT)$(RUFF) check --fix "$(FILE)"
else
	$(AT)$(RUFF) format $(PYTHON_SRC)
	$(AT)$(RUFF) check --fix $(PYTHON_SRC)
endif

format: ## Check formatting (no changes). FILE=<path> for one file
	$(AT)printf '==> format%s\n' "$(if $(FILE), ($(FILE)),)" >&2
ifdef FILE
	$(call require_python_file)
	$(AT)$(RUFF) format --check "$(FILE)"
	$(AT)$(RUFF) check --select I "$(FILE)"
else
	$(AT)$(RUFF) format --check $(PYTHON_SRC)
	$(AT)$(RUFF) check --select I $(PYTHON_SRC)
endif

format-fix: ## Apply formatting. FILE=<path> for one file
	$(AT)printf '==> format-fix%s\n' "$(if $(FILE), ($(FILE)),)" >&2
ifdef FILE
	$(call require_python_file)
	$(AT)$(RUFF) format "$(FILE)"
	$(AT)$(RUFF) check --select I --fix "$(FILE)"
else
	$(AT)$(RUFF) format $(PYTHON_SRC)
	$(AT)$(RUFF) check --select I --fix $(PYTHON_SRC)
endif

# ─── Complexity ────────────────────────────────────────────────────────
complexity-check: ## Fail when any function is over budget
	$(AT)printf '==> complexity-check\n' >&2
	$(AT)$(GUARD) --check

# Cursor hooks: stdout is protocol JSON — never print banners here.
# Always `@` so VERBOSE=1 cannot echo the recipe onto stdout.
complexity-pre: ## Cursor preToolUse — deny over-budget Write/StrReplace
	@$(GUARD) --pre

complexity-post: ## Cursor postToolUse — advisory complexity context
	@$(GUARD)

# Every function's measured metrics against its budget. A plan author needs the
# headroom of the functions a task grows; without this, the only source is the
# guard's own 32 KB of code, and a restated budget drifts from it.
complexity-report: ## Print budget headroom per function. FILE=<path.py>
	$(AT)printf '==> complexity-report%s\n' "$(if $(FILE), ($(FILE)),)" >&2
	@test -n "$(FILE)" || { \
	  printf 'error: complexity-report requires FILE=<path.py>\n' >&2; exit 2; }
	$(call require_python_file)
	$(AT)$(GUARD) --report "$(FILE)"

# ─── Imports ───────────────────────────────────────────────────────────
# Package-level: at each level the contract squashes every sibling's subtree
# and forbids cycles between the siblings. Stricter than "no module cycle" —
# it also fails on package-to-package indirection. Config: pyproject.toml
# [tool.importlinter].
imports-check: ## Fail on any import cycle inside exact
	$(AT)printf '==> imports-check\n' >&2
	$(AT)$(UV) lint-imports

# ─── Specification and plan artifacts ─────────────────────────────────
# Specification checks are complete-document gates. Index mode reads staged
# specification and evidence blobs, so partial staging cannot validate the worktree.
spec-check: ## Check one specification. FILE=<spec.md>
	$(AT)printf '==> spec-check%s\n' "$(if $(FILE), ($(FILE)),)" >&2
	@test -n "$(FILE)" || { \
	  printf 'error: spec-check requires FILE=<spec.md>\n' >&2; exit 2; }
	$(call require_md_file)
	$(AT)$(SPEC_GUARD) --check "$(FILE)"

spec-check-ready: ## Check one committed ready specification. FILE=<spec.md>
	$(AT)printf '==> spec-check-ready%s\n' "$(if $(FILE), ($(FILE)),)" >&2
	@test -n "$(FILE)" || { \
	  printf 'error: spec-check-ready requires FILE=<spec.md>\n' >&2; exit 2; }
	$(call require_md_file)
	$(AT)$(SPEC_GUARD) --ready "$(FILE)"

spec-check-index: ## Check one staged specification. FILE=<spec.md>
	$(AT)printf '==> spec-check-index%s\n' "$(if $(FILE), ($(FILE)),)" >&2
	@test -n "$(FILE)" || { \
	  printf 'error: spec-check-index requires FILE=<spec.md>\n' >&2; exit 2; }
	$(call require_md_file)
	$(AT)$(SPEC_GUARD) --check-index "$(FILE)"

spec-check-all: ## Check every tracked docs/specs specification
	$(AT)printf '==> spec-check-all\n' >&2
	$(AT)$(SPEC_GUARD) --check-all

# Reference gate for a `/plan` artifact. Strict mode validates the v1 plan
# grammar, freshness, producer order, test references, and Make targets.
plan-check: ## Verify plan-artifact references. FILE=<plan.md>
	$(AT)printf '==> plan-check%s\n' "$(if $(FILE), ($(FILE)),)" >&2
	@test -n "$(FILE)" || { \
	  printf 'error: plan-check requires FILE=<plan.md>\n' >&2; exit 2; }
	$(call require_md_file)
	$(AT)$(PLAN_GUARD) --check "$(FILE)"

# Pre-flight for one `/plan` run: the topic slug, the ready specification gate,
# a clean tree, and the state of the topic directory. It writes the v1 marker
# and prints the metadata lines of the plan head.
plan-init: ## Gate the inputs of one plan and print its metadata. TOPIC=<slug>
	$(AT)printf '==> plan-init%s\n' "$(if $(TOPIC), ($(TOPIC)),)" >&2
	@test -n "$(TOPIC)" || { \
	  printf 'error: plan-init requires TOPIC=<topic-slug>\n' >&2; exit 2; }
	$(AT)$(PLAN_GUARD) --init "$(TOPIC)"

# ─── Workflow scripts ──────────────────────────────────────────────────
# `.claude/workflows/*.js` run in the agent harness, not in any interpreter this
# project ships. The check is therefore host-side and skips when node is absent.
#
# A bare `node --check <file>` is USELESS here: Node's automatic CJS/ESM detection
# sees the leading `export const meta` and exits 0 on any downstream syntax error.
# Checking the file as .mjs reports the opposite false result — these scripts use
# top-level `return` and top-level `await`, which no module goal accepts. So
# reproduce the runtime's own shape: neutralise the one `export` and wrap the body
# in an async arrow, which makes both legal, then check that.
#
# The opening wrapper deliberately ends WITHOUT a newline, so it shares line 1 with
# the script's own first line. That keeps node's reported line numbers matching the
# real file. It relies on every script's line 1 staying comment-safe (all five open
# with `// SYNC:`). A script that starts with a shebang would report a FALSE syntax
# error — restore the newline if that ever happens.
#
# Scope: this catches typos only. A live Workflow run is the only real coverage.
workflows-check: ## Syntax-check .claude/workflows/*.js (skips without node)
	$(AT)printf '==> workflows-check\n' >&2
	@if ! command -v node >/dev/null 2>&1; then \
	  printf 'WARNING: node not on PATH — skipping .claude/workflows/*.js syntax check.\n' >&2; \
	else \
	  tmp=$$(mktemp -d); \
	  for f in .claude/workflows/*.js; do \
	    { printf 'const __check = async () => {'; \
	      sed 's/^export const meta/const meta/' "$$f"; \
	      printf '\n}\n'; } > "$$tmp/chk.mjs"; \
	    node --check "$$tmp/chk.mjs" \
	      || { printf 'error: syntax error in %s\n' "$$f" >&2; rm -rf "$$tmp"; exit 1; }; \
	  done; \
	  rm -rf "$$tmp"; \
	fi

# ─── Tests ─────────────────────────────────────────────────────────────
test: ## Run pytest (TEST= path, K= keyword, VERBOSE=1)
	$(AT)printf '==> test\n' >&2
	$(AT)$(PYTEST) $(if $(TEST),$(TEST),tests) $(PYTEST_ARGS)

test-failed: ## Re-run only previously failed tests
	$(AT)printf '==> test-failed\n' >&2
	$(AT)$(PYTEST) tests --lf $(PYTEST_ARGS)

pi-test: ## Run focused Pi resource and extension tests
	$(AT)printf '==> pi-test\n' >&2
	$(AT)$(PYTEST) tests/test_pi_resources.py -k 'test_pi_github_workflow_'
	$(AT)node --experimental-strip-types --test tests/test_pi_extension.mjs

# ─── Aggregate gate (AGENTS.md "Done when") ────────────────────────────
check: ## Lint, format-check, complexity, imports, workflow scripts, tests
	$(AT)printf '==> check\n' >&2
	@$(MAKE) lint
	@$(MAKE) format
	@$(MAKE) spec-check-all
	@$(MAKE) complexity-check
	@$(MAKE) imports-check
	@$(MAKE) workflows-check
	@$(MAKE) pi-test
	@$(MAKE) test

# ─── Cleanup ───────────────────────────────────────────────────────────
clean: ## Remove caches and coverage artifacts
	$(AT)printf '==> clean\n' >&2
	@find . -type d \( -name __pycache__ -o -name .pytest_cache \
	    -o -name .mypy_cache -o -name .ruff_cache -o -name htmlcov \
	    -o -name .scannerwork -o -name .import_linter_cache \
		-o -name .test-reports -o -name exact.egg-info \) \
	    -prune -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name .coverage \
	    -o -name "coverage.xml" \) -delete
