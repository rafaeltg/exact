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
    assert [path.stem for path in prompts] == ["plan", "spec"]
    assert len({item["description"] for item in metadata}) == 2
    assert "$1" in (ROOT / ".pi/prompts/spec.md").read_text(encoding="utf-8")
    assert "${@:2}" in (ROOT / ".pi/prompts/spec.md").read_text(encoding="utf-8")
    assert "$1" in (ROOT / ".pi/prompts/plan.md").read_text(encoding="utf-8")


def test_pi_shared_skills_have_valid_frontmatter() -> None:
    """The shared skills remain discoverable through Pi's settings path."""
    for name in ("phase-slicing", "task-structuring"):
        path = ROOT / ".claude/skills" / name / "SKILL.md"
        metadata = _frontmatter(path)
        assert metadata["name"] == name
        assert metadata["description"]
