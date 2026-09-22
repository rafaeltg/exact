from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from exact.audit import audit_report
from exact.cli import main
from exact.models import ClarifyDecision, ResearchBrief
from exact.nodes.clarify import decide_clarify
from exact.nodes.research import research_agent
from exact.nodes.scout import scout
from exact.nodes.write import write_report
from exact.status import format_update
from exact.usage import (
    EXA_HIGHLIGHTS_USD,
    EXA_SEARCH_USD,
    StructuredOutputError,
    aggregate,
    format_usage,
    invoke_structured,
    invoke_text,
    llm_groups,
)
from tests.fakes import FakeElicit, FakeExa, FakeLLM, runtime, seed_prefs


def test_format_usage_haiku_tokens_literal_usd():
    events = [
        {
            "kind": "llm",
            "node": "write_report",
            "role": "write",
            "model": "anthropic:claude-haiku-4-5",
            "input_tokens": 1000,
            "output_tokens": 500,
            "calls": 1,
        }
    ]
    # 1000 * $1/M + 500 * $5/M = 0.001 + 0.0025 = 0.0035
    assert aggregate(events)["llm_cost"] == 0.0035
    lines = format_usage(events)
    assert lines[0] == "## Usage"
    assert "$0.0035" in lines[1]
    assert "total                                 $0.0035" in lines[-1]


def test_format_usage_prices_cache_read_and_write():
    events = [
        {
            "kind": "llm",
            "node": "write_report",
            "role": "write",
            "model": "anthropic:claude-haiku-4-5",
            # LangChain total input = uncached + read + write
            "input_tokens": 1100,
            "output_tokens": 0,
            "cache_read": 1000,
            "cache_creation": 100,
            "calls": 1,
        }
    ]
    # uncached 0 * $1 + 1000 * $0.10 + 100 * $1.25 = 0.1 + 0.125 = 0.225 / 1e6 wait
    # per million: 1000 * 0.1 + 100 * 1.25 = 100 + 125 = 225 → $0.000225
    assert abs(aggregate(events)["llm_cost"] - 0.000225) < 1e-12
    lines = format_usage(events)
    assert "cache  1000 read  100 write" in lines[2]


def test_write_captures_cache_tokens_from_usage_metadata():
    llm = FakeLLM(
        usage_metadata={
            "input_tokens": 110,
            "output_tokens": 20,
            "total_tokens": 130,
            "input_token_details": {"cache_read": 80, "cache_creation": 10},
        }
    )
    out = write_report(
        {
            "brief": {"question": "What is X?"},
            "findings": [],
            "sources": [
                {"id": "src_t0_1_1", "title": "A", "url": "u", "provider": "exa"}
            ],
            "uncovered": [],
        },
        runtime(llm=llm),
    )
    assert out["usage"][0]["cache_read"] == 80
    assert out["usage"][0]["cache_creation"] == 10
    assert out["usage"][0]["input_tokens"] == 110


def test_format_usage_unknown_model_is_named_and_omitted_from_dollars():
    events = [
        {
            "kind": "llm",
            "node": "write_report",
            "role": "write",
            "model": "anthropic:claude-opus-4-8",
            "input_tokens": 100,
            "output_tokens": 50,
            "calls": 1,
        },
        {"kind": "exa_search", "node": "scout", "calls": 1},
    ]
    lines = format_usage(events)
    assert "$0.0000 + 1 unpriced" in lines[1]
    assert "$0.0070+" in lines[-1]
    assert "llm unpriced" in lines[-1]


def test_format_usage_keeps_priced_calls_when_one_model_is_unpriced():
    events = [
        {
            "kind": "llm",
            "node": "decide_clarify",
            "role": "router",
            "model": "anthropic:claude-haiku-4-5",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "calls": 1,
        },
        {
            "kind": "llm",
            "node": "write_report",
            "role": "write",
            "model": "anthropic:claude-opus-4-8",
            "input_tokens": 100,
            "output_tokens": 50,
            "calls": 1,
        },
    ]
    a = aggregate(events)
    assert a["llm_cost"] == 1.0
    assert a["llm_unpriced_calls"] == 1
    assert a["total"] == 1.0
    assert "llm unpriced" in format_usage(events)[-1]


