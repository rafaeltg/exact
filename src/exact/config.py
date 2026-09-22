from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from exact.prefs import (
    PREF_BY_FIELD,
    PREF_FIELDS,
    ClarifyMode,
    Denylist,
    Language,
    Length,
    Recency,
    SourceMix,
    Structure,
    Tone,
    effective_excludes,
    parse_hosts,
    start_date,
)
from exact.trace import NullTracer, Tracer

type Role = Literal["router", "research", "compress", "write"]
type Effort = Literal["normal", "max"]

ROLES: tuple[Role, ...] = ("router", "research", "compress", "write")


@dataclass(frozen=True)
class Profile:
    """One research-depth row: every graph cap a single effort level sets."""

    max_iterations: int
    max_clarify_turns: int
    max_tool_rounds: int
    max_hits: int
    max_topics_first_wave: int
    max_topics_followup: int
    max_concurrency: int


PROFILES: dict[Effort, Profile] = {
    "normal": Profile(
        max_iterations=3,
        max_clarify_turns=3,
        max_tool_rounds=4,
        max_hits=5,
        max_topics_first_wave=3,
        max_topics_followup=2,
        max_concurrency=3,
    ),
    "max": Profile(
        max_iterations=4,
        max_clarify_turns=3,
        max_tool_rounds=6,
        max_hits=8,
        max_topics_first_wave=4,
        max_topics_followup=3,
        max_concurrency=4,
    ),
}

# Only these four accept a MAX_* env override; the rest come from the profile.
_PROFILE_ENV_KNOBS = (
    "max_iterations",
    "max_clarify_turns",
    "max_tool_rounds",
    "max_hits",
)

# A thread-scoped knob is fixed when the thread starts and lives in its state.
_THREAD_SCOPED_KNOBS = (
    "max_iterations",
    "max_clarify_turns",
    "max_topics_first_wave",
    "max_topics_followup",
)

# A process-scoped knob follows the current shell, never the checkpoint.
_PROCESS_SCOPED_KNOBS = ("max_tool_rounds", "max_hits", "max_concurrency")

_ROLE_MODEL_FIELDS: dict[Role, str] = {
    "router": "exact_model_router",
    "research": "exact_model_research",
    "compress": "exact_model_compress",
    "write": "exact_model_write",
}

_ROLE_MAX_TOKEN_FIELDS: dict[Role, str] = {
    "router": "exact_max_tokens_router",
    "research": "exact_max_tokens_research",
    "compress": "exact_max_tokens_compress",
    "write": "exact_max_tokens_write",
}


_INCLUDE_CONFLICT = (
    "include domains cannot combine with exclude domains or a denylist "
    "(--include-domain, --exclude-domain, --denylist)"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    exa_api_key: str = Field(default="", repr=False)
    anthropic_api_key: str = Field(default="", repr=False)
    elicit_api_key: str = Field(default="", repr=False)
    exact_model: str = "anthropic:claude-haiku-4-5"
    exact_model_router: str = ""
    exact_model_research: str = ""
    exact_model_compress: str = ""
    exact_model_write: str = ""
    exact_temperature: float = 0.0
    exact_max_tokens_router: int = 1024
    exact_max_tokens_research: int = 1024
    exact_max_tokens_compress: int = 2048
    exact_max_tokens_write: int = 8192
    exact_thinking_budget: int = 0
    exact_db: str = "exact.sqlite"
    exact_trace: bool = False
    exact_trace_path: str = ""
    exact_verbose: bool = False
    exact_effort: Effort = "normal"
    exact_language: Language = "auto"
    exact_tone: Tone = "neutral"
    exact_length: Length = "standard"
    exact_structure: Structure = "report"
    exact_source_mix: SourceMix = "auto"
    exact_include_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    exact_exclude_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Validated even at its default: the include refusal must also fire when
    # the exclude list, not a preset, is what include meets.
    exact_denylist: Denylist = Field(default="none", validate_default=True)
    exact_recency: Recency = "any"
    exact_prefer_primary: bool = False
    exact_news_bias: bool = False
    exact_clarify_mode: ClarifyMode = "auto"
    max_iterations: int = 3
    max_clarify_turns: int = 3
    max_tool_rounds: int = 4
    max_hits: int = 5
    http_timeout: float = 20.0

    @field_validator("exact_include_domains", "exact_exclude_domains", mode="before")
    @classmethod
    def _parse_domains(cls, value: Any, info: ValidationInfo) -> list[str]:
        return parse_hosts(value, PREF_BY_FIELD[str(info.field_name)])

    @field_validator("exact_denylist")
    @classmethod
    def _refuse_include_with_excludes(cls, value: str, info: ValidationInfo) -> str:
        """Refuse an include list beside any exclude list or preset.

        Declaration order puts both domain lists before this field, so
        ``info.data`` holds them once they validated.
        """
        if not info.data.get("exact_include_domains"):
            return value
        if info.data.get("exact_exclude_domains") or value != "none":
            raise ValueError(_INCLUDE_CONFLICT)
        return value

    @model_validator(mode="after")
    def _fill_from_profile(self) -> Settings:
        """Fill every knob the environment did not set from the profile."""
        profile = PROFILES[self.exact_effort]
        for name in _PROFILE_ENV_KNOBS:
            if name not in self.model_fields_set:
                setattr(self, name, getattr(profile, name))
        return self

    @property
    def max_topics_first_wave(self) -> int:
        return PROFILES[self.exact_effort].max_topics_first_wave

    @property
    def max_topics_followup(self) -> int:
        return PROFILES[self.exact_effort].max_topics_followup

    @property
    def max_concurrency(self) -> int:
        return PROFILES[self.exact_effort].max_concurrency


def _model_leaf(model: str) -> str:
    return model.split(":", 1)[-1].lower()


def is_anthropic_model(model: str) -> bool:
    """True for ``anthropic:`` prefixes or Claude leaf ids."""
    if model.startswith("anthropic:"):
        return True
    return _model_leaf(model).startswith("claude")


def role_model_id(settings: Settings, role: Role) -> str:
    """Resolve the chat model id for ``role``, falling back to ``exact_model``."""
    override = (getattr(settings, _ROLE_MODEL_FIELDS[role]) or "").strip()
    return override or settings.exact_model


def role_max_tokens(settings: Settings, role: Role) -> int:
    return int(getattr(settings, _ROLE_MAX_TOKEN_FIELDS[role]))


def chat_kwargs(
    settings: Settings, model: str, role: Role = "research"
) -> dict[str, Any]:
    """Build ``init_chat_model`` kwargs for temperature, tokens, and thinking."""
    kwargs: dict[str, Any] = {
        "temperature": settings.exact_temperature,
        "max_tokens": role_max_tokens(settings, role),
    }
    if settings.exact_thinking_budget > 0 and is_anthropic_model(model):
        # Anthropic rejects any temperature but 1 while thinking is on, and
        # requires max_tokens above budget_tokens: the budget buys thinking,
        # the role cap still buys the reply.
        kwargs["temperature"] = 1
        kwargs["max_tokens"] = settings.exact_thinking_budget + role_max_tokens(
            settings, role
        )
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": settings.exact_thinking_budget,
        }
    return kwargs


