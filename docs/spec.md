# Exact — Open Deep Research (POC v1.5)

**Version:** 1.5.0  
**Status:** Implementable. LangGraph ODR pipeline with Exa. The Elicit client is dormant.  
**Surface:** CLI  
**Objective:** Deliver LangChain’s [Open Deep Research](https://www.langchain.com/blog/open-deep-research) architecture: Scope → Research → Write. Tools are Exa only. Clarification is grounded in an Exa scout that adds a publication lane on an academic signal. Every factual claim in the report carries a `[src_*]` id that resolves to a retrieved source. Gaps are listed, not invented.

This does **not** guarantee truth. Citations must be checkable. Spend is capped, not unbounded.

---

## 0. Relative to ODR and to v1.1

ODR steps that v1.5 implements: conditional clarification, brief as north star, supervisor 1-vs-N, isolated sub-agents, tool-calling research loop, prune before supervisor, supervisor iteration, one-shot write (no parallel section writers).

| v1.1 | v1.5 |
| :--- | :--- |
| Always 3 options, one interrupt | Scout first; clarify only if needed; up to 3 turns |
| One `retrieve()` + extract | Isolated ReAct via `create_agent` + `ModelCallLimitMiddleware`: the search tool of the topic focus, plus `exa_highlights`, then prune |
| `max_iterations=2`, code-first reflect | Reflect reasons against the brief; hard wave cap from the effort profile (3 normal, 4 max) |
| `InMemorySaver` | SQLite checkpointer (multi-turn HITL) |
| ≤8 LLM calls | Per-worker tool-round cap + wave cap |

Still cut: Firecrawl, Elicit Reports / MCP as product, `create_supervisor`, web UI, parallel writers, PDF/paywall full text.

---

## 1. Acceptance criteria

A run **passes** when:

1. **Citation coverage:** every `[src_*]` in `final_report` exists in `sources`.
2. **Grounding floor:** at least one citation, or `uncovered` explains empty retrieval.
3. **Honesty:** `uncovered` lists brief items findings marked as gaps.
4. **ODR shape:** scout ran; clarify was skipped *or* grounded in scout titles; brief exists; workers were isolated; write ran once after research.
5. **Bounds:** every cap below is the value of the run's effort profile, `normal` first and `max` second. `clarify_turns <= 3` (3 / 3); `iteration + 1 <= max_iterations` (3 / 4 waves); topics/wave ≤ 3 / 4 on the first wave and ≤ 2 / 3 after it; model-call rounds/worker ≤ 4 / 6; hits/tool call ≤ 5 / 8. Tool strings into the loop are ≤8000 chars under both profiles.
6. **Resume:** same `thread_id` continues after interrupt.

QA **fails** on dangling citations or exceeded bounds. The CLI exits with status `1` when `uncovered` contains a `dangling:` item. The CLI exits with status `0` when the run completes without dangling citations.

---

## 2. Roles

| Role | Kind | Job |
| :--- | :--- | :--- |
| User | Human | Query; skip / pick / text on clarify turns |
| Scout | Node, 0 LLM | Exa `max_hits` highlights (5 normal, 8 max); the same count of publications iff academic signal |
| Decide-clarify | Node, router LLM | Given query + scout: skip or ask a scout-grounded question |
| Clarifier | `interrupt()` loop | Pause; append the question asked and the user reply to `messages` |
| Brief writer | Node, compress LLM | Compress query + scout + clarify chat → `ResearchBrief` |
| Planner (supervisor) | Node, router LLM | 1 topic if simple; 2 up to the profile's first-wave cap (3 normal, 4 max) if compare/list/multi-entity |
| Researcher | Isolated subgraph | Tool loop (≤ `max_tool_rounds` rounds — 4 normal, 6 max — research LLM) then prune (compress LLM) → `Finding` |
| Reflector | Node, router LLM + cap | Brief vs findings; follow-ups or write |
| Writer | Node, write LLM | One-shot Markdown |
| Auditor | Code | Resolve `[src_*]`; append `## Audit` if dangling |
| Runtime | CLI + SQLite | `thread_id`, keys, caps; role LLM clients |

Planner ≠ auditor.

---

## 3. Graph

```
START
  → scout
  → decide_clarify
       ├─ needed=false → generate_brief
       └─ needed=true  → ask_user (interrupt)
                            ├─ more turns and < max_clarify_turns → decide_clarify
                            └─ else → generate_brief
  → plan_topics                 # 1..first-wave cap topics; no new query → write
  → Send(research_agent)×N
  → reflect
       ├─ follow-ups and iteration + 1 < max_iterations → plan_topics
       └─ else → write_report → audit_citations → END
```

```python
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command, Send

conn = sqlite3.connect("exact.sqlite", check_same_thread=False)
app = workflow.compile(checkpointer=SqliteSaver(conn))
# from_conn_string is a context manager. Construct the saver from a connection.
# HITL is interrupt() inside ask_user. No interrupt_before.
```

**`research_agent`:** parent graph node. Input `{topic, brief, prior_titles}` only. Returns deltas `{sources, findings, errors}`. The tool loop is an ephemeral LangChain `create_agent` with `ModelCallLimitMiddleware(run_limit=max_tool_rounds)` (model-call rounds, not per-tool invocations). Tool messages stay inside that agent and are dropped after prune; they never enter parent `messages`.

**`Send`:** from `plan_topics` via conditional edge. Do not invoke research workers in a Python loop.

**Reflect exit:** `iteration + 1 >= max_iterations` (3 normal, 4 max) → write. Else LLM `{done, followups, uncovered}`. If `done` or no follow-ups → write. Else up to the profile's follow-up cap (2 normal, 3 max) follow-up topics, `iteration += 1`.

---

## 4. State

```python
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
import operator
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


TopicFocus = Literal["web", "people", "company", "publication"]


class Source(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    doi: Optional[str] = None
    snippet: str  # cap 1200
    provider: Literal["exa", "elicit"]
    focus: Optional[TopicFocus] = None  # web | people | company | publication
    retrieved_at: str


class Finding(BaseModel):
    topic_id: str
    claims: list[str]
    source_ids: list[str]
    gaps: list[str]
    covered: list[str] = []


class ClarificationOption(BaseModel):
    id: str
    label: str
    description: str = ""


class UserClarification(BaseModel):
    kind: Literal["skip", "pick", "text"]
    option_ids: list[str] = []
    text: Optional[str] = None


class ResearchBrief(BaseModel):
    question: str
    audience: str = "general"
    intent: Literal["web", "academic", "mixed"]
    must_cover: list[str] = Field(max_length=5)
    exclusions: list[str] = []
    success_criteria: list[str] = []


class PlannedTopic(BaseModel):
    query: str
    focus: TopicFocus = "web"       # web | people | company | publication
    raw_focus: Optional[str] = None  # the dropped token, when one was unknown


class Topic(BaseModel):
    id: str
    query: str
    focus: TopicFocus = "web"
    status: Literal["pending", "done", "failed"] = "pending"


class ExactState(TypedDict):
    initial_query: str
    messages: Annotated[list[AnyMessage], add_messages]  # clarify thread only
    scout_hits: list[Source]  # checkpointed as dicts
    clarification_options: list[ClarificationOption]
    user_clarification: Optional[UserClarification]
    clarify_question: str
    clarify_needed: bool  # routing; replace
    clarify_turns: int
    max_clarify_turns: int  # default 3
    skip_clarify: bool
    brief: Optional[ResearchBrief]
    topics: list[Topic]  # replace
    sources: Annotated[list[Source], operator.add]
    findings: Annotated[list[Finding], operator.add]
    errors: Annotated[list[str], operator.add]
    usage: Annotated[list[dict], operator.add]  # LLM + vendor call events
    prior_titles: list[str]
    prior_queries: list[str]
    followups: list[str]
    continue_research: bool  # routing; replace
    iteration: int
    max_iterations: int  # profile
    effort: str  # "normal" | "max"
    max_topics_first_wave: int  # profile
    max_topics_followup: int  # profile
    final_report: str
    uncovered: list[str]
```

Reducers: `add` keys return **deltas**. `topics` / scout / options / `prior_titles` / `prior_queries` / `followups` / `uncovered` / routing flags are replace. Source ids: `src_{topic_id}_{i}`. Nodes write Pydantic models via `.model_dump()` so checkpointed dicts stay valid shapes.

---

## 5. Tools (research subgraph only)

| Tool | Service | Rule |
| :--- | :--- | :--- |
| `exa_search` | Exa search | Default discovery and news. `num_results=5`. |
| `exa_people_search` | Exa search `category=people` | People / roles / expertise. `num_results=5`. No date or domain filters. |
| `exa_company_search` | Exa search `category=company` | Companies / funding / org facts. `num_results=5`. No date or domain filters. |
| `exa_highlights` | Exa contents/highlights | Read a URL already found. Not full page. |
| `exa_publication_search` | Exa search `category=publication` | Papers with abstract and DOI. Bound iff the topic `focus` is `publication`. `num_results=5`. |

`elicit_search` is dormant: the client and its key stay in the tree, but no live path binds the tool.

**Tool filter by focus.** A worker binds exactly two tools: the search tool of its topic's `focus`, and `exa_highlights`. The map is `web` → `exa_search`, `people` → `exa_people_search`, `company` → `exa_company_search`, `publication` → `exa_publication_search`. A missing or unrecognized focus reads as `web`. `brief.intent` no longer gates any tool; the lane alone decides. A lane that returns nothing names itself in its gap: `lane <focus>: no sources`.

**Topics.** The planner is the only source of topics on every wave. Each topic is `{query, focus}`. A bare string coerces to `focus="web"`; an unknown focus token degrades that one topic to `web`, records the token, and never fails the whole plan. Unused follow-ups reach the planner through the prompt and come back as topics. If the planner gives no usable topic -- a parse failure, or a plan whose entries are all empty -- the wave researches the unused follow-ups directly, else the brief question, on the fallback lane. Topic identity is the pair `(query, focus)`, so the same question in two lanes is two topics, and a lane repeated inside one wave is planned once. Planner topics also dedup against the waves before this one. The prompt gives the planner `prior` with "do not repeat" and asks for every follow-up back "in its own wording", so a retry reaches the wave rephrased and survives the dedup; a verbatim repeat is the planner disobeying, and the dedup is the guard. A wave whose planner topics all dedup away routes to the writer without an `errors` line. Fallback topics are exempt, because no planner rephrased them; `prior_queries` records what was *attempted*, so a follow-up that repeats a failed lane is a retry, and dropping it would end the wave with nothing.

Scout uses the same HTTP clients, not the tool loop. Scout always runs a general Exa search, and adds an Exa `category=publication` search on an academic signal. No key gates either lane. The two lanes are interleaved before the ids are minted, so a later slice keeps both. Academic signal for scout: query heuristic only (`studies`, `trial`, `paper`, `literature`, `meta-analysis`, `doi`, …) because scout runs before clarify. Academic signal for brief intent: the same heuristic on the query, clarification text, or a picked option label/description.

The planner assigns the lane; it does not shape a topic string for the worker to read. The worker holds one search tool and does not choose a category.

No Firecrawl. No MCP. No Elicit Reports.

---

## 6. Clarification (ODR + Exa)

`decide_clarify` sees `initial_query` + scout titles/snippets + the clarify thread (`messages`), so turn 2 decides against the question already asked and the user's answer. Structured output:

- `needed=false` → brief.
- `needed=true` → one question that **cites scout titles**; optional 2–4 angles from hits; `interrupt()`.

If `needed=true` and scout hits exist, the question must contain at least one scout title. If it does not, treat as `needed=false`. Do not interrupt on an ungrounded question. Generic “narrow or broaden?” only if scout is empty. Resume `skip` | `pick` | `text`. Invalid → `skip` (proceed to brief). `--skip-clarify` forces `needed=false`.

`ask_user` and the route after `ask_user` read `max_clarify_turns` from state. Default is `3`.

---

## 7. Node contracts

| Node | LLM role | Notes |
| :--- | :--- | :--- |
| `scout` | none | Exa 5; optional Exa publication 5. Timeout 20s. Fail → empty + `errors`. |
| `decide_clarify` | router | Skip or grounded question. |
| `ask_user` | none | `interrupt()`. |
| `generate_brief` | compress | `must_cover` 1–5. Written once. |
| `plan_topics` | router | 1 up to the profile's first-wave cap; follow-up waves up to the follow-up cap; no duplicate queries. Follow-up queries come from `reflect`. Do not treat them as prior. If every candidate repeats a prior query, write. |
| `research_agent` | research + compress | ≤ `max_tool_rounds` model-call rounds (4 normal, 6 max) via `create_agent` + `ModelCallLimitMiddleware` (research) + 1 prune (compress). Isolated. Tool-loop messages use compact snippets (≤240 chars); each tool string into the loop is capped at 8000 chars; prune sees full snippets (≤1200). Tool notes are name + query/url only. Vendor exception → `gaps=["retrieval failed"]` and `errors`. Empty hits → `gaps=["no sources"]`. Prior-title drop that leaves the bag empty → `gaps=["no new sources"]`. |
| `reflect` | router | Forced write if `iteration + 1 >= max_iterations`. Follow-ups go to `followups`. Do not replace `topics`. |
| `write_report` | write | Temp 0 (1 when thinking is on). Cite existing ids. `## Open questions`. |
| `audit_citations` | none | Regex `[src_…]`. One bracket may group ids (`[src_a, src_b]`); each is checked on its own. |

---

## 7b. Usage observability

Each LLM and successful vendor call appends a `usage` event (reducer `operator.add`). Events store counts and tokens only. The CLI prints `## Usage (effort=<e>)` after the report (and from checkpointed state after a clarify interrupt). USD is estimated at print time from a dated rate table in `usage.py` (Haiku / Sonnet / Exa). Elicit is counted but priced at $0 (subscription). Vendor retries inside Exa/Elicit clients are not metered. Unknown LLM model ids show tokens and omit that slice from the dollar total.

LLM events may include `cache_read` and `cache_creation` from `usage_metadata.input_token_details`. `input_tokens` is the LangChain total (uncached + cache). Cost uses Anthropic multipliers: cache_read at 0.1x input, cache_creation at 1.25x input (5m write estimate).

Event fields: `kind` (`llm` | `exa_search` | `exa_people_search` | `exa_company_search` | `exa_publication_search` | `exa_highlights` | `elicit_search`), `node`, optional `role` / `model` / `input_tokens` / `output_tokens` / `cache_read` / `cache_creation`, `calls` (default 1). `exa_people_search`, `exa_company_search` and `exa_publication_search` price the
same as `exa_search`.

After the report, the CLI always prints `## References` from `sources` (stable ids/titles/urls). The writer must cite `[src_*]` ids but must not invent a bibliography.

Parent `messages` stay clarify-only. Research tool transcripts are never written to usage events.

---

## 8. Runtime

| | |
| :--- | :--- |
| CLI | `uv run exact "…"` |
| Model | `EXACT_MODEL` (default `anthropic:claude-haiku-4-5` via `init_chat_model`) |
| Role models | Optional `EXACT_MODEL_ROUTER`, `EXACT_MODEL_RESEARCH`, `EXACT_MODEL_COMPRESS`, `EXACT_MODEL_WRITE`. Empty inherits `EXACT_MODEL`. |
| Role map | router: `decide_clarify`, `plan_topics`, `reflect`. research: tool loop. compress: `generate_brief`, prune. write: `write_report`. |
| Temperature | `EXACT_TEMPERATURE` (default `0`) |
| Output caps | `EXACT_MAX_TOKENS_ROUTER` / `_RESEARCH` / `_COMPRESS` / `_WRITE` (defaults 1024 / 1024 / 2048 / 8192) |
| Reasoning | `EXACT_REASONING_EFFORT` (default `none`; applied only to GPT-5/6 model ids) |
| Thinking | `EXACT_THINKING_BUDGET` (default `0` = off; Anthropic only when > 0). When on, the request uses `temperature=1` and `max_tokens = budget + role cap`, because Anthropic rejects other temperatures and needs a reply budget above the thinking budget. Anthropic's own minimum is 1024. Thinking also stops Anthropic forcing a tool call, so a router that answers in prose raises `StructuredOutputError` and that node takes its skip or fallback path. |
| Effort | `EXACT_EFFORT` (default `normal`; `normal` or `max`, exact lowercase). It selects one profile row: `max_iterations` 3 / 4, `max_clarify_turns` 3 / 3, `max_tool_rounds` 4 / 6, `max_hits` 5 / 8, `max_topics_first_wave` 3 / 4, `max_topics_followup` 2 / 3, `max_concurrency` 3 / 4. `MAX_ITERATIONS`, `MAX_CLARIFY_TURNS`, `MAX_TOOL_ROUNDS` and `MAX_HITS` override the profile value when the shell or `.env` sets them; no clamp applies to an explicit value. The other three knobs have no env name. Measured 2026-09-18: `max` spent 0.70× the `total` of `normal` on the calibration query, but the two runs ran a different number of waves, so the figure does not isolate the profile (`git show 3fae7b8:docs/plans/effort-levels.md`, § 12). |
| Keys | `EXA_API_KEY` required; `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; `ELICIT_API_KEY` optional |
| Checkpointer | SQLite `exact.sqlite` |
| Concurrency | `max_concurrency` is a top-level `RunnableConfig` key set from the profile (3 normal, 4 max), not a `configurable` entry. It is process-scoped: a resume follows the current shell, not the checkpoint. |
| HTTP | 20s, 1 retry on timeout, 429, or 5xx. Exa has no SDK cancel; on soft timeout Exact reaps the worker thread before retry so calls do not overlap. |
| Exit | `0` on success; `1` if `uncovered` contains `dangling:`; `1` also on CLI misuse (missing key, finished `--thread-id`), which prints a message to stderr instead of a report |

`--effort normal|max` selects the profile for one run. Precedence is flag > `EXACT_EFFORT` > `normal`. An invalid value on either path exits `1` with a message on stderr, before the live-key check. An injected `Runtime` carries its own settings, so the flag does not reach it.

Right after the `thread_id=` line the CLI echoes the resolved caps as `effort=<e> waves=<n> topics=<first>/<followup> rounds=<n> hits=<n> clarify=<n> concurrency=<n>`. Thread-scoped values come from the checkpoint on a resume, else from the seed; process-scoped values always come from the current `Settings`.

A resume compares the effort this run resolved with the `effort` the checkpoint holds. A mismatch exits `1` with `effort mismatch: …`, before the finished-thread check. A checkpoint written without the channel reads as `normal`. Only `effort`, `max_iterations`, `max_clarify_turns` and the two topic caps are thread-scoped; `max_tool_rounds`, `max_hits` and `max_concurrency` are process-scoped and follow the current shell. Output order on start is the `thread_id=` line, then the guard, then the echo line.

`--skip-clarify` for CI. `--thread-id` to resume a thread that waits for an answer.

If the graph interrupts for clarification, the CLI prints the question and exits. Run the CLI again with the same `--thread-id` to answer. A thread that already reached END cannot be re-run: the CLI exits with `thread already finished; use a new --thread-id`, because `sources`, `findings` and `usage` are append channels that a new seed cannot reset.

`ExaClient` accepts an injected SDK. `ElicitClient` is dormant but still accepts an injected `post`. Tests must not call live vendors.

---

## 9. Layout

```
src/exact/
  cli.py config.py models.py graph.py prompts.py audit.py intent.py usage.py
  nodes/   scout, clarify, brief, plan, research, reflect, write, audit_node
  tools/   exa.py elicit.py
tests/
  test_audit.py test_clarify.py test_research.py test_graph.py
  test_cli.py test_exa.py test_elicit.py test_status.py test_usage.py
```

---

## 10. Out of scope

Firecrawl, Elicit Reports/Systematic Review/MCP product, LangGraph Studio as required UI, unbounded reflection, parallel section writing, `create_supervisor`, guaranteed truth.
