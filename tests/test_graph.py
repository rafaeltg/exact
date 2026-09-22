from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from exact.cli import main, thread_config
from exact.graph import build_graph
from exact.models import (
    ClarificationOption,
    ClarifyDecision,
    Finding,
    PlanDecision,
    ReflectDecision,
)
from exact.nodes.plan import route_research
from exact.nodes.scout import scout
from tests.fakes import (
    FakeExa,
    FakeLLM,
    RecordingTracer,
    graph_seed,
    read_trace,
    runtime,
    seed_prefs,
    source,
)


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
    result = app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    result = app.invoke(graph_seed(), config)
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
    app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    app.invoke(graph_seed(prefs=seed_prefs()), config)
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
    app.invoke(graph_seed(prefs=seed_prefs(), max_clarify_turns=2), config)
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


def _max_wave_runtime(exa: FakeExa | None = None) -> object:
    return runtime(
        exa=exa,
        llm=FakeLLM(
            plan=[
                PlanDecision(topics=["a", "b", "c", "d"], reason="broad"),
                PlanDecision(topics=["e", "f", "g"], reason="gaps"),
            ],
            reflect=[
                ReflectDecision(done=False, followups=["e", "f", "g"], uncovered=[]),
                ReflectDecision(done=True, followups=[], uncovered=[]),
            ],
        ),
        exact_effort="max",
    )


def test_max_effort_fans_out_four_then_three_topics():
    exa = FakeExa()
    app = build_graph(_max_wave_runtime(exa))
    config = _config("t-max-waves")
    app.invoke(
        graph_seed(
            effort="max",
            max_iterations=4,
            max_topics_first_wave=4,
            max_topics_followup=3,
        ),
        config,
    )
    ids = {f["topic_id"] for f in app.get_state(config).values["findings"]}
    assert {"t0_1", "t0_2", "t0_3", "t0_4"} <= ids
    assert {"t1_1", "t1_2", "t1_3"} <= ids
    assert set(exa.search_nums) == {8}


def test_a_checkpoint_without_the_cap_channels_falls_back_to_settings():
    """A thread seeded before this feature reads the caps from the run's profile.

    This is the library path. Through the CLI, ``_guard_effort`` refuses a
    resume under any effort but the checkpoint's, so only ``normal`` reaches
    here in a real run.
    """
    seed = graph_seed()
    for key in ("effort", "max_topics_first_wave", "max_topics_followup"):
        del seed[key]
    app = build_graph(_max_wave_runtime())
    config = _config("t-pre-upgrade")
    app.invoke(seed, config)
    ids = {f["topic_id"] for f in app.get_state(config).values["findings"]}
    assert {"t0_1", "t0_2", "t0_3", "t0_4"} <= ids


def _three_topic_runtime(exa: FakeExa) -> object:
    return runtime(
        exa=exa,
        llm=FakeLLM(plan=PlanDecision(topics=["a", "b", "c"], reason="broad")),
    )


def test_one_worker_at_a_time_under_max_concurrency_one():
    exa = FakeExa(delay=0.1)
    build_graph(_three_topic_runtime(exa)).invoke(
        graph_seed(), thread_config("t-c1", max_concurrency=1)
    )
    assert exa.peak == 1


def test_workers_overlap_under_max_concurrency_three():
    exa = FakeExa(delay=0.1)
    build_graph(_three_topic_runtime(exa)).invoke(
        graph_seed(), thread_config("t-c3", max_concurrency=3)
    )
    assert exa.peak >= 2


# ─── Trace: scout tool lines and the join invariant ─────────────────────

_ACADEMIC = "What do trials of GLP-1 show?"


def _scout_tools(query: str, exa: FakeExa) -> list[dict]:
    tracer = RecordingTracer()
    scout({"initial_query": query, "clarify_turns": 0}, runtime(exa=exa, tracer=tracer))
    return tracer.payloads("tool")


