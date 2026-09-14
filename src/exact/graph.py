from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from exact.config import Runtime
from exact.models import ExactState
from exact.nodes.audit_node import audit_citations
from exact.nodes.brief import generate_brief
from exact.nodes.clarify import (
    ask_user,
    decide_clarify,
    route_after_ask,
    route_after_decide,
)
from exact.nodes.plan import plan_topics, route_research
from exact.nodes.reflect import reflect, route_after_reflect
from exact.nodes.research import research_agent
from exact.nodes.scout import scout
from exact.nodes.write import write_report


def _bind(fn, runtime: Runtime):
    def node(state):
        return fn(state, runtime)

    node.__name__ = fn.__name__
    return node


def build_graph(runtime: Runtime, checkpointer: Any | None = None):
    g = StateGraph(ExactState)
    g.add_node("scout", _bind(scout, runtime))
    g.add_node("decide_clarify", _bind(decide_clarify, runtime))
    g.add_node("ask_user", ask_user)
    g.add_node("generate_brief", _bind(generate_brief, runtime))
    g.add_node("plan_topics", _bind(plan_topics, runtime))
    g.add_node("research_agent", _bind(research_agent, runtime))
    g.add_node("reflect", _bind(reflect, runtime))
    g.add_node("write_report", _bind(write_report, runtime))
    g.add_node("audit_citations", audit_citations)

    g.add_edge(START, "scout")
    g.add_edge("scout", "decide_clarify")
    g.add_conditional_edges(
        "decide_clarify",
        route_after_decide,
        {"ask_user": "ask_user", "generate_brief": "generate_brief"},
    )
    g.add_conditional_edges(
        "ask_user",
        route_after_ask,
        {"decide_clarify": "decide_clarify", "generate_brief": "generate_brief"},
    )
    g.add_edge("generate_brief", "plan_topics")
    g.add_conditional_edges(
        "plan_topics", route_research, ["research_agent", "write_report"]
    )
    g.add_edge("research_agent", "reflect")
    g.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {"plan_topics": "plan_topics", "write_report": "write_report"},
    )
    g.add_edge("write_report", "audit_citations")
    g.add_edge("audit_citations", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())
