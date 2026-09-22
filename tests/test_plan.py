from __future__ import annotations

import pytest

from exact.graph import build_graph
from exact.models import PlanDecision, ReflectDecision
from exact.nodes.plan import plan_topics, route_research
from exact.nodes.reflect import reflect
from tests.fakes import FakeExa, FakeLLM, graph_seed, runtime, seed_prefs


def _state(**overrides) -> dict:
    state = {
        "initial_query": "What is X?",
        "brief": {"question": "What is X?", "intent": "web"},
        "iteration": 0,
        "topics": [],
    }
    state.update(overrides)
    return state


def test_plan_decision_validator_coerces_a_bare_string():
    decision = PlanDecision(topics=["q"])
    assert decision.topics[0].query == "q"
    assert decision.topics[0].focus == "web"
    assert decision.topics[0].raw_focus is None


def test_plan_decision_validator_keeps_a_capitalized_lane():
    assert (
        PlanDecision(topics=[{"query": "q", "focus": " Publication "}]).topics[0].focus
        == "publication"
    )


def test_plan_decision_validator_degrades_one_unknown_lane_only():
    decision = PlanDecision(
        topics=[
            {"query": "a", "focus": "news"},
            {"query": "b", "focus": "people"},
        ]
    )
    assert [t.focus for t in decision.topics] == ["web", "people"]
    assert decision.topics[0].raw_focus == "news"
    assert decision.topics[1].raw_focus is None


def test_plan_decision_validator_strips_the_query():
    decision = PlanDecision(topics=["  q  ", {"query": " q ", "focus": "people"}])
    assert [t.query for t in decision.topics] == ["q", "q"]


def test_plan_decision_validator_never_keeps_a_planner_supplied_raw_focus():
    decision = PlanDecision(
        topics=[{"query": "a", "focus": "people", "raw_focus": "people"}]
    )
    assert decision.topics[0].raw_focus is None


def test_a_padded_repeat_of_a_prior_query_is_not_planned_again():
    out = plan_topics(
        _state(
            iteration=1,
            prior_queries=[{"query": "a", "focus": "web"}],
        ),
        runtime(
            llm=FakeLLM(plan=PlanDecision(topics=[{"query": " a ", "focus": "web"}]))
        ),
    )
    assert out["topics"] == []


def test_unknown_lane_produces_one_error_line():
    out = plan_topics(
        _state(),
        runtime(
            llm=FakeLLM(plan=PlanDecision(topics=[{"query": "a", "focus": "news"}]))
        ),
    )
    assert len(out["errors"]) == 1
    assert "news" in out["errors"][0]
    assert [t["query"] for t in out["topics"]] == ["a"]


def test_planner_focus_reaches_the_send_payload():
    out = plan_topics(
        _state(),
        runtime(
            llm=FakeLLM(
                plan=PlanDecision(
                    topics=[{"query": "trials of X", "focus": "publication"}]
                )
            )
        ),
    )
    assert out["topics"][0]["focus"] == "publication"
    sends = route_research({"topics": out["topics"], "brief": {}, "prior_titles": []})
    assert sends[0].arg["topic"]["focus"] == "publication"


def test_planner_preserves_focus_and_followups():
    out = plan_topics(
        _state(),
        runtime(
            llm=FakeLLM(
                plan=PlanDecision(
                    topics=[
                        {"query": "who leads X", "focus": "people"},
                        {"query": "trials of X", "focus": "publication"},
                    ]
                )
            )
        ),
    )
    assert [t["focus"] for t in out["topics"]] == ["people", "publication"]