def _build_role_llms(settings: Settings) -> dict[str, Any]:
    cache: dict[tuple[str, int, float, int], Any] = {}
    llms: dict[str, Any] = {}
    for role in ROLES:
        model_id = role_model_id(settings, role)
        max_tokens = role_max_tokens(settings, role)
        key = (
            model_id,
            max_tokens,
            settings.exact_temperature,
            settings.exact_thinking_budget,
        )
        if key not in cache:
            cache[key] = init_chat_model(
                model_id, **chat_kwargs(settings, model_id, role)
            )
        llms[role] = cache[key]
    return llms


@lru_cache
def get_settings() -> Settings:
    """Load ``.env`` once and return cached settings."""
    load_dotenv()
    return Settings()


def effort_snapshot(
    settings: Settings, state: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Collect the caps one run resolved, thread-scoped values from ``state``."""
    values = state or {}
    snapshot: dict[str, Any] = {"effort": values.get("effort") or settings.exact_effort}
    for name in _THREAD_SCOPED_KNOBS:
        snapshot[name] = values.get(name) or getattr(settings, name)
    for name in _PROCESS_SCOPED_KNOBS:
        snapshot[name] = getattr(settings, name)
    return snapshot


def resolve_prefs(settings: Settings, now: datetime) -> dict[str, Any]:
    """The run's ``prefs``: each resolved preference plus its derived values."""
    prefs: dict[str, Any] = {}
    for pref in PREF_FIELDS:
        value = getattr(settings, pref.field)
        prefs[pref.name] = list(value) if isinstance(value, list) else value
    prefs["start_published_date"] = start_date(settings.exact_recency, now)
    prefs["effective_exclude_domains"] = effective_excludes(
        settings.exact_exclude_domains, settings.exact_denylist
    )
    return prefs


def require_live_keys(settings: Settings) -> None:
    """Exit the process when required live API keys are missing."""
    if not settings.exa_api_key:
        raise SystemExit("EXA_API_KEY is required")
    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required")


@dataclass
class Runtime:
    """Injected settings, default LLM, and optional client/LLM extras."""

    settings: Settings
    llm: Any
    extras: dict[str, Any] = field(default_factory=dict)
    tracer: Tracer = field(default_factory=NullTracer)

    def model(self, role: Role) -> Any:
        """Return the per-role chat model, or ``llm`` when unset."""
        return (self.extras.get("llms") or {}).get(role) or self.llm

    @classmethod
    def from_env(cls, settings: Settings | None = None) -> Runtime:
        """Build a live runtime from the given or the cached settings."""
        if settings is None:
            settings = get_settings()
        require_live_keys(settings)
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
        llms = _build_role_llms(settings)
        return cls(settings=settings, llm=llms["research"], extras={"llms": llms})
