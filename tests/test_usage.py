from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from exact.cli import main
from exact.nodes.research import research_agent
from exact.nodes.scout import scout
from exact.nodes.write import write_report
from exact.usage import EXA_HIGHLIGHTS_USD, EXA_SEARCH_USD, aggregate, format_usage
from tests.fakes import FakeElicit, FakeExa, FakeLLM, runtime, source


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


def test_format_usage_unknown_model_omits_llm_dollars():
    events = [
        {
            "kind": "llm",
            "node": "write_report",
            "role": "write",
            "model": "openai:gpt-4o",
            "input_tokens": 100,
            "output_tokens": 50,
            "calls": 1,
        },
        {"kind": "exa_search", "node": "scout", "calls": 1},
    ]
    lines = format_usage(events)
    assert "(unknown model)" in lines[1]
    assert "$0.0070+" in lines[-1]
    assert "llm unpriced" in lines[-1]


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


def test_research_vertical_tool_events_match_successful_calls():
    llm = FakeLLM(tool_name="exa_people_search", tool_args={"query": "test"})
    out = research_agent(
        {
            "topic": {"id": "t0_1", "query": "define X", "status": "pending"},
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
            "skip_clarify": False,
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


def test_scout_emits_elicit_on_academic_success():
    elicit = FakeElicit(hits=[source(provider="elicit", title="Paper")], enabled=True)
    out = scout(
        {"initial_query": "meta-analysis of X", "clarify_turns": 0},
        runtime(elicit=elicit, elicit_api_key="k"),
    )
    kinds = [e["kind"] for e in out["usage"]]
    assert "exa_search" in kinds
    assert "elicit_search" in kinds


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
    assert lines[1] == "[src_t0_1_1] Source A — https://example.com/a (exa)"


def test_format_references_empty_when_no_sources():
    from exact.nodes.write import format_references

    assert format_references([]) == []
    assert format_references(None) == []
