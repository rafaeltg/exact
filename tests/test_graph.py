from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from exact.graph import build_graph
from exact.models import (
    ClarificationOption,
    ClarifyDecision,
    Finding,
    PlanDecision,
    ReflectDecision,
)
from tests.fakes import FakeExa, FakeLLM, graph_seed, runtime, source


def _config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def test_skip_clarify_produces_cited_report():
    app = build_graph(runtime())
    config = _config("t-cite")
    result = app.invoke(graph_seed(), config)
    assert app.get_state(config).next == ()
    assert result["brief"]["question"] == "What is X?"
    assert result["final_report"] == "X is Y [src_t0_1_1]."


def test_every_src_citation_in_the_report_exists_in_sources():
    app = build_graph(
        runtime(
            llm=FakeLLM(
                finding=Finding(
                    topic_id="t0_1",
                    claims=["X is Y", "Z is W"],
                    source_ids=["src_t0_1_1", "src_t0_1_2"],
                    gaps=[],
                    covered=["define X"],
                ),
                report="X is Y [src_t0_1_1]. Z is W [src_t0_1_2].",
            ),
            exa=FakeExa(hits=[source(title="A"), source(title="B")]),
        )
    )
    result = app.invoke(graph_seed(), _config("t-coverage"))
    ids = {item["id"] for item in result["sources"]}
    assert "[src_t0_1_1]" in result["final_report"]
    assert "[src_t0_1_2]" in result["final_report"]
    assert "src_t0_1_1" in ids
    assert "src_t0_1_2" in ids
    assert "## Audit" not in result["final_report"]


def test_dangling_report_citations_fail_the_audit():
    app = build_graph(runtime(llm=FakeLLM(report="Claim [src_missing].")))
    result = app.invoke(graph_seed(), _config("t-dangle"))
    assert "## Audit" in result["final_report"]
    assert "dangling:src_missing" in result["uncovered"]


def test_uncovered_lists_finding_gaps():
    app = build_graph(
        runtime(
            llm=FakeLLM(
                finding=Finding(
                    topic_id="t0_1",
                    claims=["X is Y"],
                    source_ids=["src_t0_1_1"],
                    gaps=["no safety data"],
                    covered=["define X"],
                )
            )
        )
    )
    result = app.invoke(graph_seed(), _config("t-honest"))
    assert "no safety data" in result["uncovered"]


def test_retrieval_failure_still_finishes_the_graph():
    app = build_graph(
        runtime(
            llm=FakeLLM(report="No sources found."),
            exa=FakeExa(error=RuntimeError("down")),
        )
    )
    config = _config("t-fail")
    result = app.invoke(graph_seed(), config)
    assert app.get_state(config).next == ()
    assert result["final_report"] == "No sources found."
    assert result["errors"]
    assert result["findings"][0]["gaps"] == ["lane web: retrieval failed"]
    assert "lane web: retrieval failed" in result["uncovered"]


def test_parent_messages_are_the_clarify_thread_only():
    app = build_graph(runtime())
    result = app.invoke(graph_seed(), _config("t-msgs"))
    assert result["messages"] == []


def test_scout_runs_before_clarify():
    app = build_graph(runtime())
    nodes = [
        node
        for chunk in app.stream(
            graph_seed(), _config("t-scout-first"), stream_mode="updates"
        )
        for node in chunk
    ]
    assert nodes.index("scout") < nodes.index("decide_clarify")


def test_write_runs_once_after_research():
    app = build_graph(runtime())
    nodes = [
        node
        for chunk in app.stream(graph_seed(), _config("t-write"), stream_mode="updates")
        for node in chunk
    ]
    assert nodes.index("research_agent") < nodes.index("write_report")
    assert nodes.count("write_report") == 1
    assert nodes[-2:] == ["write_report", "audit_citations"]


def test_needed_false_skips_interrupt_and_writes_brief():
    app = build_graph(runtime())
    config = _config("t-not-needed")
    result = app.invoke(graph_seed(skip_clarify=False), config)
    assert app.get_state(config).next == ()
    assert result["brief"]["question"] == "What is X?"
    assert result["final_report"]


def test_isolated_workers_mint_source_ids_per_topic():
    app = build_graph(
        runtime(llm=FakeLLM(plan=PlanDecision(topics=["define X", "safety of X"])))
    )
    result = app.invoke(graph_seed(), _config("t-workers"))
    topic_ids = {item["topic_id"] for item in result["findings"]}
    ids = {item["id"] for item in result["sources"]}
    assert topic_ids == {"t0_1", "t0_2"}
    assert "src_t0_1_1" in ids
    assert "src_t0_2_1" in ids
    assert result["messages"] == []


