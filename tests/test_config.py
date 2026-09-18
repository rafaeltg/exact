from __future__ import annotations

import pytest
from pydantic import ValidationError

from exact.config import (
    ROLES,
    Runtime,
    Settings,
    chat_kwargs,
    effort_snapshot,
    role_max_tokens,
    role_model_id,
)
from tests.fakes import FakeLLM

_KNOB_ENV_NAMES = (
    "EXACT_EFFORT",
    "MAX_ITERATIONS",
    "MAX_CLARIFY_TURNS",
    "MAX_TOOL_ROUNDS",
    "MAX_HITS",
)


@pytest.fixture(autouse=True)
def _no_inherited_knobs(monkeypatch):
    """A shell export of any knob must not steer an assertion in this file."""
    for name in _KNOB_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _knobs(settings: Settings) -> tuple[int, ...]:
    return (
        settings.max_iterations,
        settings.max_clarify_turns,
        settings.max_tool_rounds,
        settings.max_hits,
        settings.max_topics_first_wave,
        settings.max_topics_followup,
        settings.max_concurrency,
    )


def _settings(**kwargs) -> Settings:
    base = dict(
        exact_temperature=0.0,
        exact_max_tokens_router=1024,
        exact_max_tokens_research=1024,
        exact_max_tokens_compress=2048,
        exact_max_tokens_write=8192,
        exact_reasoning_effort="none",
        exact_thinking_budget=0,
    )
    base.update(kwargs)
    return Settings(**base)


def test_chat_kwargs_gpt5_sets_reasoning_effort_from_settings():
    settings = _settings()
    kwargs = chat_kwargs(settings, "openai:gpt-5.6-luna", "research")
    assert kwargs["temperature"] == 0.0
    assert kwargs["reasoning_effort"] == "none"
    assert kwargs["max_tokens"] == 1024


def test_chat_kwargs_gpt4_omits_reasoning_effort():
    settings = _settings(exact_max_tokens_write=8192)
    kwargs = chat_kwargs(settings, "openai:gpt-4.1-mini", "write")
    assert kwargs["temperature"] == 0.0
    assert "reasoning_effort" not in kwargs
    assert kwargs["max_tokens"] == 8192


def test_chat_kwargs_anthropic_omits_reasoning_effort_when_budget_zero():
    settings = _settings()
    kwargs = chat_kwargs(settings, "anthropic:claude-haiku-4-5", "compress")
    assert kwargs["temperature"] == 0.0
    assert "reasoning_effort" not in kwargs
    assert "thinking" not in kwargs
    assert kwargs["max_tokens"] == 2048


def test_chat_kwargs_anthropic_enables_thinking_when_budget_set():
    settings = _settings(exact_thinking_budget=2048)
    kwargs = chat_kwargs(settings, "anthropic:claude-haiku-4-5", "router")
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_chat_kwargs_thinking_forces_temperature_1():
    settings = _settings(exact_temperature=0.0, exact_thinking_budget=1024)
    kwargs = chat_kwargs(settings, "anthropic:claude-haiku-4-5", "router")
    assert kwargs["temperature"] == 1


def test_chat_kwargs_thinking_lifts_max_tokens_above_the_budget():
    settings = _settings(exact_thinking_budget=1024, exact_max_tokens_router=1024)
    kwargs = chat_kwargs(settings, "anthropic:claude-haiku-4-5", "router")
    assert kwargs["max_tokens"] == 2048
    assert kwargs["max_tokens"] > kwargs["thinking"]["budget_tokens"]


def test_chat_kwargs_thinking_budget_leaves_non_anthropic_temperature_alone():
    settings = _settings(exact_temperature=0.0, exact_thinking_budget=1024)
    kwargs = chat_kwargs(settings, "openai:gpt-5.1", "router")
    assert kwargs["temperature"] == 0.0
    assert "thinking" not in kwargs


def test_chat_kwargs_reads_temperature_and_max_tokens_from_settings():
    settings = _settings(exact_temperature=0.2, exact_max_tokens_research=512)
    kwargs = chat_kwargs(settings, "anthropic:claude-haiku-4-5", "research")
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 512


