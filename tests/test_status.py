from __future__ import annotations

import pytest

from exact.graph import build_graph
from exact.status import format_effort, format_plan, format_update
from tests.fakes import graph_seed, runtime


def test_format_plan_lists_topics_before_any_research_line():
    lines = format_plan(
        [
            {"id": "t0_1", "query": "GLP-1 outcomes in HFpEF"},
            {"id": "t0_2", "query": "Safety and discontinuation"},
        ],
        wave=0,
    )
    assert lines[0] == "[plan] wave 0 — 2 topics"
    assert "  t0_1 [web]  GLP-1 outcomes in HFpEF" in lines
    assert "  t0_2 [web]  Safety and discontinuation" in lines
    assert not any(line.startswith("[research") for line in lines)


def test_format_plan_without_wave_uses_next():
    lines = format_plan([{"id": "t0_1", "query": "define X"}])
    assert lines[0] == "[plan] next — 1 topic"


def test_format_plan_singular_topic_noun():
    lines = format_plan([{"id": "t0_1", "query": "define X"}], wave=0)
    assert lines[0] == "[plan] wave 0 — 1 topic"


@pytest.mark.parametrize(
    "node, update, expected",
    [
        (
            "scout",
            {
                "scout_hits": [
                    {"provider": "exa"},
                    {"provider": "exa"},
                    {"provider": "elicit"},
                ]
            },
            ["[scout] 2 web · 1 papers"],
        ),
        ("decide_clarify", {"clarify_needed": True}, ["[clarify] asking"]),
        ("decide_clarify", {"clarify_needed": False}, ["[clarify] skip"]),
        ("ask_user", {"user_clarification": {"kind": "skip"}}, ["[clarify] skip"]),
        (
            "generate_brief",
            {
                "brief": {
                    "intent": "academic",
                    "must_cover": ["a", "b"],
                    "question": "Q?",
                }
            },
            ["[brief] intent=academic  must_cover=2", "  Q?"],
        ),
        (
            "plan_topics",
            {"topics": [{"id": "t0_1", "query": "define X"}], "iteration": 0},
            ["[plan] wave 0 — 1 topic", "  t0_1 [web]  define X"],
        ),
        (
            "research_agent",
            {
                "sources": [{"id": "src_t0_1_1"}],
                "findings": [{"topic_id": "t0_1"}],
                "usage": [
                    {"kind": "exa_search", "node": "research_agent", "calls": 2},
                    {"kind": "exa_highlights", "node": "research_agent", "calls": 1},
                ],
            },
            ["[research t0_1] 1 source  · 2 exa_search · 1 exa_highlights"],
        ),
        (
            "research_agent",
            {
                "sources": [{"id": "src_t0_1_1"}],
                "findings": [{"topic_id": "t0_1"}],
                "usage": [
                    {"kind": "exa_people_search", "node": "research_agent", "calls": 1},
                    {
                        "kind": "exa_company_search",
                        "node": "research_agent",
                        "calls": 2,
                    },
                ],
            },
            ["[research t0_1] 1 source  · 1 exa_people_search · 2 exa_company_search"],
        ),
        (
            "research_agent",
            {"sources": [{"id": "src_t0_1_1"}], "findings": [{"topic_id": "t0_1"}]},
            ["[research t0_1] 1 source"],
        ),
        (
            "research_agent",
            {
                "sources": [],
                "findings": [{"topic_id": "t0_1"}],
                "errors": ["exa_search: down"],
            },
            ["[research t0_1] 0 sources  (1 error)"],
        ),
        ("reflect", {"continue_research": False}, ["[reflect] write"]),
        (
            "reflect",
            {
                "continue_research": True,
                "iteration": 1,
                "followups": ["missing safety data"],
            },
            [
                "[reflect] continue",
                "  missing safety data",
            ],
        ),
        ("write_report", {}, ["[write]"]),
        ("audit_citations", {"uncovered": []}, ["[audit] ok"]),
        (
            "audit_citations",
            {"uncovered": ["dangling:src_x"]},
            ["[audit] 1 unresolved citation"],
        ),
        ("__interrupt__", {"value": "pause"}, []),
        ("unknown_node", {}, ["[unknown_node]"]),
    ],
)
def test_format_update_for_each_graph_node(
    node: str, update: dict, expected: list[str]
):
    assert format_update(node, update) == expected


def test_stream_emits_plan_before_research_agent():
    app = build_graph(runtime())
    config = {"configurable": {"thread_id": "t-status"}}
    nodes: list[str] = []
    lines: list[str] = []
    for chunk in app.stream(graph_seed(), config, stream_mode="updates"):
        for node, update in chunk.items():
            nodes.append(node)
            lines.extend(format_update(node, update))
    plan_at = next(i for i, line in enumerate(lines) if line.startswith("[plan]"))
    research_at = next(
        i for i, line in enumerate(lines) if line.startswith("[research")
    )
    assert nodes.index("plan_topics") < nodes.index("research_agent")
    assert plan_at < research_at
    assert any(line.strip().startswith("t0_") for line in lines)


def test_scout_counts_papers_by_focus():
    hits = [{"provider": "exa", "focus": "web"} for _ in range(5)]
    hits += [{"provider": "exa", "focus": "publication"} for _ in range(5)]
    assert format_update("scout", {"scout_hits": hits}) == ["[scout] 5 web · 5 papers"]


