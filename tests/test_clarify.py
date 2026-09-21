from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from exact.config import Settings
from exact.intent import academic_signal
from exact.models import ClarificationOption, ClarifyDecision, ResearchBrief
from exact.nodes.brief import generate_brief
from exact.nodes.clarify import decide_clarify, parse_resume
from exact.nodes.write import format_references
from tests.fakes import FakeLLM, runtime


@pytest.mark.parametrize(
    "query",
    [
        "What do the studies show?",
        "What do trials of GLP-1 show?",
        "Find the paper on X",
        "A meta-analysis of Y",
        "What is the doi for this?",
        "what does the literature say about GLP-1",
        "What is the evidence for X?",
        "Which journal published it?",
        "Find the arxiv preprint",
    ],
)
def test_academic_signal_is_true_for_spec_heuristics(query: str):
    assert academic_signal(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "Best laptop for travel",
        "What is X?",
        "case study of Tesla marketing",
        "",
        None,
    ],
)
def test_academic_signal_is_false_without_heuristic(query: str | None):
    assert academic_signal(query) is False


@pytest.mark.parametrize("raw", ["skip", "s", "n", "no", "SKIP"])
def test_resume_skip_tokens_are_skip(raw):
    assert parse_resume(raw, []).kind == "skip"


@pytest.mark.parametrize("raw", ["", None, "  "])
def test_empty_resume_is_skip(raw):
    assert parse_resume(raw, []).kind == "skip"


def test_resume_digit_picks_the_matching_option():
    opts = [{"id": "opt_1", "label": "A"}, {"id": "opt_2", "label": "B"}]
    got = parse_resume("2", opts)
    assert got.kind == "pick"
    assert got.option_ids == ["opt_2"]


@pytest.mark.parametrize("raw", ["0", "3", "9"])
def test_resume_out_of_range_digit_is_invalid_and_skips(raw: str):
    opts = [{"id": "opt_1", "label": "A"}, {"id": "opt_2", "label": "B"}]
    assert parse_resume(raw, opts).kind == "skip"


def test_resume_text_is_recorded():
    got = parse_resume("focus on safety", [])
    assert got.kind == "text"
    assert got.text == "focus on safety"


def test_resume_unknown_dict_kind_is_skip():
    got = parse_resume({"kind": "bogus"}, [])
    assert got.kind == "skip"


def test_resume_dict_without_kind_is_skip():
    assert parse_resume({}, []).kind == "skip"


def test_resume_pick_dict_keeps_option_ids():
    got = parse_resume({"kind": "pick", "option_ids": ["opt_1"]}, [])
    assert got.kind == "pick"
    assert got.option_ids == ["opt_1"]


def test_skip_clarify_forces_needed_false():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": True,
            "clarify_turns": 0,
            "scout_hits": [],
        },
        runtime(llm=llm),
    )
    assert out == {"clarify_needed": False}


def test_needed_false_skips_clarify():
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(),
    )
    assert out["clarify_needed"] is False
    assert out["clarification_options"] == []
    assert out["usage"]
    assert out["usage"][0]["kind"] == "llm"
    assert out["usage"][0]["node"] == "decide_clarify"


@pytest.mark.parametrize("turns, cap", [(2, 2), (3, 3), (4, 3)])
def test_decide_clarify_stops_at_three_turns(turns: int, cap: int):
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": turns,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm, max_clarify_turns=cap),
    )
    assert out == {"clarify_needed": False}


def test_decide_clarify_still_asks_after_two_turns():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 2,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    assert out["clarify_needed"] is True
    assert out["clarify_question"] == "Scout found Source A. Focus on mechanisms?"
    prompt = llm.with_structured_output(ClarifyDecision).last_messages[0].content
    assert "Source A" in prompt


def test_decide_clarify_prompt_carries_the_user_answer():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 1,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
            "messages": [
                HumanMessage(content="User clarification (text): only 2026 trials")
            ],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ClarifyDecision).last_messages[0].content
    assert "only 2026 trials" in prompt


def test_decide_clarify_prompt_marks_an_empty_clarify_thread():
    llm = FakeLLM()
    decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ClarifyDecision).last_messages[0].content
    assert "Clarification so far:\n(none)" in prompt


def test_needed_true_question_without_scout_title_does_not_interrupt():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Narrow or broaden?",
            options=[ClarificationOption(id="opt_1", label="Narrow")],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    assert out["clarify_needed"] is False