def test_format_usage_elicit_is_subscription_zero():
    events = [{"kind": "elicit_search", "node": "scout", "calls": 2}]
    a = aggregate(events)
    assert a["elicit_search"] == 2
    assert a["total"] == 0.0
    assert "(subscription)" in format_usage(events)[3]


def test_format_usage_exa_search_and_highlights():
    events = [
        {"kind": "exa_search", "node": "scout", "calls": 1},
        {"kind": "exa_highlights", "node": "research_agent", "calls": 1},
    ]
    a = aggregate(events)
    assert a["exa_cost"] == EXA_SEARCH_USD + EXA_HIGHLIGHTS_USD
    assert a["exa_cost"] == 0.008


def test_format_usage_people_and_company_price_as_exa_search():
    events = [
        {"kind": "exa_people_search", "node": "research_agent", "calls": 1},
        {"kind": "exa_company_search", "node": "research_agent", "calls": 2},
    ]
    a = aggregate(events)
    assert a["exa_search"] == 3
    assert a["exa_cost"] == 3 * EXA_SEARCH_USD


def test_publication_event_raises_exa_count_and_total():
    events = [
        {"kind": "exa_search", "node": "scout", "calls": 1},
        {"kind": "exa_publication_search", "node": "scout", "calls": 1},
    ]
    a = aggregate(events)
    assert a["exa_search"] == 2
    assert a["exa_cost"] == 2 * EXA_SEARCH_USD
    assert "exa     2 search" in format_usage(events)[2]
    assert format_update("research_agent", {"usage": events})[0].endswith(
        "1 exa_search · 1 exa_publication_search"
    )


def test_research_vertical_tool_events_match_successful_calls():
    llm = FakeLLM(tool_name="exa_people_search", tool_args={"query": "test"})
    out = research_agent(
        {
            "topic": {"id": "t0_1", "query": "define X", "focus": "people"},
            "brief": {"question": "What is X?", "intent": "web", "must_cover": ["x"]},
            "prior_titles": [],
        },
        runtime(llm=llm, exa=FakeExa()),
    )
    tool = [e for e in out["usage"] if e["kind"] == "exa_people_search"]
    assert tool == [{"kind": "exa_people_search", "node": "research_agent", "calls": 1}]


def test_write_report_records_usage_metadata():
    llm = FakeLLM(usage_metadata={"input_tokens": 10, "output_tokens": 20})
    out = write_report(
        {
            "brief": {"question": "What is X?"},
            "findings": [],
            "sources": [
                {"id": "src_t0_1_1", "title": "A", "url": "u", "provider": "exa"}
            ],
            "uncovered": [],
        },
        runtime(llm=llm),
    )
    assert out["usage"] == [
        {
            "kind": "llm",
            "node": "write_report",
            "role": "write",
            "model": "anthropic:claude-haiku-4-5",
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read": 0,
            "cache_creation": 0,
            "calls": 1,
        }
    ]


def test_structured_decide_clarify_records_usage_metadata():
    from exact.nodes.clarify import decide_clarify

    llm = FakeLLM(usage_metadata={"input_tokens": 3, "output_tokens": 4})
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "prefs": seed_prefs(),
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    assert out["usage"] == [
        {
            "kind": "llm",
            "node": "decide_clarify",
            "role": "router",
            "model": "anthropic:claude-haiku-4-5",
            "input_tokens": 3,
            "output_tokens": 4,
            "cache_read": 0,
            "cache_creation": 0,
            "calls": 1,
        }
    ]


def test_research_loop_records_tool_usage_metadata():
    llm = FakeLLM(
        tool_rounds=1,
        tool_usage_metadata={"input_tokens": 5, "output_tokens": 7},
    )
    out = research_agent(
        {
            "topic": {"id": "t0_1", "query": "define X", "status": "pending"},
            "brief": {"question": "What is X?", "intent": "web", "must_cover": ["x"]},
            "prior_titles": [],
        },
        runtime(llm=llm),
    )
    llm_events = [
        e for e in out["usage"] if e["kind"] == "llm" and e["role"] == "research"
    ]
    assert llm_events
    assert llm_events[0]["input_tokens"] == 5
    assert llm_events[0]["output_tokens"] == 7


