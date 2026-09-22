from __future__ import annotations

from datetime import UTC, datetime

import pytest

from exact.config import Settings, resolve_prefs
from exact.prefs import (
    PREF_BY_FIELD,
    default_prefs,
    effective_excludes,
    exa_filters,
    filter_names,
    filter_suffix,
    parse_hosts,
    start_date,
)
from tests.fakes import seed_prefs

_EXCLUDE = PREF_BY_FIELD["exact_exclude_domains"]


def test_parse_hosts_splits_a_comma_list_and_strips_spaces():
    assert parse_hosts(" A.com, b.com ,,", _EXCLUDE) == ["a.com", "b.com"]


@pytest.mark.parametrize(
    "entry",
    [
        "https://a.com",
        "*.a.com",
        "a.com/blog",
        "localhost",
        "a.com.",
        "münchen.de",
        "1.2.3.4",
        "a.com:80",
    ],
)
def test_parse_hosts_refuses_each_invalid_entry(entry: str):
    with pytest.raises(ValueError) as exc:
        parse_hosts(["b.com", entry], _EXCLUDE)
    message = str(exc.value)
    assert repr(entry) in message
    assert message.endswith("(--exclude-domain or EXACT_EXCLUDE_DOMAINS)")


def test_parse_hosts_accepts_punycode_and_keeps_www():
    assert parse_hosts(["xn--mnchen-3ya.de", "www.a.com", "a.com"], _EXCLUDE) == [
        "xn--mnchen-3ya.de",
        "www.a.com",
        "a.com",
    ]


def test_parse_hosts_accepts_20_hosts_and_refuses_21():
    twenty = [f"h{i}.com" for i in range(20)]
    assert parse_hosts(twenty, _EXCLUDE) == twenty
    assert parse_hosts([*twenty, "h0.com"], _EXCLUDE) == twenty
    with pytest.raises(ValueError) as exc:
        parse_hosts([*twenty, "h20.com"], _EXCLUDE)
    assert "21" in str(exc.value)
    assert str(exc.value).endswith("(--exclude-domain or EXACT_EXCLUDE_DOMAINS)")


def test_effective_excludes_sends_a_user_and_preset_host_once():
    got = effective_excludes(["quora.com", "a.com"], "seo")
    assert got == [
        "quora.com",
        "a.com",
        "wikihow.com",
        "ehow.com",
        "answers.com",
        "reference.com",
        "medium.com",
        "hubpages.com",
        "ezinearticles.com",
    ]


@pytest.mark.parametrize(
    "recency, expected",
    [
        ("any", None),
        ("week", "2026-09-14"),
        ("month", "2026-08-22"),
        ("year", "2025-09-21"),
    ],
)
def test_start_date_counts_utc_days_back_from_the_seed_instant(
    recency: str, expected: str | None
):
    assert start_date(recency, datetime(2026, 9, 21, 1, tzinfo=UTC)) == expected


def test_exa_filters_leave_out_empty_keys():
    assert exa_filters(seed_prefs()) == {}
    assert exa_filters(seed_prefs(denylist="social")) == {
        "exclude_domains": [
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "x.com",
            "twitter.com",
            "reddit.com",
            "pinterest.com",
            "linkedin.com",
        ]
    }
    assert exa_filters(seed_prefs(include_domains=["a.com"], recency="week")) == {
        "include_domains": ["a.com"],
        "start_published_date": "2026-09-14",
    }


def test_filter_names_follow_include_exclude_recency_order():
    filters = {
        "start_published_date": "2026-09-14",
        "exclude_domains": ["a.com"],
        "include_domains": ["b.com"],
    }
    assert filter_names(filters) == ["include", "exclude", "recency"]
    assert filter_suffix(filters) == " (filters: include, exclude, recency)"
    assert filter_suffix({}) == ""


def test_default_prefs_match_the_settings_defaults():
    assert default_prefs() == {
        "language": "auto",
        "tone": "neutral",
        "length": "standard",
        "structure": "report",
        "source_mix": "auto",
        "include_domains": [],
        "exclude_domains": [],
        "denylist": "none",
        "recency": "any",
        "prefer_primary": False,
        "news_bias": False,
        "clarify_mode": "auto",
        "start_published_date": None,
        "effective_exclude_domains": [],
    }
    now = datetime(2026, 9, 21, 1, tzinfo=UTC)
    assert resolve_prefs(Settings(_env_file=None), now) == default_prefs()
