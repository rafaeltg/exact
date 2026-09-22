from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, get_args

type Language = Literal["auto", "en", "es", "pt"]
type Tone = Literal["neutral", "academic", "executive", "plain"]
type Length = Literal["short", "standard", "long"]
type Structure = Literal["report", "memo", "bullets"]
type SourceMix = Literal["auto", "web", "academic", "mixed"]
type Denylist = Literal["none", "social", "seo"]
type Recency = Literal["any", "year", "month", "week"]
type ClarifyMode = Literal["auto", "skip", "prefer"]
type PrefKind = Literal["enum", "hosts", "bool"]

LANGUAGES: tuple[str, ...] = get_args(Language.__value__)
TONES: tuple[str, ...] = get_args(Tone.__value__)
LENGTHS: tuple[str, ...] = get_args(Length.__value__)
STRUCTURES: tuple[str, ...] = get_args(Structure.__value__)
SOURCE_MIXES: tuple[str, ...] = get_args(SourceMix.__value__)
DENYLISTS: tuple[str, ...] = get_args(Denylist.__value__)
RECENCIES: tuple[str, ...] = get_args(Recency.__value__)
CLARIFY_MODES: tuple[str, ...] = get_args(ClarifyMode.__value__)


@dataclass(frozen=True)
class PrefField:
    """One user preference: its state name, its setting, and how a user sets it."""

    name: str
    field: str
    flag: str
    env: str
    kind: PrefKind
    values: tuple[str, ...]


def _pref(
    name: str, flag: str, kind: PrefKind, values: tuple[str, ...] = ()
) -> PrefField:
    field = f"exact_{name}"
    return PrefField(name, field, flag, field.upper(), kind, values)


PREF_FIELDS: tuple[PrefField, ...] = (
    _pref("language", "--lang", "enum", LANGUAGES),
    _pref("tone", "--tone", "enum", TONES),
    _pref("length", "--length", "enum", LENGTHS),
    _pref("structure", "--structure", "enum", STRUCTURES),
    _pref("source_mix", "--sources", "enum", SOURCE_MIXES),
    _pref("include_domains", "--include-domain", "hosts"),
    _pref("exclude_domains", "--exclude-domain", "hosts"),
    _pref("denylist", "--denylist", "enum", DENYLISTS),
    _pref("recency", "--since", "enum", RECENCIES),
    _pref("prefer_primary", "--prefer-primary", "bool"),
    _pref("news_bias", "--news", "bool"),
    _pref("clarify_mode", "--clarify", "enum", CLARIFY_MODES),
)

PREF_BY_FIELD: dict[str, PrefField] = {pref.field: pref for pref in PREF_FIELDS}

# The one enum whose default is not its first value.
_ENUM_DEFAULTS = {"length": "standard"}

PRESET_HOSTS: dict[str, tuple[str, ...]] = {
    "none": (),
    "social": (
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "x.com",
        "twitter.com",
        "reddit.com",
        "pinterest.com",
        "linkedin.com",
    ),
    "seo": (
        "quora.com",
        "wikihow.com",
        "ehow.com",
        "answers.com",
        "reference.com",
        "medium.com",
        "hubpages.com",
        "ezinearticles.com",
    ),
}

MAX_HOSTS = 20

_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

_RECENCY_DAYS = {"year": 365, "month": 30, "week": 7}


def _default(pref: PrefField) -> Any:
    if pref.kind == "hosts":
        return []
    if pref.kind == "bool":
        return False
    return _ENUM_DEFAULTS.get(pref.name, pref.values[0])


def default_prefs() -> dict[str, Any]:
    """A fresh ``prefs`` dict with every preference at its default."""
    prefs = {pref.name: _default(pref) for pref in PREF_FIELDS}
    prefs["start_published_date"] = None
    prefs["effective_exclude_domains"] = []
    return prefs


def _is_host(entry: str) -> bool:
    """A strict ASCII host: two or more labels, and not a numeric address."""
    if not entry.isascii():
        return False
    labels = entry.split(".")
    if len(labels) < 2 or labels[-1].isdigit():
        return False
    return all(_LABEL.fullmatch(label) for label in labels)