def test_scout_emits_exa_usage_on_success():
    out = scout({"initial_query": "What is X?", "clarify_turns": 0}, runtime())
    assert out["usage"] == [{"kind": "exa_search", "node": "scout", "calls": 1}]


def test_scout_emits_a_publication_event_on_academic_success():
    out = scout(
        {"initial_query": "meta-analysis of X", "clarify_turns": 0},
        runtime(exa=FakeExa()),
    )
    kinds = [e["kind"] for e in out["usage"]]
    assert "exa_search" in kinds
    assert "exa_publication_search" in kinds


def test_scout_failure_has_no_tool_event():
    out = scout(
        {"initial_query": "What is X?", "clarify_turns": 0},
        runtime(exa=FakeExa(error=RuntimeError("down"))),
    )
    assert out["usage"] == []
    assert out["errors"]


def test_research_failure_has_no_tool_event():
    out = research_agent(
        {
            "topic": {"id": "t0_1", "query": "define X", "status": "pending"},
            "brief": {"question": "What is X?", "intent": "web", "must_cover": ["x"]},
            "prior_titles": [],
        },
        runtime(exa=FakeExa(error=RuntimeError("down"))),
    )
    assert out["errors"]
    assert not any(
        e["kind"]
        in (
            "exa_search",
            "exa_people_search",
            "exa_company_search",
            "exa_highlights",
            "elicit_search",
        )
        for e in out["usage"]
    )


def test_research_tool_events_match_successful_calls():
    out = research_agent(
        {
            "topic": {"id": "t0_1", "query": "define X", "status": "pending"},
            "brief": {"question": "What is X?", "intent": "web", "must_cover": ["x"]},
            "prior_titles": [],
        },
        runtime(exa=FakeExa()),
    )
    tool = [e for e in out["usage"] if e["kind"] == "exa_search"]
    assert tool == [{"kind": "exa_search", "node": "research_agent", "calls": 1}]


def test_disabled_elicit_adds_no_usage_event():
    llm = FakeLLM(tool_name="elicit_search", tool_args={"query": "x"}, tool_rounds=1)
    out = research_agent(
        {
            "topic": {"id": "t0_1", "query": "define X", "status": "pending"},
            "brief": {
                "question": "What is X?",
                "intent": "web",
                "must_cover": ["x"],
            },
            "prior_titles": [],
        },
        runtime(llm=llm, elicit=FakeElicit(enabled=False)),
    )
    assert not any(e["kind"] == "elicit_search" for e in out["usage"])


def test_cli_prints_usage_footer(capsys):
    code = main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "## Usage" in out
    assert "total" in out


def test_cli_prints_references_from_sources(capsys):
    code = main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "## References" in out
    assert "[src_t0_1_1]" in out


def test_format_references_lists_sources():
    from exact.nodes.write import format_references

    lines = format_references(
        [
            {
                "id": "src_t0_1_1",
                "title": "Source A",
                "url": "https://example.com/a",
                "provider": "exa",
            }
        ]
    )
    assert lines[0] == "## References"
    assert lines[1] == "[src_t0_1_1] Source A — https://example.com/a (web)"


def test_format_references_empty_when_no_sources():
    from exact.nodes.write import format_references

    assert format_references([]) == []
    assert format_references(None) == []


