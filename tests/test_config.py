from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from exact.config import (
    ROLES,
    Runtime,
    Settings,
    chat_kwargs,
    effort_snapshot,
    resolve_prefs,
    role_max_tokens,
    role_model_id,
)
from exact.prefs import PREF_FIELDS
from exact.trace import NullTracer
from tests.fakes import FakeLLM, RecordingTracer

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
        exact_thinking_budget=0,
    )
    base.update(kwargs)
    return Settings(**base)


def test_chat_kwargs_anthropic_omits_thinking_when_budget_zero():
    settings = _settings()
    kwargs = chat_kwargs(settings, "anthropic:claude-haiku-4-5", "compress")
    assert kwargs["temperature"] == 0.0
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
    kwargs = chat_kwargs(settings, "other:model-x", "router")
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
        anthropic_api_key="anthropic-secret",
        elicit_api_key="elicit-secret",
    )
    text = repr(settings)
    assert "exa-secret" not in text
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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    settings = Settings(
        _env_file=None, exact_effort="max", exa_api_key="k", anthropic_api_key="k"
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


def test_trace_and_verbose_default_to_off_and_an_empty_path():
    settings = Settings(_env_file=None)
    assert settings.exact_trace is False
    assert settings.exact_trace_path == ""
    assert settings.exact_verbose is False


@pytest.mark.parametrize(
    "name, field", [("EXACT_TRACE", "exact_trace"), ("EXACT_VERBOSE", "exact_verbose")]
)
def test_a_boolean_knob_env_of_1_reads_as_true(monkeypatch, name: str, field: str):
    monkeypatch.setenv(name, "1")
    assert getattr(Settings(_env_file=None), field) is True


def test_a_fresh_runtime_carries_a_null_tracer():
    rt = Runtime(settings=Settings(_env_file=None), llm=FakeLLM())
    assert isinstance(rt.tracer, NullTracer)


def test_replacing_the_tracer_leaves_the_original_runtime_alone():
    rt = Runtime(settings=Settings(_env_file=None), llm=FakeLLM())
    original = rt.tracer
    copy = dataclasses.replace(rt, tracer=RecordingTracer())
    assert rt.tracer is original
    assert isinstance(copy.tracer, RecordingTracer)


# ─── User preferences ───────────────────────────────────────────────────


def test_each_preference_defaults_with_no_env():
    settings = Settings(_env_file=None)
    assert (
        settings.exact_language,
        settings.exact_tone,
        settings.exact_length,
        settings.exact_structure,
        settings.exact_source_mix,
        settings.exact_include_domains,
        settings.exact_exclude_domains,
        settings.exact_denylist,
        settings.exact_recency,
        settings.exact_prefer_primary,
        settings.exact_news_bias,
        settings.exact_clarify_mode,
    ) == (
        "auto",
        "neutral",
        "standard",
        "report",
        "auto",
        [],
        [],
        "none",
        "any",
        False,
        False,
        "auto",
    )


@pytest.mark.parametrize(
    "name, raw, field, expected",
    [
        ("EXACT_LANGUAGE", "es", "exact_language", "es"),
        ("EXACT_TONE", "plain", "exact_tone", "plain"),
        ("EXACT_LENGTH", "long", "exact_length", "long"),
        ("EXACT_STRUCTURE", "memo", "exact_structure", "memo"),
        ("EXACT_SOURCE_MIX", "academic", "exact_source_mix", "academic"),
        ("EXACT_INCLUDE_DOMAINS", "a.com", "exact_include_domains", ["a.com"]),
        ("EXACT_EXCLUDE_DOMAINS", "a.com", "exact_exclude_domains", ["a.com"]),
        ("EXACT_DENYLIST", "social", "exact_denylist", "social"),
        ("EXACT_RECENCY", "week", "exact_recency", "week"),
        ("EXACT_PREFER_PRIMARY", "1", "exact_prefer_primary", True),
        ("EXACT_NEWS_BIAS", "true", "exact_news_bias", True),
        ("EXACT_CLARIFY_MODE", "prefer", "exact_clarify_mode", "prefer"),
    ],
)
def test_a_preference_env_sets_its_field(
    monkeypatch, name: str, raw: str, field: str, expected
):
    monkeypatch.setenv(name, raw)
    assert getattr(Settings(_env_file=None), field) == expected


def test_a_domain_preference_env_is_a_comma_separated_host_list(monkeypatch):
    monkeypatch.setenv("EXACT_EXCLUDE_DOMAINS", "a.com, b.com")
    assert Settings(_env_file=None).exact_exclude_domains == ["a.com", "b.com"]


@pytest.mark.parametrize("raw", ["Executive", " executive", "executive ", "EXECUTIVE"])
def test_an_enum_preference_matches_the_exact_lowercase_value(monkeypatch, raw: str):
    monkeypatch.setenv("EXACT_TONE", raw)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


_INCLUDE_CONFLICT = (
    "include domains cannot combine with exclude domains or a denylist "
    "(--include-domain, --exclude-domain, --denylist)"
)


def test_settings_refuse_include_with_exclude_preferences():
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None,
            exact_include_domains=["a.com"],
            exact_exclude_domains=["b.com"],
        )
    assert _INCLUDE_CONFLICT in str(exc.value)


def test_settings_refuse_include_with_a_denylist_preference():
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None, exact_include_domains=["a.com"], exact_denylist="social"
        )
    assert _INCLUDE_CONFLICT in str(exc.value)


@pytest.mark.parametrize("pref", PREF_FIELDS, ids=lambda pref: pref.name)
def test_every_preference_field_is_an_enum_a_boolean_or_a_host_list(pref):
    """No preference takes free text: a sentence fails every field."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{pref.field: "write like a pirate"})


def test_resolve_prefs_holds_every_d50_key_and_the_derived_values():
    settings = Settings(
        _env_file=None,
        exact_tone="plain",
        exact_exclude_domains=["quora.com", "a.com"],
        exact_denylist="seo",
        exact_recency="month",
    )
    prefs = resolve_prefs(settings, datetime(2026, 9, 21, 1, tzinfo=UTC))
    assert prefs == {
        "language": "auto",
        "tone": "plain",
        "length": "standard",
        "structure": "report",
        "source_mix": "auto",
        "include_domains": [],
        "exclude_domains": ["quora.com", "a.com"],
        "denylist": "seo",
        "recency": "month",
        "prefer_primary": False,
        "news_bias": False,
        "clarify_mode": "auto",
        "start_published_date": "2026-08-22",
        "effective_exclude_domains": [
            "quora.com",
            "a.com",
            "wikihow.com",
            "ehow.com",
            "answers.com",
            "reference.com",
            "medium.com",
            "hubpages.com",
            "ezinearticles.com",
        ],
    }
    assert prefs["exclude_domains"] is not settings.exact_exclude_domains
