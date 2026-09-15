from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

type JsonMapping = Mapping[str, Any]


class Source(BaseModel):
    id: str
    title: str
    url: str | None = None
    doi: str | None = None
    snippet: str = ""
    provider: Literal["exa", "elicit"]
    retrieved_at: str = ""


class Finding(BaseModel):
    topic_id: str
    claims: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    covered: list[str] = Field(default_factory=list)


class ClarificationOption(BaseModel):
    id: str
    label: str
    description: str = ""


class UserClarification(BaseModel):
    kind: Literal["skip", "pick", "text"]
    option_ids: list[str] = Field(default_factory=list)
    text: str | None = None


class ResearchBrief(BaseModel):
    question: str
    audience: str = "general"
    intent: Literal["web", "academic", "mixed"] = "web"
    must_cover: list[str] = Field(default_factory=list, max_length=5)
    exclusions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    id: str
    query: str
    status: Literal["pending", "done", "failed"] = "pending"


class ClarifyDecision(BaseModel):
    needed: bool
    question: str = ""
    options: list[ClarificationOption] = Field(default_factory=list)
    rationale: str = ""


class PlanDecision(BaseModel):
    topics: list[str]
    reason: str = ""


class ReflectDecision(BaseModel):
    done: bool
    followups: list[str] = Field(default_factory=list)
    uncovered: list[str] = Field(default_factory=list)


class UsageEvent(BaseModel):
    """One LLM or vendor call. USD is computed at print time, not stored."""

    kind: Literal[
        "llm",
        "exa_search",
        "exa_people_search",
        "exa_company_search",
        "exa_highlights",
        "elicit_search",
    ]
    node: str
    role: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    calls: int = 1


class ExactState(TypedDict, total=False):
    """Checkpointed parent-graph state. Nested models are stored as dicts."""

    # Checkpointed values are serialized dicts of the Pydantic models above.
    initial_query: str
    messages: Annotated[list[AnyMessage], add_messages]
    scout_hits: list[dict]
    clarification_options: list[dict]
    user_clarification: dict | None
    clarify_question: str
    clarify_needed: bool
    clarify_turns: int
    max_clarify_turns: int
    skip_clarify: bool
    brief: dict | None
    topics: list[dict]
    sources: Annotated[list[dict], operator.add]
    findings: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    usage: Annotated[list[dict], operator.add]
    prior_titles: list[str]
    prior_queries: list[str]
    followups: list[str]
    continue_research: bool
    iteration: int
    max_iterations: int
    final_report: str
    uncovered: list[str]


class ResearchPayload(TypedDict):
    """Isolated ``research_agent`` worker input from ``Send``."""

    topic: dict
    brief: dict
    prior_titles: list[str]