class _BlockContentModel:
    """Anthropic returns a block list when extended thinking is on."""

    def invoke(self, messages):
        return AIMessage(
            content=[
                {"type": "thinking", "thinking": "weighing the sources"},
                {"type": "text", "text": "X is Y [src_t0_1_1]."},
            ],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def test_invoke_text_joins_text_blocks_into_a_string():
    text, events = invoke_text(
        _BlockContentModel(),
        [HumanMessage(content="Write the report.")],
        node="write_report",
        role="write",
        model_id="anthropic:claude-haiku-4-5",
    )
    assert isinstance(text, str)
    assert text == "X is Y [src_t0_1_1]."
    assert "weighing the sources" not in text
    assert events[0]["input_tokens"] == 10


def test_write_report_with_block_content_stays_auditable():
    report, dangling = audit_report(
        invoke_text(
            _BlockContentModel(),
            [HumanMessage(content="Write the report.")],
            node="write_report",
            role="write",
            model_id="anthropic:claude-haiku-4-5",
        )[0],
        [{"id": "src_t0_1_1"}],
    )
    assert dangling == []
    assert "## Audit" not in report


class _ThinkingProseModel:
    """Anthropic cannot force a tool call while thinking is on."""

    def with_structured_output(self, schema, **_kwargs):
        return self

    def invoke(self, messages):
        raise OutputParserException("tool calls were not generated")


def test_structured_output_prose_under_thinking_raises_structured_output_error():
    with pytest.raises(StructuredOutputError):
        invoke_structured(
            _ThinkingProseModel(),
            ResearchBrief,
            [HumanMessage(content="Produce the brief.")],
            node="generate_brief",
            role="compress",
            model_id="anthropic:claude-haiku-4-5",
        )


def test_decide_clarify_skips_when_thinking_breaks_structured_output():
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "prefs": seed_prefs(),
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=_ThinkingProseModel()),
    )
    assert out["clarify_needed"] is False
    assert out["errors"]


def test_the_usage_heading_carries_the_effort_when_given():
    events = [{"kind": "llm", "model": "claude-haiku-4-5", "calls": 1}]
    assert format_usage(events, effort="max")[0] == "## Usage (effort=max)"


def test_the_usage_heading_stays_bare_without_an_effort():
    events = [{"kind": "llm", "model": "claude-haiku-4-5", "calls": 1}]
    assert format_usage(events)[0] == "## Usage"


def test_no_events_stay_empty_even_with_an_effort():
    assert format_usage([], effort="max") == []


def _priced_llm_event(**overrides) -> dict:
    event = {
        "kind": "llm",
        "node": "write_report",
        "role": "write",
        "model": "anthropic:claude-haiku-4-5",
        "input_tokens": 100,
        "output_tokens": 50,
        "calls": 1,
    }
    event.update(overrides)
    return event


def test_llm_groups_sum_to_the_llm_total():
    events = [
        _priced_llm_event(
            node="write_report",
            model="anthropic:claude-haiku-4-5",
            input_tokens=1000,
            output_tokens=500,
            cache_read=100,
            cache_creation=50,
        ),
        _priced_llm_event(
            node="research_agent",
            role="research",
            model="anthropic:claude-opus-4-8",
            input_tokens=200,
            output_tokens=100,
            calls=2,
        ),
        {"kind": "llm", "input_tokens": 30, "output_tokens": 7},
        {"kind": "exa_search", "node": "scout", "calls": 1},
    ]
    total = aggregate(events)
    for field in ("model", "node"):
        groups = llm_groups(events, field)
        assert sum(t["llm_calls"] for _, t in groups) == total["llm_calls"]
        for tok in ("input_tokens", "output_tokens", "cache_read", "cache_creation"):
            assert sum(t[tok] for _, t in groups) == total[tok]
        assert sum(t["llm_cost"] for _, t in groups) == pytest.approx(total["llm_cost"])


def test_llm_groups_merge_roles_of_one_model_and_one_node():
    events = [
        _priced_llm_event(node="research_agent", role="research"),
        _priced_llm_event(
            node="research_agent",
            role="compress",
            input_tokens=200,
            output_tokens=20,
        ),
    ]
    model_groups = llm_groups(events, "model")
    assert [key for key, _ in model_groups] == ["anthropic:claude-haiku-4-5"]
    assert model_groups[0][1]["llm_calls"] == 2

    node_groups = llm_groups(events, "node")
    assert [key for key, _ in node_groups] == ["research_agent"]
    assert node_groups[0][1]["llm_calls"] == 2


