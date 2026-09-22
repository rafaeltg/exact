from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, model_validator

type JsonMapping = Mapping[str, Any]

# Retrieval lane of a source or a topic; also the Exa search category.
type TopicFocus = Literal["web", "people", "company", "publication"]
FOCUS_VALUES: frozenset[str] = frozenset({"web", "people", "company", "publication"})


class Source(BaseModel):
    id: str
    title: str
    url: str | None = None
    doi: str | None = None
    snippet: str = ""
    provider: Literal["exa", "elicit"]
    focus: TopicFocus | None = None
    retrieved_at: str = ""


def focus_label(source: JsonMapping) -> str:
    """The retrieval lane to show for a source.

    A checkpoint written before sources carried a focus has none, so an Exa
    row reads as web and any other provider names itself.
    """
    focus = source.get("focus")
    if focus:
        return str(focus)
    provider = str(source.get("provider") or "")
    return "web" if provider == "exa" else provider


def render_prior_queries(prior: list) -> list[str]:
    """Prior topics as ``query [focus]`` lines for a prompt.

    A row is a dict once topics carry a lane, and a bare string in a
    checkpoint written before they did.
    """
    lines: list[str] = []
    for row in prior or []:
        if isinstance(row, str):
            lines.append(f"{row} [web]")
        elif isinstance(row, dict) and row.get("query"):
            lines.append(f"{row['query']} [{row.get('focus') or 'web'}]")
    return lines


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


class PlannedTopic(BaseModel):
    """One topic as the planner proposed it, before it earns an id."""

    query: str
    focus: TopicFocus = "web"
    # The token the planner asked for when it was not a lane, kept so the
    # node can report what it dropped.
    raw_focus: str | None = None


class Topic(BaseModel):
    id: str
    query: str
    focus: TopicFocus = "web"
    status: Literal["pending", "done", "failed"] = "pending"


class ClarifyDecision(BaseModel):
    needed: bool
    question: str = ""
    options: list[ClarificationOption] = Field(default_factory=list)
    rationale: str = ""


def _coerce_topic(entry: Any) -> Any:
    """Normalize one planner topic entry; never reject the whole plan.

    A planner may answer with a bare query string, or name a lane that is not
    one. Either way the topic survives, because one bad focus must not cost
    the wave every other topic.
    """
    if isinstance(entry, str):
        return {"query": entry.strip(), "focus": "web"}
    if not isinstance(entry, dict):
        # Neither shape is a topic; an empty query drops this row alone.
        return {"query": "", "focus": "web"}
    # Strip here so the dedup key and the search string agree across waves.
    query = str(entry.get("query") or "").strip()
    token = str(entry.get("focus") or "web").strip().casefold()
    if token in FOCUS_VALUES:
        # ``raw_focus`` is in the schema the planner sees; only this node sets it.
        return {**entry, "query": query, "focus": token, "raw_focus": None}
    return {
        **entry,
        "query": query,
        "focus": "web",
        "raw_focus": str(entry.get("focus")),
    }


class PlanDecision(BaseModel):
    topics: list[PlannedTopic]
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_topics(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        topics = data.get("topics")
        if not isinstance(topics, list):
            return data
        return {**data, "topics": [_coerce_topic(t) for t in topics]}


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
        "exa_publication_search",
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
    # The run's user preferences, frozen when the thread is seeded.
    prefs: dict
    brief: dict | None
    topics: list[dict]
    sources: Annotated[list[dict], operator.add]
    findings: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    usage: Annotated[list[dict], operator.add]
    prior_titles: list[str]
    prior_queries: list[dict]
    followups: list[str]
    continue_research: bool
    iteration: int
    max_iterations: int
    effort: str
    max_topics_first_wave: int
    max_topics_followup: int
    final_report: str
    uncovered: list[str]


class ResearchPayload(TypedDict):
    """Isolated ``research_agent`` worker input from ``Send``."""

    topic: dict
    brief: dict
    prior_titles: list[str]
    prefs: dict
