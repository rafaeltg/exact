"""Deterministic checks for project-local Pi resources."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _frontmatter(path: Path) -> dict[str, str]:
    """Read the simple YAML frontmatter fields used by Pi templates."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    values: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator:
            values[key] = value.strip().strip('"')
    return values


def test_pi_settings_preserve_model_and_load_shared_skills() -> None:
    """Project settings keep existing model choices and load Claude skills."""
    settings = json.loads((ROOT / ".pi/settings.json").read_text(encoding="utf-8"))
    assert settings["defaultProvider"] == "openrouter"
    assert settings["defaultModel"] == "openai/gpt-5.6-luna-pro"
    assert settings["skills"] == [
        "../.claude/skills/phase-slicing",
        "../.claude/skills/task-structuring",
        "../.claude/skills/python-quality",
        "../.claude/skills/test-design",
    ]


def test_pi_prompt_templates_have_unique_names_and_arguments() -> None:
    """Both templates expose the documented positional argument contract."""
    prompts = sorted((ROOT / ".pi/prompts").glob("*.md"))
    metadata = [_frontmatter(path) for path in prompts]
    assert [path.stem for path in prompts] == ["commit", "create-pr", "plan", "spec"]
    assert len({item["description"] for item in metadata}) == 4
    assert "$1" in (ROOT / ".pi/prompts/spec.md").read_text(encoding="utf-8")
    assert "${@:2}" in (ROOT / ".pi/prompts/spec.md").read_text(encoding="utf-8")
    assert "$1" in (ROOT / ".pi/prompts/plan.md").read_text(encoding="utf-8")


def test_pi_github_workflow_prompts_are_discoverable() -> None:
    """Both GitHub workflows are project-local prompt resources."""
    prompts = sorted((ROOT / ".pi/prompts").glob("*.md"))
    assert {path.stem for path in prompts} >= {"commit", "create-pr"}


def test_pi_github_workflow_prompt_metadata_preserves_source_contract() -> None:
    """Workflow descriptions and no-argument contracts match the source commands."""
    commit = _frontmatter(ROOT / ".pi/prompts/commit.md")
    create_pr = _frontmatter(ROOT / ".pi/prompts/create-pr.md")

    assert (
        commit["description"]
        == "Create atomic git commits for all working-tree changes with clear messages, "
        "following CONTRIBUTING.md conventions"
    )
    assert "argument-hint" not in commit
    assert (
        create_pr["description"]
        == "Create a GitHub PR for the current branch with a generated title and description"
    )
    assert create_pr["argument-hint"] == "(no args; uses the current branch)"
    for metadata in (commit, create_pr):
        assert "allowed-tools" not in metadata
        assert "disable-model-invocation" not in metadata


def test_pi_github_workflow_prompts_cover_source_stages() -> None:
    """Workflow prompts retain each source workflow's observable stages."""
    commit = (ROOT / ".pi/prompts/commit.md").read_text(encoding="utf-8")
    create_pr = (ROOT / ".pi/prompts/create-pr.md").read_text(encoding="utf-8")

    for marker in (
        "EXACT_GITHUB_USER",
        "git status",
        "git reset HEAD",
        "git diff",
        "git add",
        "git commit",
        "gh auth switch",
        "ORIGINAL_GH_USER",
        "final status",
    ):
        assert marker in commit
    for marker in (
        "EXACT_GITHUB_USER",
        "default branch",
        "git branch --show-current",
        "git status --short",
        "git push",
        "gh pr create",
        "ORIGINAL_GH_USER",
        "PR URL",
    ):
        assert marker in create_pr


def test_pi_github_workflow_extension_requires_explicit_invocation() -> None:
    """The extension activates only exact workflow commands and clears settled state."""
    extension = (ROOT / ".pi/extensions/github-workflows.ts").read_text(
        encoding="utf-8"
    )

    assert 'text === "/commit"' in extension
    assert 'text === "/create-pr"' in extension
    assert 'text: "/commit"' not in extension
    assert 'text: "/create-pr"' not in extension
    assert 'pi.on("input"' in extension
    assert 'pi.on("agent_settled"' in extension
    assert 'action: "handled"' in extension


def test_pi_github_workflow_extension_blocks_unauthorized_commands() -> None:
    """The extension enforces Bash-only calls through the workflow allowlist."""
    extension = (ROOT / ".pi/extensions/github-workflows.ts").read_text(
        encoding="utf-8"
    )

    assert 'pi.on("tool_call"' in extension
    assert "isAllowedWorkflowCommand" in extension
    assert 'event.toolName !== "bash"' in extension
    assert "block: true" in extension
    assert "SHELL_OPERATORS" in extension


def test_pi_shared_skills_have_valid_frontmatter() -> None:
    """The shared skills remain discoverable through Pi's settings path."""
    for name in ("phase-slicing", "task-structuring"):
        path = ROOT / ".claude/skills" / name / "SKILL.md"
        metadata = _frontmatter(path)
        assert metadata["name"] == name
        assert metadata["description"]