def test_llm_groups_sort_by_usd_then_tokens_then_key():
    events = [
        _priced_llm_event(
            node="n1",
            model="anthropic:claude-sonnet-4-6",
            input_tokens=10_000,
            output_tokens=0,
        ),
        _priced_llm_event(
            node="n2",
            model="anthropic:claude-haiku-4-5",
            input_tokens=5_000,
            output_tokens=0,
        ),
        _priced_llm_event(
            node="n3", model="aaa-unpriced", input_tokens=0, output_tokens=0
        ),
        _priced_llm_event(
            node="n4", model="zzz-haiku-4-5", input_tokens=0, output_tokens=0
        ),
        _priced_llm_event(
            node="n5", model="mmm-unpriced", input_tokens=100, output_tokens=0
        ),
    ]
    expected = [
        "anthropic:claude-sonnet-4-6",
        "anthropic:claude-haiku-4-5",
        "mmm-unpriced",
        "aaa-unpriced",
        "zzz-haiku-4-5",
    ]
    assert [key for key, _ in llm_groups(events, "model")] == expected
    assert [key for key, _ in llm_groups(list(reversed(events)), "model")] == expected


def test_llm_groups_break_an_equal_summed_usd_by_key():
    # 0.1 + 0.2 + 0.3 and 0.6 differ as floats; the order must not see that.
    events = [
        _priced_llm_event(node="y", input_tokens=100_000, output_tokens=0),
        _priced_llm_event(node="y", input_tokens=200_000, output_tokens=0),
        _priced_llm_event(node="y", input_tokens=300_000, output_tokens=0),
        _priced_llm_event(node="x", input_tokens=600_000, output_tokens=0),
    ]
    assert [key for key, _ in llm_groups(events, "node")] == ["x", "y"]
    assert [key for key, _ in llm_groups(list(reversed(events)), "node")] == [
        "x",
        "y",
    ]


def test_llm_groups_file_a_missing_key_under_unknown():
    no_model = _priced_llm_event(node="n1", input_tokens=10, calls=0)
    del no_model["model"]
    no_node = _priced_llm_event(input_tokens=1, output_tokens=1)
    del no_node["node"]
    empty_node = _priced_llm_event(node="", input_tokens=1, output_tokens=1)
    events = [no_model, no_node, empty_node]

    model_groups = dict(llm_groups(events, "model"))
    assert model_groups["(unknown)"]["llm_calls"] == 1
    assert model_groups["(unknown)"]["llm_unpriced_calls"] == 1

    node_groups = dict(llm_groups(events, "node"))
    assert node_groups["(unknown)"]["llm_calls"] == 2


def test_by_model_group_marks_an_unknown_model_unpriced():
    no_model = _priced_llm_event(input_tokens=10, output_tokens=5)
    del no_model["model"]
    assert "    (unknown)  1 calls  10 in  5 out   unpriced" in format_usage([no_model])


def test_llm_groups_skip_a_failed_structured_call():
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "prefs": seed_prefs(),
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=_ThinkingProseModel()),
    )
    assert llm_groups(out.get("usage") or [], "node") == []


def test_by_model_group_prints_one_line_per_model():
    events = [
        _priced_llm_event(
            node="write_report",
            model="anthropic:claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=200,
        ),
        _priced_llm_event(
            node="decide_clarify",
            role="router",
            model="anthropic:claude-haiku-4-5",
            input_tokens=500,
            output_tokens=100,
        ),
        _priced_llm_event(
            node="research_agent",
            role="research",
            model="anthropic:claude-opus-4-8",
            input_tokens=300,
            output_tokens=50,
        ),
    ]
    lines = format_usage(events)
    assert (
        "    anthropic:claude-sonnet-4-6  1 calls  1000 in  200 out   $0.0060" in lines
    )
    assert "    anthropic:claude-haiku-4-5  1 calls  500 in  100 out   $0.0010" in lines
    opus_line = next(line for line in lines if "claude-opus-4-8" in line)
    assert opus_line == (
        "    anthropic:claude-opus-4-8  1 calls  300 in  50 out   unpriced"
    )


def test_by_model_group_follows_the_llm_total_and_its_cache_line():
    cached = [
        _priced_llm_event(
            input_tokens=1100, output_tokens=0, cache_read=1000, cache_creation=100
        )
    ]
    lines = format_usage(cached)
    assert lines[3] == "  by model"
    assert lines[4].startswith("    anthropic:claude-haiku-4-5")
    assert lines[5].startswith("        cache")

    uncached = [_priced_llm_event(input_tokens=100, output_tokens=0)]
    lines_uncached = format_usage(uncached)
    assert not lines_uncached[4].startswith("        cache")