def test_needed_true_question_that_cites_a_scout_title_interrupts():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    assert out["clarify_needed"] is True
    assert out["clarify_question"] == "Scout found Source A. Focus on mechanisms?"


def test_empty_scout_allows_a_generic_question():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Narrow or broaden?",
            options=[ClarificationOption(id="opt_1", label="Narrow")],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [],
        },
        runtime(llm=llm),
    )
    assert out["clarify_needed"] is True
    assert out["clarify_question"] == "Narrow or broaden?"


def test_empty_scout_is_shown_to_decide_clarify():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Narrow or broaden the question?",
            options=[ClarificationOption(id="opt_1", label="Narrow")],
        )
    )
    decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ClarifyDecision).last_messages[0].content
    assert "(no scout hits)" in prompt


def test_decide_clarify_includes_a_user_message():
    llm = FakeLLM()
    decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    messages = llm.with_structured_output(ClarifyDecision).last_messages
    assert any(isinstance(m, HumanMessage) for m in messages)


def test_needed_clarify_without_options_gets_a_default():
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Narrow the angle?",
            options=[],
        )
    )
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [{"title": "Source A", "provider": "exa", "snippet": "X"}],
        },
        runtime(llm=llm),
    )
    assert out["clarification_options"] == [
        {"id": "opt_1", "label": "Proceed as stated", "description": ""}
    ]


@pytest.mark.parametrize("n", [4, 5])
def test_must_cover_accepts_up_to_five_items(n: int):
    brief = ResearchBrief(question="q", intent="web", must_cover=["a"] * n)
    assert len(brief.must_cover) == n


def test_must_cover_rejects_more_than_five_items():
    with pytest.raises(ValidationError):
        ResearchBrief(question="q", intent="web", must_cover=["a"] * 6)


def test_academic_query_promotes_web_brief_to_academic():
    llm = FakeLLM(
        brief=ResearchBrief(
            question="What do trials show?", intent="web", must_cover=["outcomes"]
        )
    )
    out = generate_brief(
        {
            "initial_query": "What do trials of GLP-1 show?",
            "scout_hits": [],
            "messages": [],
        },
        runtime(llm=llm),
    )
    assert out["brief"]["intent"] == "academic"


def test_academic_clarification_text_promotes_web_brief_to_academic():
    llm = FakeLLM(
        brief=ResearchBrief(question="What is X?", intent="web", must_cover=["x"])
    )
    out = generate_brief(
        {
            "initial_query": "What is X?",
            "scout_hits": [],
            "messages": [],
            "user_clarification": {
                "kind": "text",
                "option_ids": [],
                "text": "Prefer peer-reviewed clinical trials",
            },
        },
        runtime(llm=llm),
    )
    assert out["brief"]["intent"] == "academic"


def test_academic_clarification_pick_promotes_web_brief_to_academic():
    llm = FakeLLM(
        brief=ResearchBrief(question="What is X?", intent="web", must_cover=["x"])
    )
    out = generate_brief(
        {
            "initial_query": "What is X?",
            "scout_hits": [],
            "messages": [],
            "user_clarification": {
                "kind": "pick",
                "option_ids": ["opt_1"],
                "text": None,
            },
            "clarification_options": [
                {
                    "id": "opt_1",
                    "label": "Focus on a systematic review",
                    "description": "",
                }
            ],
        },
        runtime(llm=llm),
    )
    assert out["brief"]["intent"] == "academic"