def test_a_non_academic_scout_writes_one_tool_line():
    lines = _scout_tools("What is X?", FakeExa())
    assert [(line["name"], line["outcome"]) for line in lines] == [("exa_search", "ok")]
    assert lines[0]["topic_id"] == "scout"
    assert lines[0]["wave"] is None
    assert lines[0]["query"] == "What is X?"


def test_an_academic_scout_writes_one_tool_line_per_leg():
    lines = _scout_tools(_ACADEMIC, FakeExa())
    assert [line["name"] for line in lines] == ["exa_search", "exa_publication_search"]


def test_every_scout_crumb_carries_a_minted_scout_id():
    exa = FakeExa(hits=[source(title="A"), source(title="B")])
    crumbs = [c for line in _scout_tools(_ACADEMIC, exa) for c in line["sources"]]
    assert sorted(c["id"] for c in crumbs) == [f"src_scout_{i}" for i in range(1, 5)]


def test_a_failing_scout_leg_writes_an_error_line_beside_the_ok_leg():
    exa = FakeExa(failing={"publication": RuntimeError("papers down")})
    web, papers = _scout_tools(_ACADEMIC, exa)
    assert (web["outcome"], web["hit_count"]) == ("ok", 1)
    assert papers == {
        "name": "exa_publication_search",
        "outcome": "error",
        "topic_id": "scout",
        "wave": None,
        "query": _ACADEMIC,
        "url": None,
        "hit_count": None,
        "sources": [],
        "error": "papers down",
    }


def _trace_run(tmp_path, llm: FakeLLM, exa: FakeExa | None = None) -> list[dict]:
    path = tmp_path / "run.jsonl"
    main(
        ["What is X?", "--skip-clarify", "--trace", "--trace-path", str(path)],
        runtime=runtime(llm=llm, exa=exa, exact_model="anthropic:m"),
        checkpointer=InMemorySaver(),
    )
    return read_trace(path)


def _research_crumb_ids(lines: list[dict], run_id: str) -> set[str]:
    return {
        c["id"]
        for line in lines
        if line["kind"] == "tool"
        and line["run_id"] == run_id
        and line["data"]["topic_id"] != "scout"
        for c in line["data"]["sources"]
    }


def _data(lines: list[dict], kind: str) -> list[dict]:
    return [line["data"] for line in lines if line["kind"] == kind]


def _two_topic_llm(**kwargs) -> FakeLLM:
    return FakeLLM(
        plan=PlanDecision(topics=["alpha", "beta"], reason="two"),
        echo_topic=True,
        **kwargs,
    )


def test_each_finding_source_id_resolves_to_a_research_crumb_of_its_run(tmp_path):
    lines = _trace_run(tmp_path, _two_topic_llm())
    crumbs = _research_crumb_ids(lines, lines[0]["run_id"])
    ids = [i for finding in _data(lines, "finding") for i in finding["source_ids"]]
    assert ids
    assert set(ids) <= crumbs


def test_each_resolved_cited_id_resolves_to_a_research_crumb_of_its_run(tmp_path):
    llm = FakeLLM(report="A [src_t0_1_1]. B [src_t0_1_2].")
    exa = FakeExa(hits=[source(title="A"), source(title="B")])
    lines = _trace_run(tmp_path, llm, exa)
    (refs,) = _data(lines, "report_refs")
    resolved = set(refs["cited"]) - set(refs["dangling"])
    assert resolved == {"src_t0_1_1", "src_t0_1_2"}
    assert resolved <= _research_crumb_ids(lines, lines[0]["run_id"])


def test_no_dangling_id_resolves_to_a_research_crumb_of_its_run(tmp_path):
    lines = _trace_run(tmp_path, FakeLLM(report="A [src_scout_1]. B [src_t9_9_9]."))
    (refs,) = _data(lines, "report_refs")
    assert refs["dangling"] == ["src_scout_1", "src_t9_9_9"]
    assert not set(refs["dangling"]) & _research_crumb_ids(lines, lines[0]["run_id"])