def test_by_model_group_ignores_event_order():
    events = [
        _priced_llm_event(
            node="n1",
            model="anthropic:claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=100,
        ),
        _priced_llm_event(
            node="n2",
            model="anthropic:claude-haiku-4-5",
            input_tokens=500,
            output_tokens=50,
        ),
        _priced_llm_event(
            node="n3",
            model="anthropic:claude-opus-4-8",
            input_tokens=300,
            output_tokens=30,
        ),
    ]
    assert format_usage(events) == format_usage(list(reversed(events)))


def test_footer_groups_print_node_usd_and_unpriced_count():
    events = [
        _priced_llm_event(
            node="research_agent",
            role="research",
            model="anthropic:claude-haiku-4-5",
            input_tokens=1000,
            output_tokens=0,
        ),
        _priced_llm_event(
            node="research_agent",
            role="compress",
            model="anthropic:claude-opus-4-8",
            input_tokens=100,
            output_tokens=0,
        ),
    ]
    lines = format_usage(events)
    node_line = next(line for line in lines if line.startswith("    research_agent"))
    assert node_line == (
        "    research_agent  2 calls  1100 in  0 out   $0.0010 + 1 unpriced"
    )


def test_footer_groups_lay_out_between_the_llm_total_and_exa():
    events = [
        _priced_llm_event(
            input_tokens=1100, output_tokens=0, cache_read=1000, cache_creation=100
        ),
        _priced_llm_event(
            node="research_agent",
            role="research",
            model="anthropic:claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=200,
        ),
        {"kind": "exa_search", "node": "scout", "calls": 1},
    ]
    assert format_usage(events) == [
        "## Usage",
        "llm     2 calls  2100 in  200 out   $0.0062",
        "        cache  1000 read  100 write",
        "  by model",
        "    anthropic:claude-sonnet-4-6  1 calls  1000 in  200 out   $0.0060",
        "    anthropic:claude-haiku-4-5  1 calls  1100 in  0 out   $0.0002",
        "        cache  1000 read  100 write",
        "  by node",
        "    research_agent  1 calls  1000 in  200 out   $0.0060",
        "    write_report  1 calls  1100 in  0 out   $0.0002",
        "        cache  1000 read  100 write",
        "exa     1 search  0 highlights        $0.0070",
        "elicit  0 search                      (subscription)",
        "total                                 $0.0132",
    ]


def test_footer_groups_are_absent_from_a_tool_only_footer():
    events = [
        {"kind": "exa_search", "node": "scout", "calls": 1},
        {"kind": "elicit_search", "node": "scout", "calls": 1},
    ]
    assert format_usage(events) == [
        "## Usage",
        "llm     0 calls  0 in  0 out   $0.0000",
        "exa     1 search  0 highlights        $0.0070",
        "elicit  1 search                      (subscription)",
        "total                                 $0.0070",
    ]


def test_footer_groups_print_at_the_clarify_pause(capsys):
    llm = FakeLLM(
        clarify=ClarifyDecision(needed=True, question="Scout found Source A. Focus?")
    )
    code = main(
        ["What is X?"],
        runtime=runtime(llm=llm),
        checkpointer=InMemorySaver(),
    )
    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    assert "  by model" in lines
    assert "  by node" in lines
    assert any(line.startswith("    decide_clarify  ") for line in lines)


def test_footer_groups_list_both_models_after_a_resume(capsys):
    llm = FakeLLM(
        clarify=ClarifyDecision(needed=True, question="Scout found Source A. Focus?")
    )
    saver = InMemorySaver()
    main(
        ["What is X?", "--thread-id", "t-usage-resume"],
        runtime=runtime(llm=llm, exact_model="anthropic:claude-haiku-4-5"),
        checkpointer=saver,
    )
    capsys.readouterr()
    main(
        ["What is X?", "--thread-id", "t-usage-resume"],
        runtime=runtime(llm=llm, exact_model="anthropic:claude-sonnet-4-6"),
        checkpointer=saver,
        read_reply=lambda: "skip",
    )
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("    anthropic:claude-haiku-4-5  ") for line in lines)
    assert any(line.startswith("    anthropic:claude-sonnet-4-6  ") for line in lines)
