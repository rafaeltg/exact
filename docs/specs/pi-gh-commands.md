# GitHub workflow commands for Pi

Topic: pi-gh-commands
Revision: 4
Status: Ready
Superseded by: None

## Goal

Port the repository's `/commit` and `/create-pr` GitHub workflow commands to Pi as project-local prompt templates. Preserve their observable repository and GitHub workflow while using Pi's prompt-template resource model and the repository's existing checks.

## Requirements

### R1 — Expose the GitHub workflow commands
- **Status:** active
- **Behavior:** The project exposes `/commit` and `/create-pr` from Pi project resources. Each one keeps its user-facing description and the source argument contract. The project-local extension is loaded as the enforcement boundary.

### R2 — Port and restrict the commit workflow
- **Status:** active
- **Behavior:** An explicit `/commit` covers the source workflow. That workflow is working-tree inspection, logical commit grouping, hook-preserving commit execution, and final status reporting. It runs Git only. The Pi extension blocks each tool call outside the source command's allowed Git patterns.

### R3 — Port and restrict the pull-request workflow
- **Status:** active
- **Behavior:** An explicit `/create-pr` covers the source workflow. That workflow is branch pre-flight, dirty-tree confirmation, branch publication, generated PR content, PR creation, and URL reporting. Each GitHub CLI call runs through `scripts/gh-exact`. The Pi extension blocks each tool call outside the source command's allowed Git and `scripts/gh-exact` patterns.

### R4 — Keep the Pi resources verifiable
- **Status:** active
- **Behavior:** The port follows Pi's project resource conventions and has deterministic repository tests for resource discovery, metadata, argument handling, explicit invocation, and extension enforcement.

## Out of scope

- Changing the source Claude command files as part of the port. D2 follows a change to the source commands.
- Changing commit, pull-request, or GitHub account policy in `CONTRIBUTING.md`.
- Adding a general GitHub integration, web UI, or HTTP API.
- Starting `/plan` as part of this work.

## Decisions

### D1 — Enforce command restrictions with a Pi extension
- **Status:** active
- **Question:** What should enforce the Claude command restrictions in Pi?
- **Answer:** Add a project-local Pi extension that mechanically enforces the source commands' tool and invocation restrictions.
- **Impact:** The extension is the enforcement boundary for `/commit` and `/create-pr`. The Pi resources do not rely on prompt text alone to restrict Git and GitHub CLI operations.
- **Evidence:** E1

### D2 — Act as the project account without a global switch
- **Status:** active
- **Question:** How does a workflow run GitHub CLI calls as `EXACT_GITHUB_USER`?
- **Answer:** Each call runs through `scripts/gh-exact`. The wrapper sets `GH_TOKEN` to the token of `EXACT_GITHUB_USER` for that one process.
- **Impact:** The global `gh` account does not change, so no workflow has an account restore step. `/commit` runs Git only, so it has no GitHub CLI call. The extension blocks `gh auth switch` and bare `gh` calls.
- **Evidence:** E6

## Repository evidence

- E1: repo:.claude/commands/commit.md#L3
- E2: repo:.claude/commands/commit.md#L16
- E3: repo:.claude/commands/commit.md#L30
- E4: repo:.claude/commands/create-pr.md#L71
- E5: repo:.claude/commands/create-pr.md#L4
- E6: repo:.claude/commands/create-pr.md#L19
- E7: repo:.claude/commands/create-pr.md#L29
- E8: repo:.claude/commands/create-pr.md#L43
- E9: repo:.claude/commands/create-pr.md#L47
- E10: repo:.claude/commands/create-pr.md#L55
- E11: repo:.claude/commands/create-pr.md#L83
- E12: repo:.pi/prompts/plan.md#L1
- E13: repo:.pi/settings.json#L4
- E14: repo:tests/test_pi_resources.py#L32
- E15: repo:Makefile#L264
- E16: repo:CONTRIBUTING.md#L27
- E17: repo:.pi/extensions/rtk.ts#L1
- E18: repo:.pi/prompts/spec.md#L1

## Acceptance criteria

- **R1:** Pi discovers `/commit` and `/create-pr` from the project resources, and each command exposes the source description and argument contract.
- **R2:** An explicit `/commit` observes each source workflow stage. It runs no GitHub CLI call. Unauthorized Git and GitHub CLI tool calls are blocked.
- **R3:** An explicit `/create-pr` observes the source branch checks, dirty-tree confirmation, push, PR creation through `scripts/gh-exact`, and URL report. It does not switch the global `gh` account. It does not bypass a stop condition of the source command. Unauthorized Git and GitHub CLI tool calls are blocked, including bare `gh` calls.
- **R4:** The focused Pi resource and extension tests pass and `make spec-check FILE=docs/specs/pi-gh-commands.md` passes.

## Open questions

None.