def test_skip_clarify_does_not_interrupt_even_if_model_would_ask():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-force-skip")
    result = app.invoke(graph_seed(skip_clarify=True), config)
    assert app.get_state(config).next == ()
    assert result["brief"]["question"] == "What is X?"


def test_clarify_interrupts_when_needed():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-hitl")
    app.invoke(graph_seed(skip_clarify=False), config)
    snap = app.get_state(config)
    assert snap.next == ("ask_user",)


def test_same_thread_id_continues_after_interrupt():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-resume")
    app.invoke(graph_seed(skip_clarify=False), config)
    result = app.invoke(Command(resume="skip"), config)
    snap = app.get_state(config)
    assert snap.next == ()
    assert result["user_clarification"]["kind"] == "skip"
    # The clarify thread holds the question asked and the answer given, so a
    # later decide_clarify turn can see both.
    assert (
        result["messages"][-2].content
        == "Scout found Source A. Focus on mechanisms or outcomes?"
    )
    assert result["messages"][-1].content == "User clarification (skip): skip"
    assert not any(isinstance(m, ToolMessage) for m in result["messages"])
    assert result["final_report"]


def test_resume_pick_records_the_option():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-pick")
    app.invoke(graph_seed(skip_clarify=False), config)
    result = app.invoke(Command(resume="1"), config)
    assert result["user_clarification"]["kind"] == "pick"
    assert result["user_clarification"]["option_ids"] == ["opt_1"]
    assert result["messages"][-1].content == "User clarification (pick): opt_1"


def test_invalid_resume_is_skip():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-invalid")
    app.invoke(graph_seed(skip_clarify=False), config)
    result = app.invoke(Command(resume={"kind": "bogus"}), config)
    assert result["user_clarification"]["kind"] == "skip"
    assert app.get_state(config).next == ()


def test_clarify_still_asks_after_two_text_turns():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-two")
    app.invoke(graph_seed(skip_clarify=False), config)
    app.invoke(Command(resume="angle one"), config)
    app.invoke(Command(resume="angle two"), config)
    snap = app.get_state(config)
    assert snap.next == ("ask_user",)
    assert snap.values["clarify_turns"] == 2


def test_clarify_proceeds_after_three_turns():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm))
    config = _config("t-three")
    app.invoke(graph_seed(skip_clarify=False), config)
    app.invoke(Command(resume="angle one"), config)
    app.invoke(Command(resume="angle two"), config)
    result = app.invoke(Command(resume="angle three"), config)
    snap = app.get_state(config)
    assert snap.next == ()
    assert result["clarify_turns"] == 3
    assert result["final_report"]


def test_ask_user_respects_max_clarify_turns():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms or outcomes?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    app = build_graph(runtime(llm=llm, max_clarify_turns=2))
    config = _config("t-cap-2")
    app.invoke(graph_seed(skip_clarify=False, max_clarify_turns=2), config)
    app.invoke(Command(resume="angle one"), config)
    result = app.invoke(Command(resume="angle two"), config)
    snap = app.get_state(config)
    assert snap.next == ()
    assert result["clarify_turns"] == 2
    assert result["final_report"]


def test_reflect_followups_return_to_plan_topics():
    app = build_graph(
        runtime(
            llm=FakeLLM(
                plan=[
                    PlanDecision(topics=["define X"], reason="simple"),
                    PlanDecision(topics=["missing safety"], reason="gaps"),
                ],
                reflect=[
                    ReflectDecision(
                        done=False, followups=["missing safety"], uncovered=["safety"]
                    ),
                    ReflectDecision(done=True, followups=[], uncovered=["safety"]),
                ],
            )
        )
    )
    config = _config("t-wave")
    nodes = [
        node
        for chunk in app.stream(graph_seed(), config, stream_mode="updates")
        for node in chunk
    ]
    result = app.get_state(config).values
    assert nodes.count("plan_topics") == 2
    assert nodes.count("research_agent") == 2
    assert nodes.count("write_report") == 1
    assert result["iteration"] == 1
    assert result["topics"][0]["query"] == "missing safety"


def test_third_wave_forces_write():
    app = build_graph(
        runtime(
            llm=FakeLLM(
                plan=[
                    PlanDecision(topics=["define X"], reason="simple"),
                    PlanDecision(topics=["more"], reason="gaps"),
                    PlanDecision(topics=["still more"], reason="gaps"),
                ],
                reflect=ReflectDecision(done=False, followups=["more"], uncovered=[]),
            )
        )
    )
    nodes: list[str] = []
    for i, chunk in enumerate(
        app.stream(graph_seed(), _config("t-three-wave"), stream_mode="updates")
    ):
        nodes.extend(chunk)
        if i > 40:
            break
    assert nodes.count("research_agent") == 3
    assert nodes.count("write_report") == 1