def test_structured_output_failure_skips_clarify():
    out = decide_clarify(
        {
            "initial_query": "What is X?",
            "scout_hits": [{"title": "Source A", "snippet": "x", "provider": "exa"}],
            "clarify_turns": 0,
            "max_clarify_turns": 3,
        },
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert out["clarify_needed"] is False
    assert out["errors"]
    assert "structured output missing" in out["errors"][0]


def test_structured_output_failure_still_produces_a_brief():
    out = generate_brief(
        {"initial_query": "What is X?", "scout_hits": [], "messages": []},
        runtime(llm=FakeLLM(fail_structured=True)),
    )
    assert out["brief"]["question"] == "What is X?"
    assert out["brief"]["must_cover"] == ["What is X?"]
    assert out["errors"]


def test_empty_must_cover_defaults_to_the_question():
    llm = FakeLLM(
        brief=ResearchBrief(question="What is X?", intent="web", must_cover=[])
    )
    out = generate_brief(
        {"initial_query": "What is X?", "scout_hits": [], "messages": []},
        runtime(llm=llm),
    )
    assert out["brief"]["must_cover"] == ["What is X?"]


def test_bounds_defaults_match_spec():
    fields = Settings.model_fields
    assert fields["exact_model"].default == "anthropic:claude-haiku-4-5"
    assert fields["exact_model_router"].default == ""
    assert fields["exact_model_research"].default == ""
    assert fields["exact_model_compress"].default == ""
    assert fields["exact_model_write"].default == ""
    assert fields["exact_temperature"].default == 0.0
    assert fields["exact_max_tokens_router"].default == 1024
    assert fields["exact_max_tokens_research"].default == 1024
    assert fields["exact_max_tokens_compress"].default == 2048
    assert fields["exact_max_tokens_write"].default == 8192
    assert fields["exact_thinking_budget"].default == 0
    assert fields["max_clarify_turns"].default == 3
    assert fields["max_iterations"].default == 3
    assert fields["max_tool_rounds"].default == 4
    assert fields["max_hits"].default == 5
    assert fields["http_timeout"].default == 20.0


def test_router_question_wording_does_not_decide_the_brief_intent():
    llm = FakeLLM(
        brief=ResearchBrief(question="What is X?", intent="web", must_cover=["X"])
    )
    out = generate_brief(
        {
            "initial_query": "What is X?",
            "scout_hits": [],
            "messages": [
                AIMessage(content="Scout found A trial of X. Which angle?"),
                HumanMessage(content="User clarification (text): the 2026 rollout"),
            ],
            "user_clarification": {"kind": "text", "text": "the 2026 rollout"},
        },
        runtime(llm=llm),
    )
    assert out["brief"]["intent"] == "web"


def test_an_earlier_clarify_turn_still_promotes_the_brief_to_academic():
    llm = FakeLLM(
        brief=ResearchBrief(question="What is X?", intent="web", must_cover=["X"])
    )
    out = generate_brief(
        {
            "initial_query": "What is X?",
            "scout_hits": [],
            "messages": [
                AIMessage(content="Which angle?"),
                HumanMessage(
                    content="User clarification (text): only peer-reviewed trials"
                ),
                AIMessage(content="Which period?"),
                HumanMessage(content="User clarification (text): the 2026 rollout"),
            ],
            "user_clarification": {"kind": "text", "text": "the 2026 rollout"},
        },
        runtime(llm=llm),
    )
    assert out["brief"]["intent"] == "academic"


def test_reference_line_renders_doi_beside_url():
    lines = format_references(
        [
            {
                "id": "src_t0_1_1",
                "title": "A trial",
                "url": "https://www.nature.com/articles/x",
                "doi": "10.1/x",
                "provider": "exa",
                "focus": "publication",
            }
        ]
    )
    assert lines[1] == (
        "[src_t0_1_1] A trial — https://www.nature.com/articles/x — doi:10.1/x"
        " (publication)"
    )


def test_reference_line_does_not_repeat_a_doi_the_url_already_spells():
    lines = format_references(
        [
            {
                "id": "src_t0_1_1",
                "title": "A trial",
                "url": "https://doi.org/10.1/x",
                "doi": "10.1/x",
                "provider": "exa",
                "focus": "publication",
            }
        ]
    )
    assert lines[1] == "[src_t0_1_1] A trial — https://doi.org/10.1/x (publication)"


_PAPER_HIT = {
    "title": "A trial",
    "provider": "exa",
    "focus": "publication",
    "snippet": "s",
}


def test_scout_text_labels_publication_hit():
    """The paper signal must reach the brief prompt, not just the scout."""
    llm = FakeLLM()
    generate_brief(
        {"initial_query": "What is X?", "scout_hits": [_PAPER_HIT]}, runtime(llm=llm)
    )
    prompt = llm.with_structured_output(ResearchBrief).last_messages[0].content
    assert "[publication]" in prompt


def test_scout_block_labels_publication_hit():
    llm = FakeLLM()
    decide_clarify(
        {
            "initial_query": "What is X?",
            "skip_clarify": False,
            "clarify_turns": 0,
            "scout_hits": [_PAPER_HIT],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ClarifyDecision).last_messages[0].content
    assert "[publication]" in prompt


def test_scout_labels_fall_back_to_web_for_a_pre_focus_checkpoint():
    llm = FakeLLM()
    generate_brief(
        {
            "initial_query": "What is X?",
            "scout_hits": [{"title": "A page", "provider": "exa", "snippet": "s"}],
        },
        runtime(llm=llm),
    )
    prompt = llm.with_structured_output(ResearchBrief).last_messages[0].content
    assert "[web]" in prompt