def parse_hosts(raw: str | Sequence[str], pref: PrefField) -> list[str]:
    """Normalize a host list from a comma string or repeated flags.

    Raises:
        ValueError: an entry is not a host, or the list holds too many hosts.
    """
    entries = raw.split(",") if isinstance(raw, str) else list(raw)
    cleaned = [entry.strip().lower() for entry in entries]
    hosts = list(dict.fromkeys(entry for entry in cleaned if entry))
    source = f"({pref.flag} or {pref.env})"
    for host in hosts:
        if not _is_host(host):
            raise ValueError(f"{pref.name}: {host!r} is not a host name {source}")
    if len(hosts) > MAX_HOSTS:
        raise ValueError(
            f"{pref.name} holds {len(hosts)} hosts; at most {MAX_HOSTS} {source}"
        )
    return hosts


def effective_excludes(user: Sequence[str], denylist: str) -> list[str]:
    """The user hosts, then the preset hosts, each host once."""
    return list(dict.fromkeys([*user, *PRESET_HOSTS[denylist]]))


def start_date(recency: str, now: datetime) -> str | None:
    """The first publish date a ``recency`` window keeps, as a UTC date."""
    days = _RECENCY_DAYS.get(recency)
    if days is None:
        return None
    return (now.astimezone(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")


def state_prefs(state: Mapping[str, Any]) -> dict[str, Any]:
    """The thread's ``prefs``; a checkpoint written before them reads as defaults."""
    return state.get("prefs") or default_prefs()


def legacy_prefs(skip_clarify: bool) -> dict[str, Any]:
    """The ``prefs`` of a checkpoint written before threads stored them."""
    prefs = default_prefs()
    if skip_clarify:
        prefs["clarify_mode"] = "skip"
    return prefs


def render_value(value: Any) -> str:
    """One preference value as the echo line and the mismatch message print it."""
    if isinstance(value, list):
        return ",".join(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _same(pref: PrefField, stored: Any, resolved: Any) -> bool:
    """Host lists compare as sets: a resume may list the hosts in another order."""
    if pref.kind == "hosts":
        return sorted(set(stored or [])) == sorted(set(resolved or []))
    return stored == resolved


def pref_mismatches(
    stored: Mapping[str, Any], resolved: Mapping[str, Any]
) -> list[str]:
    """One ``name thread=... run=...`` part per preference that differs.

    The start date is derived from ``recency`` and the seed instant, so it
    never differs on its own.
    """
    return [
        f"{pref.name} thread={render_value(stored.get(pref.name))} "
        f"run={render_value(resolved.get(pref.name))}"
        for pref in PREF_FIELDS
        if not _same(pref, stored.get(pref.name), resolved.get(pref.name))
    ]


# Each Exa filter argument, by the name a lane gap gives it.
_FILTER_NAMES = {
    "include_domains": "include",
    "exclude_domains": "exclude",
    "start_published_date": "recency",
}


def exa_filters(prefs: Mapping[str, Any]) -> dict[str, Any]:
    """The Exa filter arguments of a filtered search; an empty filter is left out."""
    filters = {
        "include_domains": list(prefs.get("include_domains") or []),
        "exclude_domains": list(prefs.get("effective_exclude_domains") or []),
        "start_published_date": prefs.get("start_published_date"),
    }
    return {key: value for key, value in filters.items() if value}


def filter_names(filters: Mapping[str, Any]) -> list[str]:
    """The short names of the active filters, in include, exclude, recency order."""
    return [name for key, name in _FILTER_NAMES.items() if key in filters]


def filter_suffix(filters: Mapping[str, Any]) -> str:
    """The `` (filters: ...)`` tail of a filtered gap or error line."""
    if not filters:
        return ""
    return f" (filters: {', '.join(filter_names(filters))})"


# The brief audience each non-neutral tone fixes.
AUDIENCES = {
    "academic": "academic researchers",
    "executive": "executives",
    "plain": "general public",
}


def brief_notes(prefs: Mapping[str, Any]) -> list[str]:
    """The brief exclusion notes the domain preferences add, hosts in stored order."""
    notes = []
    if prefs.get("exclude_domains"):
        notes.append(f"Exclude sources from {', '.join(prefs['exclude_domains'])}")
    preset = PRESET_HOSTS[prefs.get("denylist") or "none"]
    if preset:
        notes.append(f"Exclude {prefs['denylist']} sites: {', '.join(preset)}")
    if prefs.get("include_domains"):
        notes.append(f"Use only sources from {', '.join(prefs['include_domains'])}")
    return notes
