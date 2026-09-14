.PHONY: help setup install-hooks \
        test test-failed \
        lint lint-fix format format-fix \
        complexity-check complexity-pre complexity-post \
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
TEST ?=
K    ?=
FILE ?=

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
GUARD  = python3 .cursor/hooks/complexity-guard.py

define require_python_file
	@case "$(FILE)" in \
	  *.py|*.pyi) ;; \
	  *) printf 'error: FILE= only accepts .py / .pyi (got: %s)\n' "$(FILE)" >&2; exit 2 ;; \
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

# ─── Tests ─────────────────────────────────────────────────────────────
test: ## Run pytest (TEST= path, K= keyword, VERBOSE=1)
	$(AT)printf '==> test\n' >&2
	$(AT)$(PYTEST) $(if $(TEST),$(TEST),tests) $(PYTEST_ARGS)

test-failed: ## Re-run only previously failed tests
	$(AT)printf '==> test-failed\n' >&2
	$(AT)$(PYTEST) tests --lf $(PYTEST_ARGS)

# ─── Aggregate gate (AGENTS.md "Done when") ────────────────────────────
check: ## Lint, format-check, complexity, tests
	$(AT)printf '==> check\n' >&2
	@$(MAKE) lint
	@$(MAKE) format
	@$(MAKE) complexity-check
	@$(MAKE) test

# ─── Cleanup ───────────────────────────────────────────────────────────
clean: ## Remove caches and coverage artifacts
	$(AT)printf '==> clean\n' >&2
	@find . -type d \( -name __pycache__ -o -name .pytest_cache \
	    -o -name .mypy_cache -o -name .ruff_cache -o -name htmlcov \
	    -o -name .scannerwork \) \
	    -prune -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" -o -name .coverage \
	    -o -name "coverage.xml" \) -delete