def test_one_trace_file_answers_both_eval_questions(tmp_path):
    exa = FakeExa(failing={"beta": RuntimeError("vendor down")})
    lines = _trace_run(tmp_path, _two_topic_llm(), exa)
    assert not list(tmp_path.glob("*.sqlite"))

    # Which topic in which wave produced no usable source, and which tool
    # attempt failed first for that topic?
    empty = [
        (f["topic_id"], f["wave"])
        for f in _data(lines, "finding")
        if not f["source_ids"]
    ]
    assert empty == [("t0_2", 0)]
    failed = [
        line
        for line in lines
        if line["kind"] == "tool"
        and line["data"]["topic_id"] == "t0_2"
        and line["data"]["outcome"] == "error"
    ]
    first = min(failed, key=lambda line: line["seq"])["data"]
    assert (first["name"], first["query"], first["error"]) == (
        "exa_search",
        "beta",
        "vendor down",
    )

    # Did a settings change move the claim count or the source count?
    (start,) = _data(lines, "run_start")
    assert start["settings"]["models"]["research"] == "anthropic:m"
    assert start["settings"]["thinking_budget"] == 0
    assert sum(f["claims"] for f in _data(lines, "finding")) == 1
    assert _research_crumb_ids(lines, lines[0]["run_id"]) == {"src_t0_1_1"}


# ─── User preferences ───────────────────────────────────────────────────


def _asking_llm() -> FakeLLM:
    return FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )


def test_prefs_clarify_mode_skip_makes_no_router_call():
    llm = _asking_llm()
    app = build_graph(runtime(llm=llm))
    config = _config("t-prefs-skip")
    result = app.invoke(graph_seed(prefs=seed_prefs(clarify_mode="skip")), config)
    assert app.get_state(config).next == ()
    assert result["clarify_needed"] is False
    assert llm.with_structured_output(ClarifyDecision).invocations == 0


def test_prefs_state_has_no_skip_clarify_channel():
    app = build_graph(runtime(llm=_asking_llm()))
    config = _config("t-prefs-channel")
    app.invoke(graph_seed(prefs=seed_prefs(), skip_clarify=True), config)
    snap = app.get_state(config)
    # A ``skip_clarify`` input is no channel: it neither skips nor persists.
    assert snap.next == ("ask_user",)
    assert "skip_clarify" not in snap.values


def test_prefs_every_worker_send_payload_holds_prefs():
    prefs = seed_prefs(tone="plain", exclude_domains=["a.com"])
    sends = route_research(
        {
            "topics": [
                {"id": "t0_1", "query": "a", "focus": "web"},
                {"id": "t0_2", "query": "b", "focus": "people"},
            ],
            "brief": {"question": "q"},
            "prefs": prefs,
        }
    )
    assert [send.arg["prefs"] for send in sends] == [prefs, prefs]


def test_prefs_nodes_read_state_prefs_not_settings():
    llm = _asking_llm()
    app = build_graph(runtime(llm=llm, exact_clarify_mode="skip"))
    config = _config("t-prefs-state")
    app.invoke(graph_seed(prefs=seed_prefs()), config)
    assert app.get_state(config).next == ("ask_user",)


def test_prefs_a_clarify_reply_leaves_recency_any():
    app = build_graph(runtime(llm=_asking_llm()))
    config = _config("t-prefs-reply")
    app.invoke(graph_seed(prefs=seed_prefs(), max_clarify_turns=1), config)
    result = app.invoke(Command(resume="last month"), config)
    assert result["user_clarification"]["text"] == "last month"
    assert result["prefs"]["recency"] == "any"
    assert result["prefs"]["start_published_date"] is None


def _run_scouted(exa: FakeExa, query: str = "What is X?", **prefs) -> dict:
    app = build_graph(runtime(exa=exa))
    seed = graph_seed(
        initial_query=query, prefs=seed_prefs(clarify_mode="skip", **prefs)
    )
    return app.invoke(seed, _config("t-scout-prefs"))


