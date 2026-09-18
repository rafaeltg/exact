from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from exact import prompts
from exact.models import PlanDecision, ReflectDecision
from exact.nodes import research as research_module
from exact.nodes.plan import plan_topics, route_research
from exact.nodes.reflect import reflect
from exact.nodes.research import (
    _Bag,
    _compact_sources,
    _render,
    research_agent,
)
from exact.nodes.scout import _interleave, scout
from tests.fakes import FakeExa, FakeLLM, runtime, source


def _payload(**overrides) -> dict:
    data = {
        "topic": {"id": "t0_1", "query": "define X", "status": "pending"},
        "brief": {
            "question": "What is X?",
            "intent": "web",
            "must_cover": ["define X"],
        },
        "prior_titles": [],
    }
    data.update(overrides)
    return data


def test_research_agent_returns_only_pruned_deltas():
    out = research_agent(_payload(), runtime())
    assert set(out) == {"sources", "findings", "errors", "usage"}
    assert "messages" not in out
    assert out["errors"] == []
    assert out["findings"][0]["topic_id"] == "t0_1"


def test_research_agent_does_not_expose_tool_transcript():
    from langchain_core.messages import ToolMessage

    llm = FakeLLM(tool_rounds=2)
    out = research_agent(_payload(), runtime(llm=llm))
    assert "messages" not in out
    assert any(isinstance(m, ToolMessage) for m in llm.last_tool_loop_messages)


def test_clip_tool_text_caps_at_tool_text_max():
    from exact.nodes.research import TOOL_TEXT_MAX, clip_tool_text

    assert clip_tool_text("short") == "short"
    assert len(clip_tool_text("x" * (TOOL_TEXT_MAX + 50))) == TOOL_TEXT_MAX


