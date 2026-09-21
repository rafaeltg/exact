from __future__ import annotations

import pytest

from exact.sink import emit_chunk
from tests.fakes import RecordingTracer

_CLARIFY = {"clarify_needed": True, "clarify_question": "Q?"}
_REFLECT = {
    "continue_research": True,
    "iteration": 1,
    "followups": ["dose"],
    "uncovered": ["cost"],
}
_BRIEF = {
    "brief": {"intent": "academic", "must_cover": ["define X"], "question": "Q?"},
    "iteration": 0,
}
_PLAN = {
    "topics": [{"id": "t1_1", "query": "dose", "focus": "web", "status": "pending"}],
    "iteration": 1,
}
_FINDING = {
    "findings": [
        {
            "topic_id": "t0_2",
            "claims": ["a", "b"],
            "source_ids": ["src_t0_2_1"],
            "gaps": ["g"],
            "covered": ["define X"],
        }
    ],
    "sources": [{"id": "src_t0_2_1", "snippet": "body"}],
}


def _emit(node: str, update) -> RecordingTracer:
    tracer = RecordingTracer()
    emit_chunk(tracer, node, update)
    return tracer


@pytest.mark.parametrize(
    "node, update, kind",
    [
        ("decide_clarify", _CLARIFY, "decision"),
        ("reflect", _REFLECT, "decision"),
        ("generate_brief", _BRIEF, "brief"),
        ("plan_topics", _PLAN, "plan"),
        ("research_agent", _FINDING, "finding"),
    ],
)
def test_each_mapped_node_yields_its_kind(node: str, update: dict, kind: str):
    assert _emit(node, update).kinds() == [kind]


@pytest.mark.parametrize(
    "node, update",
    [
        ("scout", {"scout_hits": [{"id": "src_scout_1"}]}),
        ("ask_user", {"clarify_needed": False}),
        ("write_report", {"final_report": "X."}),
        ("audit_citations", {"uncovered": ["dangling:src_x"]}),
    ],
)
def test_an_unmapped_node_yields_no_stage_kind(node: str, update: dict):
    assert _emit(node, update).kinds() == []


def test_a_node_whose_name_starts_with_two_underscores_yields_nothing():
    tracer = _emit("__interrupt__", ({"value": "Q?"},))
    assert tracer.events == []
    assert tracer.dropped == 0


def test_the_stage_payloads_carry_their_exact_key_sets():
    assert set(_emit("decide_clarify", _CLARIFY).payloads("decision")[0]) == {
        "stage",
        "needed",
    }
    assert set(_emit("reflect", _REFLECT).payloads("decision")[0]) == {
        "stage",
        "continue",
        "followups",
        "uncovered",
    }
    assert set(_emit("generate_brief", _BRIEF).payloads("brief")[0]) == {
        "intent",
        "must_cover",
        "question",
    }
    assert set(_emit("plan_topics", _PLAN).payloads("plan")[0]) == {"wave", "topics"}
    assert set(_emit("research_agent", _FINDING).payloads("finding")[0]) == {
        "topic_id",
        "wave",
        "claims",
        "source_ids",
        "gaps",
    }


def test_the_stage_payloads_carry_the_chunk_values():
    assert _emit("decide_clarify", _CLARIFY).payloads("decision") == [
        {"stage": "clarify", "needed": True}
    ]
    assert _emit("reflect", _REFLECT).payloads("decision") == [
        {
            "stage": "reflect",
            "continue": True,
            "followups": ["dose"],
            "uncovered": ["cost"],
        }
    ]
    assert _emit("plan_topics", _PLAN).payloads("plan") == [
        {"wave": 1, "topics": [{"id": "t1_1", "query": "dose", "focus": "web"}]}
    ]
    assert _emit("research_agent", _FINDING).payloads("finding") == [
        {
            "topic_id": "t0_2",
            "wave": 0,
            "claims": 2,
            "source_ids": ["src_t0_2_1"],
            "gaps": ["g"],
        }
    ]


def test_the_brief_line_reads_the_values_nested_under_brief():
    assert _emit("generate_brief", _BRIEF).payloads("brief") == [
        {"intent": "academic", "must_cover": ["define X"], "question": "Q?"}
    ]


def test_a_plan_without_iteration_takes_the_wave_of_its_first_topic():
    update = {"topics": [{"id": "t2_1", "query": "q", "focus": "web"}]}
    assert _emit("plan_topics", update).payloads("plan")[0]["wave"] == 2


def test_a_reflect_chunk_without_followups_writes_an_empty_list():
    update = {"continue_research": False, "uncovered": []}
    assert _emit("reflect", update).payloads("decision")[0]["followups"] == []


def test_a_chunk_whose_findings_is_empty_writes_no_line_and_one_drop():
    tracer = _emit("research_agent", {"findings": [], "usage": []})
    assert tracer.events == []
    assert tracer.dropped == 1


def test_a_chunk_that_is_not_a_mapping_raises_nothing():
    tracer = _emit("research_agent", "not a mapping")
    assert tracer.events == []
    assert tracer.dropped == 1


_LLM = {
    "kind": "llm",
    "node": "research_agent",
    "role": "research",
    "model": "m",
    "input_tokens": 10,
    "output_tokens": 2,
    "cache_read": 0,
    "cache_creation": 0,
    "calls": 1,
}
_TOOL = {"kind": "exa_search", "node": "research_agent", "calls": 1}
_PRUNE = {**_LLM, "role": "compress"}


def test_one_research_chunk_yields_one_usage_line_per_event():
    update = {**_FINDING, "usage": [_LLM, _TOOL, _PRUNE]}
    assert _emit("research_agent", update).kinds() == [
        "finding",
        "usage",
        "usage",
        "usage",
    ]


def test_a_usage_line_carries_the_exact_eleven_keys():
    update = {**_FINDING, "usage": [_LLM]}
    assert set(_emit("research_agent", update).payloads("usage")[0]) == {
        "kind",
        "node",
        "role",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read",
        "cache_creation",
        "calls",
        "topic_id",
        "wave",
    }


def test_a_research_usage_line_names_the_topic_and_its_wave():
    update = {**_FINDING, "usage": [_LLM]}
    line = _emit("research_agent", update).payloads("usage")[0]
    assert (line["topic_id"], line["wave"]) == ("t0_2", 0)


def test_a_scout_usage_line_names_the_scout_topic_and_no_wave():
    update = {"scout_hits": [], "usage": [{**_TOOL, "node": "scout"}]}
    line = _emit("scout", update).payloads("usage")[0]
    assert (line["topic_id"], line["wave"]) == ("scout", None)


def test_another_node_usage_line_names_no_topic():
    update = {**_BRIEF, "usage": [{**_LLM, "node": "generate_brief"}]}
    line = _emit("generate_brief", update).payloads("usage")[0]
    assert (line["topic_id"], line["wave"]) == (None, None)


def test_a_vendor_tool_event_writes_null_for_role_model_and_tokens():
    update = {**_FINDING, "usage": [_TOOL]}
    line = _emit("research_agent", update).payloads("usage")[0]
    for key in (
        "role",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read",
        "cache_creation",
    ):
        assert line[key] is None
    assert line["calls"] == 1