def test_an_unused_followup_reaches_the_planner_prompt():
    """Follow-ups are no longer topics themselves; the planner turns them into topics."""
    llm = FakeLLM(plan=PlanDecision(topics=["new gap"]))
    out = plan_topics(
        _state(followups=["missing safety"]),
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(PlanDecision).last_messages[0].content
    assert "missing safety" in prompt
    assert [t["query"] for t in out["topics"]] == ["new gap"]


@pytest.mark.parametrize("intent", ["academic", "mixed"])
def test_fallback_plan_keeps_the_publication_lane(intent: str):
    out = plan_topics(
        _state(brief={"question": "What is X?", "intent": intent}),
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert [t["focus"] for t in out["topics"]] == ["publication"]
    assert out["errors"]


def test_fallback_plan_keeps_the_web_lane_for_a_web_brief():
    out = plan_topics(_state(), runtime(llm=FakeLLM(fail_structured=True)))
    assert [t["focus"] for t in out["topics"]] == ["web"]


def test_fallback_plan_researches_unused_followups():
    """A parse failure must not drop the follow-ups the wave exists for."""
    out = plan_topics(
        _state(
            iteration=1,
            followups=["  missing safety  ", "missing cost"],
            prior_queries=[{"query": "What is X?", "focus": "web"}],
        ),
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert [t["query"] for t in out["topics"]] == ["missing safety", "missing cost"]
    assert out["errors"]


def test_fallback_retries_a_followup_an_earlier_wave_already_attempted():
    """prior_queries records attempts, not successes.

    Wave 0 attempted the lane and retrieval failed, so reflect restates it as a
    follow-up. Deduping the retry against prior would end the wave with no
    topics and route straight to the writer.
    """
    out = plan_topics(
        _state(
            iteration=1,
            followups=["effects of X"],
            prior_queries=[{"query": "effects of X", "focus": "web"}],
        ),
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert [t["query"] for t in out["topics"]] == ["effects of X"]
    assert route_research(out) != "write_report"


def test_a_planner_wave_still_dedups_against_earlier_waves():
    """The fallback exemption must not leak into the planner path."""
    out = plan_topics(
        _state(
            iteration=1,
            prior_queries=[{"query": "effects of X", "focus": "web"}],
        ),
        runtime(llm=FakeLLM(plan=PlanDecision(topics=["effects of X"]))),
    )
    assert out["topics"] == []


def test_one_wave_plans_a_repeated_lane_once():
    out = plan_topics(
        _state(),
        runtime(
            llm=FakeLLM(
                plan=PlanDecision(
                    topics=[
                        {"query": "effects of X", "focus": "web"},
                        {"query": "Effects of X", "focus": "web"},
                    ]
                )
            )
        ),
    )
    assert [t["query"] for t in out["topics"]] == ["effects of X"]


def test_a_malformed_topic_entry_does_not_cost_the_plan():
    decision = PlanDecision(topics=[123, {"query": "a", "focus": "people"}])
    assert [t.query for t in decision.topics] == ["", "a"]


@pytest.mark.parametrize("wave", [1, 2])
def test_prior_queries_carry_focus(wave: int):
    """The same query in a new lane is a new topic, not a repeat."""
    out = plan_topics(
        _state(
            iteration=wave,
            topics=[],
            prior_queries=[{"query": "effects of X", "focus": "web"}],
        ),
        runtime(
            llm=FakeLLM(
                plan=PlanDecision(
                    topics=[{"query": "effects of X", "focus": "publication"}]
                )
            )
        ),
    )
    assert [t["focus"] for t in out["topics"]] == ["publication"]


def test_a_bare_string_prior_query_still_loads():
    out = plan_topics(
        _state(iteration=1, prior_queries=["effects of X"]),
        runtime(llm=FakeLLM(plan=PlanDecision(topics=["effects of X"]))),
    )
    assert out["topics"] == []
    assert out["prior_queries"] == [{"query": "effects of X", "focus": "web"}]


def test_reflect_prompt_renders_prior_topics_as_lines_not_dicts():
    """prior_queries is a list of dicts; a prompt must never show the raw shape."""
    llm = FakeLLM()
    reflect(
        {
            "brief": {"question": "What is X?"},
            "findings": [],
            "iteration": 1,
            "max_iterations": 3,
            "prior_queries": [{"query": "define X", "focus": "publication"}],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ReflectDecision).last_messages[0].content
    assert "define X [publication]" in prompt
    assert "'query'" not in prompt


def test_reflect_prompt_renders_a_pre_lane_checkpoint():
    llm = FakeLLM()
    reflect(
        {
            "brief": {"question": "What is X?"},
            "findings": [],
            "iteration": 1,
            "max_iterations": 3,
            "prior_queries": ["define X"],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ReflectDecision).last_messages[0].content
    assert "define X [web]" in prompt


def _four_topics() -> PlanDecision:
    return PlanDecision(topics=["a", "b", "c", "d"], reason="broad")


def _three_topics() -> PlanDecision:
    return PlanDecision(topics=["a", "b", "c"], reason="broad")


@pytest.mark.parametrize("effort, expected", [("max", 4), ("normal", 3)])
def test_the_first_wave_keeps_the_profiles_topic_cap(effort: str, expected: int):
    out = plan_topics(
        _state(),
        runtime(llm=FakeLLM(plan=_four_topics()), exact_effort=effort),
    )
    assert len(out["topics"]) == expected


@pytest.mark.parametrize("effort, expected", [("max", 3), ("normal", 2)])
def test_a_follow_up_wave_keeps_the_profiles_follow_up_cap(effort: str, expected: int):
    out = plan_topics(
        _state(iteration=1),
        runtime(llm=FakeLLM(plan=_three_topics()), exact_effort=effort),
    )
    assert len(out["topics"]) == expected


@pytest.mark.parametrize("effort, expected", [("max", 3), ("normal", 2)])
def test_the_fallback_wave_keeps_the_profiles_follow_up_cap(effort: str, expected: int):
    out = plan_topics(
        _state(iteration=1, followups=["one", "two", "three"]),
        runtime(llm=FakeLLM(fail_structured=True), exact_effort=effort),
    )
    assert [t["query"] for t in out["topics"]] == ["one", "two", "three"][:expected]


@pytest.mark.parametrize("effort, expected", [("max", 3), ("normal", 2)])
def test_reflect_keeps_the_profiles_follow_up_cap(effort: str, expected: int):
    out = reflect(
        {
            "brief": {},
            "findings": [],
            "sources": [],
            "topics": [],
            "iteration": 0,
            "max_iterations": 3,
        },
        runtime(
            llm=FakeLLM(
                reflect=ReflectDecision(
                    done=False, followups=["one", "two", "three"], uncovered=[]
                )
            ),
            exact_effort=effort,
        ),
    )
    assert out["followups"] == ["one", "two", "three"][:expected]


@pytest.mark.parametrize(
    "effort, first, followup",
    [
        ("max", "Use 2-4 topics", "keep the first 3 only"),
        ("normal", "Use 2-3 topics", "keep the first 2 only"),
    ],
)
def test_the_plan_prompt_names_both_caps_of_the_profile(
    effort: str, first: str, followup: str
):
    llm = FakeLLM()
    plan_topics(_state(), runtime(llm=llm, exact_effort=effort))
    prompt = llm.with_structured_output(PlanDecision).last_messages[0].content
    assert first in prompt
    assert followup in prompt


@pytest.mark.parametrize("effort, expected", [("max", 3), ("normal", 2)])
def test_the_reflect_prompt_names_the_follow_up_cap(effort: str, expected: int):
    llm = FakeLLM()
    reflect(
        {"brief": {}, "findings": [], "iteration": 0, "max_iterations": 3},
        runtime(llm=llm, exact_effort=effort),
    )
    prompt = llm.with_structured_output(ReflectDecision).last_messages[0].content
    assert f"give 1-{expected} follow-up" in prompt


# ─── Lanes by source mix ────────────────────────────────────────────────


def _plan_under(source_mix: str, *topics, **state) -> dict:
    llm = FakeLLM(plan=PlanDecision(topics=list(topics)))
    return plan_topics(
        _state(prefs=seed_prefs(source_mix=source_mix), **state), runtime(llm=llm)
    )


def _lanes(out: dict) -> list[tuple[str, str]]:
    return [(t["query"], t["focus"]) for t in out["topics"]]


def test_lanes_sources_web_changes_a_publication_topic_to_web():
    out = _plan_under("web", {"query": "trials of X", "focus": "publication"})
    assert _lanes(out) == [("trials of X", "web")]


def test_lanes_sources_academic_changes_a_web_topic_to_publication():
    out = _plan_under("academic", {"query": "news on X", "focus": "web"})
    assert _lanes(out) == [("news on X", "publication")]


def test_lanes_collision_keeps_the_first_topic_with_no_error_line():
    out = _plan_under(
        "web",
        {"query": "q", "focus": "publication"},
        {"query": "q", "focus": "web"},
    )
    assert [(t["id"], t["query"], t["focus"]) for t in out["topics"]] == [
        ("t0_1", "q", "web")
    ]
    assert "errors" not in out


def test_lanes_unknown_focus_line_names_the_final_lane():
    out = _plan_under("academic", {"query": "q", "focus": "news"})
    assert out["errors"] == [
        "plan: dropped unknown topic focus 'news'; used publication"
    ]
    assert _lanes(out) == [("q", "publication")]


@pytest.mark.parametrize(
    "source_mix, intent, expected",
    [("web", "academic", "web"), ("academic", "web", "publication")],
)
def test_lanes_fallback_topic_follows_the_change(
    source_mix: str, intent: str, expected: str
):
    out = plan_topics(
        _state(
            brief={"question": "What is X?", "intent": intent},
            prefs=seed_prefs(source_mix=source_mix),
        ),
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert _lanes(out) == [("What is X?", expected)]


@pytest.mark.parametrize("source_mix", ["web", "academic", "mixed", "auto"])
def test_lanes_people_and_company_topics_keep_their_lane(source_mix: str):
    out = _plan_under(
        source_mix,
        {"query": "who", "focus": "people"},
        {"query": "firm", "focus": "company"},
    )
    assert _lanes(out) == [("who", "people"), ("firm", "company")]


def _plan_prompt(prefs: dict) -> str:
    llm = FakeLLM()
    plan_topics(_state(prefs=prefs), runtime(llm=llm))
    return llm.with_structured_output(PlanDecision).last_messages[0].content


def test_lanes_plan_prompt_does_not_change_for_source_mix():
    assert _plan_prompt(seed_prefs(source_mix="academic")) == _plan_prompt(
        seed_prefs(source_mix="auto")
    )


# ─── Search bias ────────────────────────────────────────────────────────

_PRIMARY = "Prefer official and primary sources"
_NEWS = "Shape web-lane queries as news queries"


def test_bias_plan_prompt_holds_the_primary_line_only_with_prefer_primary():
    assert _PRIMARY in _plan_prompt(seed_prefs(prefer_primary=True))
    assert _PRIMARY not in _plan_prompt(seed_prefs())


def test_bias_plan_prompt_holds_the_news_line_only_with_news_bias():
    assert _NEWS in _plan_prompt(seed_prefs(news_bias=True))
    assert _NEWS not in _plan_prompt(seed_prefs())


def _news_line(prompt: str) -> str:
    (line,) = [line for line in prompt.splitlines() if line.startswith(_NEWS)]
    return line


def test_bias_news_line_is_the_same_with_and_without_recency():
    assert _news_line(_plan_prompt(seed_prefs(news_bias=True))) == _news_line(
        _plan_prompt(seed_prefs(news_bias=True, recency="week"))
    )


def _graph_filters(**prefs) -> list[dict]:
    exa = FakeExa()
    build_graph(runtime(exa=exa)).invoke(
        graph_seed(prefs=seed_prefs(clarify_mode="skip", **prefs)),
        {"configurable": {"thread_id": "t-bias"}},
    )
    return exa.search_filters


def test_bias_leaves_the_exa_filter_arguments_unchanged():
    base = {"exclude_domains": ["a.com"], "recency": "week"}
    assert _graph_filters(**base, prefer_primary=True, news_bias=True) == (
        _graph_filters(**base)
    )