def test_tool_loop_strings_are_clipped_at_8000():
    from langchain_core.messages import ToolMessage

    from exact.nodes.research import TOOL_TEXT_MAX

    llm = FakeLLM(tool_rounds=1)
    research_agent(
        _payload(),
        runtime(llm=llm, exa=FakeExa(error=RuntimeError("x" * 20_000))),
    )
    tool_msgs = [m for m in llm.last_tool_loop_messages if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert all(len(str(m.content)) <= TOOL_TEXT_MAX for m in tool_msgs)


def test_begin_tool_session_resets_rounds_across_workers():
    llm = FakeLLM(tool_rounds=1)
    exa = FakeExa()
    rt = runtime(llm=llm, exa=exa)
    research_agent(
        _payload(topic={"id": "t0_1", "query": "a", "status": "pending"}), rt
    )
    research_agent(
        _payload(topic={"id": "t0_2", "query": "b", "status": "pending"}), rt
    )
    assert exa.search_nums == [5, 5]


def test_source_ids_use_topic_and_index():
    exa = FakeExa(hits=[source(title="A"), source(title="B")])
    out = research_agent(_payload(), runtime(exa=exa))
    assert [item["id"] for item in out["sources"]] == ["src_t0_1_1", "src_t0_1_2"]


@pytest.mark.parametrize("wanted, searches", [(3, 3), (4, 4), (5, 4)])
def test_tool_rounds_per_worker_cap_at_four(wanted: int, searches: int):
    llm = FakeLLM(tool_rounds=wanted)
    exa = FakeExa()
    research_agent(_payload(), runtime(llm=llm, exa=exa))
    assert exa.search_nums == [5] * searches


def test_hits_per_call_are_five():
    exa = FakeExa()
    research_agent(_payload(), runtime(exa=exa))
    assert exa.search_nums == [5]


def test_retrieval_failure_records_gaps_and_errors():
    out = research_agent(
        _payload(),
        runtime(exa=FakeExa(error=RuntimeError("down"))),
    )
    assert out["sources"] == []
    assert out["findings"][0]["gaps"] == ["lane web: retrieval failed"]
    assert out["findings"][0]["claims"] == []
    assert out["errors"]


def test_empty_hits_are_no_sources():
    out = research_agent(_payload(), runtime(exa=FakeExa(hits=[])))
    assert out["sources"] == []
    assert out["findings"][0]["gaps"] == ["lane web: no sources"]
    assert out["findings"][0]["claims"] == []


def test_research_drops_sources_already_in_prior_titles():
    out = research_agent(
        _payload(prior_titles=["Source A"]),
        runtime(exa=FakeExa(hits=[source(title="Source A")])),
    )
    assert out["sources"] == []
    assert out["findings"][0]["claims"] == []
    assert out["findings"][0]["gaps"] == ["lane web: no new sources"]


@pytest.mark.parametrize(
    "focus, search_tool",
    [
        ("web", "exa_search"),
        ("people", "exa_people_search"),
        ("company", "exa_company_search"),
        ("publication", "exa_publication_search"),
    ],
)
def test_focus_filters_tools(focus: str, search_tool: str):
    llm = FakeLLM()
    research_agent(
        _payload(topic={"id": "t0_1", "query": "define X", "focus": focus}),
        runtime(llm=llm, exa=FakeExa()),
    )
    assert [t.name for t in llm.bound.tools] == [search_tool, "exa_highlights"]


def test_a_missing_focus_binds_the_web_lane():
    llm = FakeLLM()
    research_agent(_payload(), runtime(llm=llm, exa=FakeExa()))
    assert [t.name for t in llm.bound.tools] == ["exa_search", "exa_highlights"]


def test_publication_lane_on_a_web_brief_binds_a_working_tool():
    """The intent gate is gone, so the lane alone decides."""
    llm = FakeLLM(tool_name="exa_publication_search", tool_args={"query": "test"})
    exa = FakeExa(hits=[source(title="Paper", doi="10.1/abc")])
    out = research_agent(
        _payload(
            topic={"id": "t0_1", "query": "trials of X", "focus": "publication"},
            brief={"question": "What is X?", "intent": "web", "must_cover": []},
        ),
        runtime(llm=llm, exa=exa),
    )
    assert exa.search_categories == ["publication"]
    assert out["sources"][0]["focus"] == "publication"


def test_no_worker_binds_elicit_search():
    llm = FakeLLM()
    research_agent(_payload(), runtime(llm=llm, exa=FakeExa()))
    assert "elicit_search" not in [t.name for t in llm.bound.tools]


def test_research_sys_states_the_lane():
    llm = FakeLLM()
    research_agent(
        _payload(topic={"id": "t0_1", "query": "trials of X", "focus": "publication"}),
        runtime(llm=llm, exa=FakeExa()),
    )
    prompt = str(llm.last_tool_loop_messages[0].content)
    assert "publication lane" in prompt
    assert "exa_people_search" not in prompts.RESEARCH_SYS


def test_empty_lane_names_itself():
    llm = FakeLLM(tool_name="exa_people_search", tool_args={"query": "test"})
    out = research_agent(
        _payload(topic={"id": "t0_1", "query": "who leads X", "focus": "people"}),
        runtime(llm=llm, exa=FakeExa(hits=[])),
    )
    assert out["findings"][0]["gaps"] == ["lane people: no sources"]


def test_two_empty_lanes_produce_two_gap_lines():
    gaps = []
    for focus, tool in (
        ("people", "exa_people_search"),
        ("company", "exa_company_search"),
    ):
        llm = FakeLLM(tool_name=tool, tool_args={"query": "test"})
        out = research_agent(
            _payload(topic={"id": "t0_1", "query": "X", "focus": focus}),
            runtime(llm=llm, exa=FakeExa(hits=[])),
        )
        gaps.extend(out["findings"][0]["gaps"])
    assert gaps == ["lane people: no sources", "lane company: no sources"]


def test_source_listings_label_publication():
    paper = {
        "id": "src_t0_1_1",
        "title": "Paper",
        "url": "https://doi.org/10.1/x",
        "provider": "exa",
        "focus": "publication",
        "snippet": "s",
    }
    assert "(publication)" in _render([paper])
    assert "(publication)" in _compact_sources([paper])


def test_scout_assigns_src_scout_ids():
    out = scout({"initial_query": "What is X?", "clarify_turns": 0}, runtime())
    assert out["scout_hits"][0]["id"] == "src_scout_1"
    assert out["errors"] == []


def test_scout_publication_search_runs_on_academic_signal():
    exa = FakeExa()
    out = scout(
        {"initial_query": "What do trials of GLP-1 show?", "clarify_turns": 0},
        runtime(exa=exa),
    )
    assert exa.search_categories == [None, "publication"]
    assert [hit["id"] for hit in out["scout_hits"]] == ["src_scout_1", "src_scout_2"]
    assert [hit["focus"] for hit in out["scout_hits"]] == ["web", "publication"]
    assert [e["kind"] for e in out["usage"]] == [
        "exa_search",
        "exa_publication_search",
    ]


def test_scout_interleaves_both_lanes_before_the_slice():
    """Both lanes must survive the eight-hit slice the brief takes."""
    exa = FakeExa(hits=[source(id=f"h{i}") for i in range(5)])
    out = scout(
        {"initial_query": "What do trials of GLP-1 show?", "clarify_turns": 0},
        runtime(exa=exa),
    )
    assert [hit["focus"] for hit in out["scout_hits"][:8]].count("publication") == 4


def test_scout_publication_failure_keeps_web_hits_and_appends_one_error():
    class _OnePublicationFailure(FakeExa):
        def search(self, query, num=5, *, category=None):
            if category == "publication":
                raise RuntimeError("boom")
            return super().search(query, num, category=category)

    out = scout(
        {"initial_query": "What do trials of GLP-1 show?", "clarify_turns": 0},
        runtime(exa=_OnePublicationFailure()),
    )
    assert len(out["scout_hits"]) == 1
    assert out["errors"] == ["exa publication scout failed: boom"]


def test_scout_appends_the_degraded_line_once():
    exa = FakeExa()
    exa.degraded = "exa publication search ran without abstracts or DOIs"
    out = scout(
        {"initial_query": "What do trials of GLP-1 show?", "clarify_turns": 0},
        runtime(exa=exa),
    )
    assert out["errors"] == ["exa publication search ran without abstracts or DOIs"]


def test_concurrent_ingest_mints_unique_source_ids(monkeypatch):
    """ToolNode runs one turn's tool calls in parallel threads.

    ``_mint`` is widened so the read-then-write window is reliably
    interleaved; the lock, not luck, is what keeps the ids unique.
    """
    real_mint = research_module._mint

    def slow_mint(topic_id, sources, start):
        time.sleep(0.01)
        return real_mint(topic_id, sources, start)

    monkeypatch.setattr(research_module, "_mint", slow_mint)
    bag = _Bag("t0_1", [], 5)
    batches = [[source(title=f"S{i}")] for i in range(20)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(bag.ingest, batches))
    ids = [s["id"] for s in bag.collected]
    assert len(ids) == 20
    assert len(set(ids)) == 20


def test_exa_highlights_reads_a_known_url():
    llm = FakeLLM(
        tool_script=[
            ("exa_search", {"query": "define X"}),
            ("exa_highlights", {"url": "https://example.com/a"}),
        ]
    )
    exa = FakeExa()
    out = research_agent(_payload(), runtime(llm=llm, exa=exa))
    assert exa.highlight_urls == ["https://example.com/a"]
    assert out["sources"][0]["id"] == "src_t0_1_1"


def test_exa_highlights_refuses_a_url_no_search_returned():
    llm = FakeLLM(
        tool_name="exa_highlights", tool_args={"url": "https://attacker.example/?q=x"}
    )
    exa = FakeExa()
    out = research_agent(_payload(), runtime(llm=llm, exa=exa))
    assert exa.highlight_urls == []
    assert out["sources"] == []
    assert out["findings"][0]["gaps"] == ["lane web: no sources"]


@pytest.mark.parametrize(
    "tool_name, category",
    [
        ("exa_people_search", "people"),
        ("exa_company_search", "company"),
    ],
)
def test_vertical_search_tools_pass_category(tool_name: str, category: str):
    llm = FakeLLM(tool_name=tool_name, tool_args={"query": "test"})
    exa = FakeExa(hits=[source(title="A"), source(title="B")])
    out = research_agent(
        _payload(topic={"id": "t0_1", "query": "define X", "focus": category}),
        runtime(llm=llm, exa=exa),
    )
    assert exa.search_categories == [category]
    assert exa.search_nums == [5]
    assert [item["id"] for item in out["sources"]] == ["src_t0_1_1", "src_t0_1_2"]


def test_vertical_search_failure_records_gaps_and_errors():
    llm = FakeLLM(tool_name="exa_people_search", tool_args={"query": "test"})
    out = research_agent(
        _payload(topic={"id": "t0_1", "query": "define X", "focus": "people"}),
        runtime(llm=llm, exa=FakeExa(error=RuntimeError("down"))),
    )
    assert out["findings"][0]["gaps"] == ["lane people: retrieval failed"]
    assert out["errors"]
    assert out["sources"] == []


def test_scout_skips_publication_search_without_academic_signal():
    exa = FakeExa()
    out = scout(
        {"initial_query": "Best laptop for travel", "clarify_turns": 0},
        runtime(exa=exa),
    )
    assert exa.search_categories == [None]
    assert all(hit["focus"] == "web" for hit in out["scout_hits"])


def test_scout_failure_returns_empty_hits_and_errors():
    out = scout(
        {"initial_query": "What is X?", "clarify_turns": 0},
        runtime(exa=FakeExa(error=RuntimeError("down"))),
    )
    assert out["scout_hits"] == []
    assert out["errors"][0].startswith("exa scout failed:")


def test_scout_asks_exa_for_five_hits():
    exa = FakeExa()
    scout({"initial_query": "What is X?", "clarify_turns": 0}, runtime(exa=exa))
    assert exa.search_nums == [5]


@pytest.mark.parametrize(
    "topics, expected",
    [
        (["topic 1", "topic 2"], ["topic 1", "topic 2"]),
        (["topic 1", "topic 2", "topic 3"], ["topic 1", "topic 2", "topic 3"]),
        (
            ["topic 1", "topic 2", "topic 3", "topic 4"],
            ["topic 1", "topic 2", "topic 3"],
        ),
    ],
)
def test_topics_per_wave_cap_at_three(topics: list[str], expected: list[str]):
    out = plan_topics(
        {
            "initial_query": "What is X?",
            "brief": {"question": "What is X?"},
            "iteration": 0,
            "topics": [],
        },
        runtime(llm=FakeLLM(plan=PlanDecision(topics=topics, reason="list"))),
    )
    assert [t["query"] for t in out["topics"]] == expected
    assert [row["query"] for row in out["prior_queries"]] == expected
    assert out["followups"] == []


def test_structured_output_failure_falls_back_to_one_topic():
    out = plan_topics(
        {
            "initial_query": "What is X?",
            "brief": {"question": "What is X?"},
            "iteration": 0,
            "topics": [],
        },
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert [t["query"] for t in out["topics"]] == ["What is X?"]
    assert out["errors"]
    assert "structured output missing" in out["errors"][0]


@pytest.mark.parametrize(
    "topics, expected",
    [
        (["follow 1"], ["follow 1"]),
        (["follow 1", "follow 2"], ["follow 1", "follow 2"]),
        (["follow 1", "follow 2", "follow 3"], ["follow 1", "follow 2"]),
    ],
)
def test_follow_up_topics_per_wave_cap_at_two(topics: list[str], expected: list[str]):
    out = plan_topics(
        {
            "initial_query": "What is X?",
            "brief": {"question": "What is X?"},
            "iteration": 1,
            "topics": [{"id": "t0_1", "query": "define X"}],
        },
        runtime(llm=FakeLLM(plan=PlanDecision(topics=topics, reason="gaps"))),
    )
    assert [t["query"] for t in out["topics"]] == expected
    assert [row["query"] for row in out["prior_queries"]] == ["define X", *expected]
    assert out["followups"] == []


def test_plan_drops_duplicate_prior_queries():
    out = plan_topics(
        {
            "initial_query": "What is X?",
            "brief": {"question": "What is X?"},
            "iteration": 1,
            "topics": [{"id": "t0_1", "query": "define X"}],
        },
        runtime(
            llm=FakeLLM(
                plan=PlanDecision(topics=["define X", "safety data"], reason="gaps")
            )
        ),
    )
    assert [t["query"] for t in out["topics"]] == ["safety data"]
    assert [row["query"] for row in out["prior_queries"]] == ["define X", "safety data"]
    assert out["followups"] == []


def test_plan_topics_follow_up_no_duplicate_queries_when_all_repeat():
    out = plan_topics(
        {
            "initial_query": "What is X?",
            "brief": {"question": "What is X?"},
            "iteration": 1,
            "topics": [{"id": "t0_1", "query": "define X"}],
            "followups": ["define X"],
        },
        runtime(llm=FakeLLM(plan=PlanDecision(topics=["define X"], reason="repeat"))),
    )
    assert out["topics"] == []
    assert [row["query"] for row in out["prior_queries"]] == ["define X"]
    assert out["followups"] == []


def test_route_research_writes_when_topics_empty():
    assert route_research({"topics": []}) == "write_report"


@pytest.mark.parametrize(
    "followups, expected",
    [
        (["a"], ["a"]),
        (["a", "b"], ["a", "b"]),
        (["a", "b", "c"], ["a", "b"]),
    ],
)
def test_reflect_followups_cap_at_two(followups: list[str], expected: list[str]):
    out = reflect(
        {
            "iteration": 0,
            "max_iterations": 3,
            "sources": [{"title": "Source A"}],
            "findings": [],
            "brief": {},
            "topics": [],
        },
        runtime(
            llm=FakeLLM(
                reflect=ReflectDecision(
                    done=False,
                    followups=followups,
                    uncovered=["gap"],
                )
            )
        ),
    )
    assert out["continue_research"] is True
    assert out["iteration"] == 1
    assert out["followups"] == expected
    assert "topics" not in out
    assert out["prior_titles"] == ["Source A"]


def test_reflect_still_allows_follow_up_at_iteration_one():
    out = reflect(
        {
            "iteration": 1,
            "max_iterations": 3,
            "sources": [],
            "findings": [],
            "brief": {},
            "topics": [],
        },
        runtime(
            llm=FakeLLM(
                reflect=ReflectDecision(done=False, followups=["more"], uncovered=[])
            )
        ),
    )
    assert out["continue_research"] is True
    assert out["iteration"] == 2


@pytest.mark.parametrize("iteration", [2, 3])
def test_reflect_forces_write_when_iteration_reaches_wave_cap(iteration: int):
    out = reflect(
        {
            "iteration": iteration,
            "max_iterations": 3,
            "sources": [],
            "findings": [{"gaps": ["no safety data"]}],
            "brief": {},
            "topics": [],
        },
        runtime(
            llm=FakeLLM(
                reflect=ReflectDecision(done=False, followups=["more"], uncovered=[])
            )
        ),
    )
    assert out["continue_research"] is False
    assert out["uncovered"] == ["no safety data"]


def test_structured_output_failure_forces_write():
    out = reflect(
        {
            "iteration": 0,
            "max_iterations": 3,
            "sources": [{"title": "Source A"}],
            "findings": [{"gaps": ["no safety data"]}],
            "brief": {},
            "topics": [],
        },
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert out["continue_research"] is False
    assert out["prior_titles"] == ["Source A"]
    assert out["uncovered"] == ["no safety data"]
    assert out["errors"]
    assert "structured output missing" in out["errors"][0]


def test_reflect_writes_when_done_or_no_followups():
    out = reflect(
        {
            "iteration": 0,
            "max_iterations": 3,
            "sources": [],
            "findings": [],
            "brief": {},
            "topics": [],
        },
        runtime(
            llm=FakeLLM(
                reflect=ReflectDecision(
                    done=True, followups=["ignored"], uncovered=["open"]
                )
            )
        ),
    )
    assert out["continue_research"] is False
    assert out["uncovered"] == ["open"]


def test_prune_uses_compress_role_llm():
    from exact.models import Finding

    research = FakeLLM()
    compress = FakeLLM(
        finding=Finding(
            topic_id="t0_1",
            claims=["from compress"],
            source_ids=["src_t0_1_1"],
            gaps=[],
            covered=["define X"],
        )
    )
    out = research_agent(
        _payload(),
        runtime(llm=research, llms={"research": research, "compress": compress}),
    )
    assert out["findings"][0]["claims"] == ["from compress"]


def test_prune_includes_a_user_message():
    from langchain_core.messages import HumanMessage

    from exact.models import Finding

    compress = FakeLLM()
    research_agent(
        _payload(),
        runtime(llm=FakeLLM(), llms={"research": FakeLLM(), "compress": compress}),
    )
    messages = compress.with_structured_output(Finding).last_messages
    assert any(isinstance(m, HumanMessage) for m in messages)


def test_write_report_uses_write_role_llm():
    from exact.nodes.write import write_report

    default = FakeLLM(report="default report")
    writer = FakeLLM(report="Writer role report [src_t0_1_1].")
    out = write_report(
        {
            "brief": {"question": "What is X?"},
            "findings": [
                {
                    "topic_id": "t0_1",
                    "claims": ["X is Y"],
                    "source_ids": ["src_t0_1_1"],
                    "gaps": [],
                }
            ],
            "sources": [
                {
                    "id": "src_t0_1_1",
                    "title": "A",
                    "url": "https://example.com",
                    "provider": "exa",
                }
            ],
            "uncovered": [],
        },
        runtime(llm=default, llms={"write": writer}),
    )
    assert out["final_report"] == "Writer role report [src_t0_1_1]."


def test_highlights_inherit_focus_and_doi():
    """A highlights read carries no lane; it takes both from the source it read."""
    paper = source(title="Paper", url="https://doi.org/10.1/x", doi="10.1/x")
    llm = FakeLLM(
        tool_script=[
            ("exa_publication_search", {"query": "trials of X"}),
            ("exa_highlights", {"url": "https://doi.org/10.1/x"}),
        ],
        tool_rounds=2,
    )
    out = research_agent(
        _payload(topic={"id": "t0_1", "query": "trials of X", "focus": "publication"}),
        runtime(llm=llm, exa=FakeExa(hits=[paper])),
    )
    assert out["sources"][1]["focus"] == "publication"
    assert out["sources"][1]["doi"] == "10.1/x"


def test_degraded_search_appends_an_error_not_a_gap():
    exa = FakeExa(hits=[])
    exa.degraded = "exa publication search ran without abstracts or DOIs"
    llm = FakeLLM(tool_name="exa_search", tool_args={"query": "test"})
    # No hits, so _gap_kind really runs and the gap assertion can fail.
    out = research_agent(_payload(), runtime(llm=llm, exa=exa))
    assert exa.degraded in out["errors"]
    assert all("retrieval failed" not in g for g in out["findings"][0]["gaps"])


@pytest.mark.parametrize(
    "web, papers, expected",
    [
        (3, 1, ["web", "publication", "web", "web"]),
        (1, 3, ["web", "publication", "publication", "publication"]),
        (0, 2, ["publication", "publication"]),
    ],
)
def test_interleave_keeps_every_hit_of_a_ragged_pair(
    web: int, papers: int, expected: list[str]
):
    got = _interleave(
        [{"focus": "web"} for _ in range(web)],
        [{"focus": "publication"} for _ in range(papers)],
    )
    assert [h["focus"] for h in got] == expected