def test_scout_counts_a_legacy_elicit_hit_as_a_paper():
    hits = [{"provider": "exa"}, {"provider": "elicit"}]
    assert format_update("scout", {"scout_hits": hits}) == ["[scout] 1 web · 1 papers"]


def test_research_counts_repeated_errors_once():
    data = {"errors": ["exa scout failed: boom", "exa scout failed: boom"]}
    assert "(1 error)" in format_update("research_agent", data)[0]


def test_plan_lines_show_focus():
    topics = [
        {"id": "t0_1", "query": "trials of X", "focus": "publication"},
        {"id": "t0_2", "query": "define X", "focus": "web"},
    ]
    lines = format_plan(topics, wave=0)
    assert lines[1] == "  t0_1 [publication]  trials of X"
    assert lines[2] == "  t0_2 [web]  define X"


def test_plan_lines_tag_a_pre_focus_checkpoint_as_web():
    lines = format_plan([{"id": "t0_1", "query": "define X"}], wave=0)
    assert lines[1] == "  t0_1 [web]  define X"


def test_format_effort_renders_every_resolved_cap():
    line = format_effort(
        {
            "effort": "max",
            "max_iterations": 4,
            "max_clarify_turns": 3,
            "max_topics_first_wave": 4,
            "max_topics_followup": 3,
            "max_tool_rounds": 6,
            "max_hits": 8,
            "max_concurrency": 4,
        }
    )
    assert line == (
        "effort=max waves=4 topics=4/3 rounds=6 hits=8 clarify=3 concurrency=4"
    )


_BRIEF = {
    "brief": {"intent": "web", "must_cover": ["define X", "cost"], "question": "Q?"}
}
_RESEARCH = {
    "findings": [{"topic_id": "t0_1", "gaps": ["no safety data"]}],
    "sources": [{"id": "src_t0_1_1"}],
    "errors": ["exa_search: down", "exa_search: down", "prune: bad"],
    "usage": [],
}
_REFLECT = {"continue_research": False, "uncovered": ["dose", "cost"]}
_AUDIT = {"uncovered": ["dose", "dangling:src_x", "dangling:src_y"]}


@pytest.mark.parametrize(
    "node, update, expected",
    [
        (
            "generate_brief",
            _BRIEF,
            [
                "[brief] intent=web  must_cover=2",
                "  Q?",
                "  - define X",
                "  - cost",
            ],
        ),
        (
            "research_agent",
            _RESEARCH,
            [
                "[research t0_1] 1 source  (2 errors)",
                "  gap: no safety data",
                "  error: exa_search: down",
                "  error: prune: bad",
            ],
        ),
        (
            "reflect",
            _REFLECT,
            ["[reflect] write", "  uncovered: dose", "  uncovered: cost"],
        ),
        (
            "audit_citations",
            _AUDIT,
            [
                "[audit] 2 unresolved citations",
                "  dangling: src_x",
                "  dangling: src_y",
            ],
        ),
    ],
)
def test_verbose_adds_detail_lines_under_the_default_lines(
    node: str, update: dict, expected: list[str]
):
    assert format_update(node, update, verbose=True) == expected


@pytest.mark.parametrize(
    "node, update",
    [
        ("generate_brief", _BRIEF),
        ("research_agent", _RESEARCH),
        ("reflect", _REFLECT),
        ("audit_citations", _AUDIT),
    ],
)
def test_the_default_lines_stay_byte_identical_under_verbose(node: str, update: dict):
    default = format_update(node, update)
    verbose = format_update(node, update, verbose=True)
    assert verbose[: len(default)] == default
    assert all(line.startswith("  ") for line in verbose[len(default) :])


@pytest.mark.parametrize(
    "node, update",
    [
        ("scout", {"scout_hits": [{"provider": "exa", "focus": "web"}]}),
        ("decide_clarify", {"clarify_needed": True}),
        ("ask_user", {"user_clarification": {"kind": "skip"}}),
        ("plan_topics", {"topics": [{"id": "t0_1", "query": "q"}], "iteration": 0}),
        ("write_report", {"final_report": "X [src_t0_1_1]."}),
    ],
)
def test_scout_clarify_plan_and_write_print_the_same_lines_under_verbose(
    node: str, update: dict
):
    assert format_update(node, update, verbose=True) == format_update(node, update)


@pytest.mark.parametrize(
    "node, update",
    [
        ("generate_brief", {"brief": {"intent": "web", "must_cover": []}}),
        ("research_agent", {"findings": [{"topic_id": "t0_1", "gaps": []}]}),
        ("reflect", {"continue_research": False, "uncovered": []}),
        ("audit_citations", {"uncovered": ["dose"]}),
    ],
)
def test_an_empty_list_adds_no_detail_line(node: str, update: dict):
    assert format_update(node, update, verbose=True) == format_update(node, update)


def test_a_repeated_error_appears_once_under_verbose():
    lines = format_update(
        "research_agent",
        {"findings": [{"topic_id": "t0_1"}], "errors": ["boom", "boom"]},
        verbose=True,
    )
    assert lines.count("  error: boom") == 1