def test_role_model_id_falls_back_to_exact_model():
    settings = _settings(exact_model="anthropic:claude-haiku-4-5")
    assert role_model_id(settings, "router") == "anthropic:claude-haiku-4-5"
    assert role_model_id(settings, "write") == "anthropic:claude-haiku-4-5"


def test_role_model_id_uses_override():
    settings = _settings(
        exact_model="anthropic:claude-haiku-4-5",
        exact_model_write="anthropic:claude-sonnet-4-5",
    )
    assert role_model_id(settings, "write") == "anthropic:claude-sonnet-4-5"
    assert role_model_id(settings, "research") == "anthropic:claude-haiku-4-5"


def test_role_max_tokens_reads_settings():
    settings = _settings(exact_max_tokens_compress=3000)
    assert role_max_tokens(settings, "compress") == 3000


def test_api_keys_are_hidden_from_settings_repr():
    settings = _settings(
        exa_api_key="exa-secret",
        openai_api_key="openai-secret",
        anthropic_api_key="anthropic-secret",
        elicit_api_key="elicit-secret",
    )
    text = repr(settings)
    assert "exa-secret" not in text
    assert "openai-secret" not in text
    assert "anthropic-secret" not in text
    assert "elicit-secret" not in text


def test_normal_profile_fills_every_knob():
    assert _knobs(Settings(_env_file=None)) == (3, 3, 4, 5, 3, 2, 3)


def test_max_profile_fills_every_knob():
    assert _knobs(Settings(_env_file=None, exact_effort="max")) == (4, 3, 6, 8, 4, 3, 4)


def test_effort_env_selects_the_profile(monkeypatch):
    monkeypatch.setenv("EXACT_EFFORT", "max")
    settings = Settings(_env_file=None)
    assert settings.exact_effort == "max"
    assert settings.max_hits == 8


def test_an_explicit_tool_rounds_env_survives_the_max_profile(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_ROUNDS", "4")
    assert Settings(_env_file=None, exact_effort="max").max_tool_rounds == 4


def test_an_explicit_hits_env_is_not_clamped(monkeypatch):
    monkeypatch.setenv("MAX_HITS", "99")
    assert Settings(_env_file=None, exact_effort="max").max_hits == 99


@pytest.mark.parametrize("value", ["MAX", ""])
def test_an_effort_outside_the_two_levels_is_rejected(value: str):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, exact_effort=value)


def test_concurrency_ignores_an_env_name(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENCY", "1")
    assert Settings(_env_file=None).max_concurrency == 3


def test_from_env_builds_the_role_llms_from_the_given_settings(monkeypatch):
    seen: list[Settings] = []

    def recorder(settings: Settings) -> dict:
        seen.append(settings)
        return dict.fromkeys(ROLES, FakeLLM())

    monkeypatch.setattr("exact.config._build_role_llms", recorder)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    settings = Settings(
        _env_file=None, exact_effort="max", exa_api_key="k", openai_api_key="k"
    )
    Runtime.from_env(settings)
    assert seen[0] is settings
    assert seen[0].max_tool_rounds == 6


def test_the_snapshot_prefers_thread_scoped_state_over_settings():
    snapshot = effort_snapshot(
        Settings(_env_file=None, exact_effort="max"),
        {"effort": "normal", "max_iterations": 3},
    )
    assert snapshot["effort"] == "normal"
    assert snapshot["max_iterations"] == 3
    assert snapshot["max_topics_first_wave"] == 4
    assert snapshot["max_hits"] == 8


def test_an_empty_state_takes_every_snapshot_value_from_settings():
    settings = Settings(_env_file=None, exact_effort="max")
    assert effort_snapshot(settings, {}) == {
        "effort": "max",
        "max_iterations": 4,
        "max_clarify_turns": 3,
        "max_topics_first_wave": 4,
        "max_topics_followup": 3,
        "max_tool_rounds": 6,
        "max_hits": 8,
        "max_concurrency": 4,
    }
