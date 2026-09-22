# GitHub workflow commands for Pi

Topic: pi-gh-commands
Revision: 3
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
- **Behavior:** An explicit `/commit` covers the source workflow. That workflow is GitHub account pre-flight, working-tree inspection, logical commit grouping, hook-preserving commit execution, account restoration, and final status reporting. The Pi extension blocks each tool call outside the source command's allowed Git and GitHub CLI patterns.

### R3 — Port and restrict the pull-request workflow
- **Status:** active
- **Behavior:** An explicit `/create-pr` covers the source workflow. That workflow is GitHub account and branch pre-flight, dirty-tree confirmation, branch publication, generated PR content, PR creation, account restoration, and URL reporting. The Pi extension blocks each tool call outside the source command's allowed Git and GitHub CLI patterns.

### R4 — Keep the Pi resources verifiable
- **Status:** active
- **Behavior:** The port follows Pi's project resource conventions and has deterministic repository tests for resource discovery, metadata, argument handling, explicit invocation, and extension enforcement.

## Out of scope

- Changing the source Claude command files.
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

## Repository evidence

- E1: repo:.claude/commands/commit.md#L3
- E2: repo:.claude/commands/commit.md#L18
- E3: repo:.claude/commands/commit.md#L37
- E4: repo:.claude/commands/commit.md#L60
- E5: repo:.claude/commands/create-pr.md#L4
- E6: repo:.claude/commands/create-pr.md#L19
- E7: repo:.claude/commands/create-pr.md#L22
- E8: repo:.claude/commands/create-pr.md#L39
- E9: repo:.claude/commands/create-pr.md#L59
- E10: repo:.claude/commands/create-pr.md#L67
- E11: repo:.claude/commands/create-pr.md#L95
- E12: repo:.pi/prompts/plan.md#L1
- E13: repo:.pi/settings.json#L4
- E14: repo:tests/test_pi_resources.py#L32
- E15: repo:Makefile#L155
- E16: repo:CONTRIBUTING.md#L27
- E17: repo:.pi/extensions/rtk.ts#L1
- E18: repo:.pi/prompts/spec.md#L1

## Acceptance criteria

- **R1:** Pi discovers `/commit` and `/create-pr` from the project resources, and each command exposes the source description and argument contract.
- **R2:** An explicit `/commit` observes each source workflow stage. It restores the original GitHub account after a post-switch failure. Unauthorized Git and GitHub CLI tool calls are blocked.
- **R3:** An explicit `/create-pr` observes the source branch checks, dirty-tree confirmation, push, PR creation, account restoration, and URL report. It does not bypass a stop condition of the source command. Unauthorized Git and GitHub CLI tool calls are blocked.
- **R4:** The focused Pi resource and extension tests pass and `make spec-check FILE=docs/specs/pi-gh-commands.md` passes.

## Open questions

None.
