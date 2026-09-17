from __future__ import annotations

from exact.config import Settings, chat_kwargs, role_max_tokens, role_model_id


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