def test_scout_filters_reach_the_web_and_publication_legs():
    exa = FakeExa()
    _run_scouted(
        exa,
        source_mix="mixed",
        exclude_domains=["quora.com"],
        denylist="seo",
        recency="week",
    )
    assert exa.search_categories[:2] == [None, "publication"]
    for filters in exa.search_filters[:2]:
        assert filters["exclude_domains"].count("quora.com") == 1
        assert filters["start_published_date"] == "2026-09-14"
    assert exa.search_nums[:2] == [5, 5]


def test_scout_sources_web_never_runs_the_publication_leg():
    exa = FakeExa()
    _run_scouted(exa, "Clinical trials of X?", source_mix="web")
    assert "publication" not in exa.search_categories


def test_scout_sources_academic_runs_the_publication_leg_on_any_query():
    exa = FakeExa()
    _run_scouted(exa, "What is X?", source_mix="academic")
    assert exa.search_categories[:2] == [None, "publication"]


def test_scout_filtered_empty_legs_append_a_no_hits_line():
    result = _run_scouted(
        FakeExa(hits=[]), source_mix="mixed", exclude_domains=["a.com"]
    )
    assert "exa scout: no hits (filters: exclude)" in result["errors"]
    assert "exa publication scout: no hits (filters: exclude)" in result["errors"]
    assert result["final_report"]


def test_scout_unfiltered_empty_leg_appends_no_line():
    result = _run_scouted(FakeExa(hits=[]), source_mix="mixed")
    assert not [e for e in result["errors"] if "no hits" in e]


def test_scout_filtered_raising_leg_keeps_only_its_failure_line():
    exa = FakeExa(failing={None: RuntimeError("boom")})
    result = _run_scouted(exa, exclude_domains=["a.com"])
    assert "exa scout failed: boom" in result["errors"]
    assert not [e for e in result["errors"] if e.startswith("exa scout: no hits")]


def _write_prompt(**prefs) -> str:
    llm = FakeLLM()
    build_graph(runtime(llm=llm)).invoke(
        graph_seed(prefs=seed_prefs(clarify_mode="skip", **prefs)),
        _config("t-write-prefs"),
    )
    return llm.last_text_messages[0].content


@pytest.mark.parametrize(
    "name, value, expected",
    [
        ("language", "auto", 'Write in the language of the user query "What is X?"'),
        ("language", "en", "Write in English."),
        ("language", "es", "Write in Spanish."),
        ("language", "pt", "Write in Portuguese."),
        ("length", "short", "Length: 300 to 500 words."),
        ("length", "standard", "Length: 800 to 1500 words."),
        ("length", "long", "Length: 2000 to 3500 words."),
        ("structure", "report", "Structure: a cohesive report with headed sections."),
        ("structure", "memo", "Summary, Findings and Implications sections"),
        ("structure", "bullets", "bodies are bullet lists"),
        ("tone", "academic", "Tone: formal and academic."),
        ("tone", "executive", "Tone: executive. Lead with conclusions and decisions"),
        ("tone", "plain", "Tone: plain. Use short sentences and everyday words"),
    ],
)
def test_write_prefs_prompt_holds_each_output_value_string(
    name: str, value: str, expected: str
):
    prompt = _write_prompt(**{name: value})
    assert expected in prompt
    assert "Only cite source ids that exist, as [src_...]." in prompt
    assert "End with ## Open questions listing the gaps." in prompt


def test_write_prefs_neutral_tone_adds_no_tone_line():
    assert "Tone:" not in _write_prompt(tone="neutral")


def test_write_prefs_bullets_exempt_open_questions_from_citation():
    prompt = _write_prompt(structure="bullets")
    assert "The bullets under ## Open questions need no citation." in prompt
    assert "The bullets under ## Open questions need no citation." not in (
        _write_prompt(structure="memo")
    )


@pytest.mark.parametrize("language, name", [("es", "Spanish"), ("pt", "Portuguese")])
def test_write_prefs_es_and_pt_keep_open_questions_in_english(language, name):
    prompt = _write_prompt(language=language)
    assert f"Write the other headings in {name}." in prompt
    assert "Keep the heading ## Open questions in English, word for word." in prompt
