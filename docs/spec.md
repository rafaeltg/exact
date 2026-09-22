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

**`research_agent`:** parent graph node. Input `{topic, brief, prior_titles, prefs}` only. Returns deltas `{sources, findings, errors}`. The tool loop is an ephemeral LangChain `create_agent` with `ModelCallLimitMiddleware(run_limit=max_tool_rounds)` (model-call rounds, not per-tool invocations). Tool messages stay inside that agent and are dropped after prune; they never enter parent `messages`.

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
    prefs: dict  # user preferences, frozen at the seed; see below
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

`prefs` is one replace value that the run seed writes. It holds the twelve preferences of §8 under their state names: `language`, `tone`, `length`, `structure`, `source_mix`, `include_domains`, `exclude_domains`, `denylist`, `recency`, `prefer_primary`, `news_bias` and `clarify_mode`. It also holds two derived keys: `start_published_date` (the frozen `YYYY-MM-DD` date, or `null` for `recency=any`) and `effective_exclude_domains` (the user exclude hosts, then the `denylist` preset hosts, each host once). Readers never compute the derived keys again. Scout, clarify, brief, planner, workers and writer read `prefs` from state, never from `Settings`. Each worker gets `prefs` in its `Send` payload. A clarify answer never changes `prefs`. A checkpoint with no `prefs` reads as all defaults. There is no `skip_clarify` channel. Only the CLI resume guard of §8 reads the old `skip_clarify` value of such a checkpoint. The nodes cannot see it, so they read that thread as all defaults, `clarify_mode=auto` included. The two readings differ only for an old `skip_clarify=true` thread that stopped before `decide_clarify` ran. On a resume, that thread can get one clarify question.

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

**Filters.** Four searches send the domain and date filters of `prefs`: the scout web leg, the scout publication leg, `exa_search` and `exa_publication_search`. `exa_people_search` and `exa_company_search` never send a filter. The Exa arguments are `include_domains` (from `prefs.include_domains`), `exclude_domains` (from `prefs.effective_exclude_domains`) and `start_published_date` (from `prefs.start_published_date`). The raw publication request body uses `includeDomains`, `excludeDomains` and `startPublishedDate`. The degraded publication path sends the snake-case names. An empty list and a `null` date leave the key out, so an unfiltered call sends the same arguments as before. No request sends include and exclude together: §8 refuses that combination at startup. Every search requests the resolved `max_hits`. A filter can return fewer hits.

When `recency` is set, Exa drops each page that has no known publish date. That loss is accepted.

The `denylist` presets:

| Preset | Hosts |
| :--- | :--- |
| `none` | (none) |
| `social` | `facebook.com`, `instagram.com`, `tiktok.com`, `x.com`, `twitter.com`, `reddit.com`, `pinterest.com`, `linkedin.com` |
| `seo` | `quora.com`, `wikihow.com`, `ehow.com`, `answers.com`, `reference.com`, `medium.com`, `hubpages.com`, `ezinearticles.com` |

**Filtered lane gaps.** A lane is filtered when it is `web` or `publication` and `prefs` holds at least one active filter. A search attempt is not necessary. Each gap of a filtered lane ends with a space and `(filters: <names>)`. The names are `include`, `exclude` and `recency`, in that order. A `denylist` preset counts as `exclude`. The suffix applies to `no sources`, `no new sources` and `retrieval failed`, for example `lane web: no sources (filters: exclude, recency)`. An unfiltered lane, and each `people` or `company` lane, keeps its gap text. The trace `tool` line does not name the filters.

**Primary sources.** With `prefer_primary`, `RESEARCH_SYS` gets one line on every lane. The line prefers official and primary sources over secondary roundups. `PRUNE` does not change.

**Tool filter by focus.** A worker binds exactly two tools: the search tool of its topic's `focus`, and `exa_highlights`. The map is `web` → `exa_search`, `people` → `exa_people_search`, `company` → `exa_company_search`, `publication` → `exa_publication_search`. A missing or unrecognized focus reads as `web`. `brief.intent` no longer gates any tool; the lane alone decides. A lane that returns nothing names itself in its gap: `lane <focus>: no sources`.

**Topics.** The planner is the only source of topics on every wave. Each topic is `{query, focus}`. A bare string coerces to `focus="web"`; an unknown focus token degrades that one topic to `web`, records the token, and never fails the whole plan. Unused follow-ups reach the planner through the prompt and come back as topics. If the planner gives no usable topic -- a parse failure, or a plan whose entries are all empty -- the wave researches the unused follow-ups directly, else the brief question, on the fallback lane. Topic identity is the pair `(query, focus)`, so the same question in two lanes is two topics, and a lane repeated inside one wave is planned once. Planner topics also dedup against the waves before this one. The prompt gives the planner `prior` with "do not repeat" and asks for every follow-up back "in its own wording", so a retry reaches the wave rephrased and survives the dedup; a verbatim repeat is the planner disobeying, and the dedup is the guard. A wave whose planner topics all dedup away routes to the writer without an `errors` line. Fallback topics are exempt, because no planner rephrased them; `prior_queries` records what was *attempted*, so a follow-up that repeats a failed lane is a retry, and dropping it would end the wave with nothing.

Scout uses the same HTTP clients, not the tool loop. Scout always runs a general Exa search. `prefs.source_mix` decides the Exa `category=publication` search: `auto` runs it on an academic signal, `web` never runs it, and `academic` and `mixed` always run it. No key gates either lane. Both legs send the filters and request `max_hits`. A filtered leg that returns no hits appends one `errors` line: `exa scout: no hits (filters: <names>)` or `exa publication scout: no hits (filters: <names>)`. An unfiltered empty leg appends none. A leg that raises keeps only its `<label> scout failed: <exc>` line. The clarify behavior does not change. The two lanes are interleaved before the ids are minted, so a later slice keeps both. Academic signal for scout: query heuristic only (`studies`, `trial`, `paper`, `literature`, `meta-analysis`, `doi`, …) because scout runs before clarify. Academic signal for brief intent: the same heuristic on the query, clarification text, or a picked option label/description.

The planner assigns the lane; it does not shape a topic string for the worker to read. The worker holds one search tool and does not choose a category.

No Firecrawl. No MCP. No Elicit Reports.

---

## 6. Clarification (ODR + Exa)

`decide_clarify` sees `initial_query` + scout titles/snippets + the clarify thread (`messages`), so turn 2 decides against the question already asked and the user's answer. Structured output:

- `needed=false` → brief.
- `needed=true` → one question that **cites scout titles**; optional 2–4 angles from hits; `interrupt()`.

If `needed=true` and scout hits exist, the question must contain at least one scout title. If it does not, treat as `needed=false`. Do not interrupt on an ungrounded question. Generic “narrow or broaden?” only if scout is empty. Resume `skip` | `pick` | `text`. Invalid → `skip` (proceed to brief).

`decide_clarify` reads `prefs.clarify_mode`:

- `skip` forces `needed=false` with no router call. `--skip-clarify` is a second name for `--clarify skip`.
- `auto` keeps the behavior above.
- `prefer` replaces the `DECIDE_CLARIFY` sentence "Prefer skipping if the query is specific enough." with a sentence that prefers to ask one grounded question.

The scout-title grounding rule, the generic question on an empty scout, and the turn cap apply in every mode.

The `DECIDE_CLARIFY` prompt names each axis that a set preference settles, and tells the model not to ask about it. `source_mix` other than `auto` settles web versus academic. `recency` other than `any` settles the time range. `tone` other than `neutral` settles the audience. The entity axis stays open. When `language` is not `auto`, the prompt tells the model to write the question and the options in that language, and to quote scout titles unchanged, so the grounding check still finds them. With every one of these at its default, the prompt does not change.

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
| `research_agent` | research + compress | ≤ `max_tool_rounds` model-call rounds (4 normal, 6 max) via `create_agent` + `ModelCallLimitMiddleware` (research) + 1 prune (compress). Isolated. Tool-loop messages use compact snippets (≤240 chars); each tool string into the loop is capped at 8000 chars; prune sees full snippets (≤1200). Tool notes are name + query/url only. Vendor exception → `gaps=["retrieval failed"]` and `errors`. Empty hits → `gaps=["no sources"]`. Prior-title drop that leaves the bag empty → `gaps=["no new sources"]`. `Finding.source_ids` holds minted ids only: prune removes each id that no attempt of this worker minted. |
| `reflect` | router | Forced write if `iteration + 1 >= max_iterations`. Follow-ups go to `followups`. Do not replace `topics`. |
| `write_report` | write | Temp 0 (1 when thinking is on). Cite existing ids. `## Open questions`. |
| `audit_citations` | none | Regex `[src_…]`. One bracket may group ids (`[src_a, src_b]`); each is checked on its own. |

**Brief preferences.** `generate_brief` applies `prefs` after `_normalize`, on the model path and on the fallback path. When `source_mix` is `web`, `academic` or `mixed`, `brief.intent` is that value. No signal, model output or clarify answer changes it. With `source_mix=auto`, the academic-signal rule sets `intent`. When `tone` is not `neutral`, `brief.audience` replaces the model value: `academic` gives `academic researchers`, `executive` gives `executives`, and `plain` gives `general public`. `brief.exclusions` gets up to three notes after the model entries: one for the user exclude list, one for the `denylist` preset, and one restriction note for the include list. Each note names its hosts in stored order. A note equal to a model entry appears once. An empty list or `denylist=none` gives no note.

**Lanes by source mix.** In `plan_topics`, `source_mix=web` changes each `publication` topic to `web`, and `source_mix=academic` changes each `web` topic to `publication`. `people` and `company` topics do not change. `auto` and `mixed` change no topic. The change applies to planner topics and fallback topics. It runs after an unknown focus drops to `web`, and before the topic dedup. The unknown-focus line names the final lane: `plan: dropped unknown topic focus '<token>'; used <lane>`. A lane change writes no other `errors` line. When a changed topic and another topic have the same query and lane, the first in planner order survives. The `PLAN` prompt does not change for `source_mix`.

**Search bias.** With `prefer_primary`, `PLAN` gets the line that prefers official and primary sources over secondary roundups. With `news_bias`, `PLAN` gets one line that shapes web-lane queries as news queries with event, outlet and date cues. The news line is the same with or without `recency`. Neither preference changes a filter argument or a cap.

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
| Thinking | `EXACT_THINKING_BUDGET` (default `0` = off; Anthropic only when > 0). When on, the request uses `temperature=1` and `max_tokens = budget + role cap`, because Anthropic rejects other temperatures and needs a reply budget above the thinking budget. Anthropic's own minimum is 1024. Thinking also stops Anthropic forcing a tool call, so a router that answers in prose raises `StructuredOutputError` and that node takes its skip or fallback path. |
| Effort | `EXACT_EFFORT` (default `normal`; `normal` or `max`, exact lowercase). It selects one profile row: `max_iterations` 3 / 4, `max_clarify_turns` 3 / 3, `max_tool_rounds` 4 / 6, `max_hits` 5 / 8, `max_topics_first_wave` 3 / 4, `max_topics_followup` 2 / 3, `max_concurrency` 3 / 4. `MAX_ITERATIONS`, `MAX_CLARIFY_TURNS`, `MAX_TOOL_ROUNDS` and `MAX_HITS` override the profile value when the shell or `.env` sets them; no clamp applies to an explicit value. The other three knobs have no env name. Measured 2026-09-18: `max` spent 0.70× the `total` of `normal` on the calibration query, but the two runs ran a different number of waves, so the figure does not isolate the profile (`git show 3fae7b8:docs/plans/effort-levels.md`, § 12). |
| Keys | `EXA_API_KEY` and `ANTHROPIC_API_KEY` required; `ELICIT_API_KEY` optional |
| Checkpointer | SQLite `exact.sqlite` |
| Concurrency | `max_concurrency` is a top-level `RunnableConfig` key set from the profile (3 normal, 4 max), not a `configurable` entry. It is process-scoped: a resume follows the current shell, not the checkpoint. |
| HTTP | 20s, 1 retry on timeout, 429, or 5xx. Exa has no SDK cancel; on soft timeout Exact reaps the worker thread before retry so calls do not overlap. |
| Exit | `0` on success; `1` if `uncovered` contains `dangling:`; `1` also on CLI misuse (missing key, finished `--thread-id`, invalid knob, refused trace path), which prints a message to stderr instead of a report |

`--effort normal|max` selects the profile for one run. Precedence is flag > `EXACT_EFFORT` > `normal`. An invalid value on either path exits `1` with a message on stderr, before the live-key check. An injected `Runtime` carries its own settings, so the flag does not reach it.

Right after the `thread_id=` line the CLI echoes the resolved caps as `effort=<e> waves=<n> topics=<first>/<followup> rounds=<n> hits=<n> clarify=<n> concurrency=<n>`. Thread-scoped values come from the checkpoint on a resume, else from the seed; process-scoped values always come from the current `Settings`.

A resume compares the effort this run resolved with the `effort` the checkpoint holds. A mismatch exits `1` with `effort mismatch: …`, before the finished-thread check. A checkpoint written without the channel reads as `normal`. Only `effort`, `max_iterations`, `max_clarify_turns` and the two topic caps are thread-scoped; `max_tool_rounds`, `max_hits` and `max_concurrency` are process-scoped and follow the current shell. Output order on start is the `thread_id=` line, then `trace=` when tracing is on, then any trace warning on stderr, then the effort guard, then the preference guard, then the `effort=` echo line, then the `prefs` echo line, then `run_start`.

`--skip-clarify` for CI. `--thread-id` to resume a thread that waits for an answer. `--trace` and `--verbose` are in §8b.

### Preferences

A preference changes prompts, brief defaults, Exa filter arguments, the lanes that a run searches, and clarify routing. It never raises a cap of the effort profile, never changes the requested hit count, a role model or the temperature, and never adds a vendor. Every bound of §1 holds for every combination.

| Preference | CLI | Env | `Settings` field | Values | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `language` | `--lang` | `EXACT_LANGUAGE` | `exact_language` | `auto`, `en`, `es`, `pt` | `auto` |
| `tone` | `--tone` | `EXACT_TONE` | `exact_tone` | `neutral`, `academic`, `executive`, `plain` | `neutral` |
| `length` | `--length` | `EXACT_LENGTH` | `exact_length` | `short`, `standard`, `long` | `standard` |
| `structure` | `--structure` | `EXACT_STRUCTURE` | `exact_structure` | `report`, `memo`, `bullets` | `report` |
| `source_mix` | `--sources` | `EXACT_SOURCE_MIX` | `exact_source_mix` | `auto`, `web`, `academic`, `mixed` | `auto` |
| `include_domains` | `--include-domain` (repeats) | `EXACT_INCLUDE_DOMAINS` | `exact_include_domains` | host list | empty |
| `exclude_domains` | `--exclude-domain` (repeats) | `EXACT_EXCLUDE_DOMAINS` | `exact_exclude_domains` | host list | empty |
| `denylist` | `--denylist` | `EXACT_DENYLIST` | `exact_denylist` | `none`, `social`, `seo` | `none` |
| `recency` | `--since` | `EXACT_RECENCY` | `exact_recency` | `any`, `year`, `month`, `week` | `any` |
| `prefer_primary` | `--prefer-primary` / `--no-prefer-primary` | `EXACT_PREFER_PRIMARY` | `exact_prefer_primary` | boolean | false |
| `news_bias` | `--news` / `--no-news` | `EXACT_NEWS_BIAS` | `exact_news_bias` | boolean | false |
| `clarify_mode` | `--clarify` | `EXACT_CLARIFY_MODE` | `exact_clarify_mode` | `auto`, `skip`, `prefer` | `auto` |

Precedence is flag > environment > default. A domain environment variable is a comma-separated host list: spaces around entries are removed and empty entries are dropped. One use of a domain flag replaces the whole environment list. No flag clears a domain list that the environment sets; `--denylist none` clears a preset. `--skip-clarify` is a second name for `--clarify skip`. Each preference flag also overrides the settings of an injected `Runtime`, and the result passes the same checks. `--effort` is the only flag that does not reach an injected `Runtime`.

`recency` becomes `start_published_date`: the UTC date 365 (`year`), 30 (`month`) or 7 (`week`) days before the instant that the first run seeds the thread. The date is stored in `prefs` and reused on every resume.

**Validation.** `Settings` validators hold the preference checks, so an invalid `Settings` fails wherever it is built. The CLI holds only the `--skip-clarify` conflict check. The checks run before the live-key check. An invalid value exits `1` with one message on stderr. An enum value must match exactly, in lowercase, with no spaces. A domain entry must be a strict ASCII host: two or more dot-separated labels, each `[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?`, and a last label that is not all digits. So a scheme, path, port, wildcard, IP address, single-label name, trailing dot or non-ASCII name is refused. Punycode is accepted, and `www.a.com` and `a.com` are two hosts. Each user domain list holds at most 20 hosts after duplicates are removed; preset hosts do not count. The messages:

```text
<name> must be one of '<v1>', '<v2>', …; got '<value>' (<flag> or <ENV>)
<name> must be a boolean such as 0 or 1; got '<value>' (<flag> or <ENV>)
<name>: '<entry>' is not a host name (<flag> or <ENV>)
<name> holds <n> hosts; at most 20 (<flag> or <ENV>)
include domains cannot combine with exclude domains or a denylist (--include-domain, --exclude-domain, --denylist)
--skip-clarify cannot combine with --clarify <value>
```

Only the first failure is reported, in this order: effort, then the preferences in table order, then the `--skip-clarify` conflict, then `EXACT_TRACE` and `EXACT_VERBOSE`. The include refusal ranks as `denylist`.

**Resume.** A resume resolves the preferences from flags, environment and defaults, and compares them with the checkpoint `prefs`. Enums and booleans compare by value, domain lists as sorted sets, `denylist` by preset name, and `recency` by enum, not by date. The refusal order is effort mismatch, then preference mismatch, then finished thread. A difference exits `1` with one message on stderr, and writes no trace line:

```text
preference mismatch: <name> thread=<stored> run=<resolved>; …; rerun with the same preferences or use a new --thread-id
```

A list value prints comma-joined and a boolean prints `true` or `false`. A resume with `--skip-clarify` of a thread seeded with `clarify_mode=auto` is a mismatch. A checkpoint with no `prefs` reads as all defaults. When that checkpoint holds `skip_clarify=true`, it reads as `clarify_mode=skip`.

**Echo.** Directly after the `effort=` line the CLI prints `prefs=default`, or `prefs` and one `name=value` pair for each preference that is not at its default, in table order, for example `prefs tone=plain exclude_domains=b.com,a.com recency=month`. A list joins its hosts with commas in stored order. The derived keys are not shown. On a resume the values come from the checkpoint.

**Output.** `write_report` puts one fixed line for each of `language`, `tone`, `length` and `structure` into `WRITE`. Every value adds its line, the defaults included, except `tone=neutral`, which adds none. Code holds the exact strings.

- `language`: `auto` tells the writer to use the language of `initial_query`. `en`, `es` and `pt` name English, Spanish and Portuguese. `auto`, `es` and `pt` also tell the writer to write the other headings in that language. Every language keeps the heading `## Open questions` in English. Claims may be translated. Uncited content may not be added.
- `tone`: `academic` is formal, with precise terms and hedged claims. `executive` leads with conclusions and decisions, with little jargon. `plain` uses short sentences and everyday words, and defines terms.
- `length`: `short` is 300 to 500 words, `standard` 800 to 1500 words, and `long` 2000 to 3500 words.
- `structure`: `report` is a cohesive report with sections. `memo` has Summary, Findings and Implications sections, in prose. `bullets` has headed sections whose bodies are bullet lists, with one cited claim for each bullet; the `## Open questions` bullets need no citation.

Every structure keeps the citation rule and ends with `## Open questions`. `length=long` fits the default write cap of 8192 tokens. Under an `EXACT_MAX_TOKENS_WRITE` below 8192, a `long` report can end early. No check compares the two.

If the graph interrupts for clarification, the CLI prints the question and exits. Run the CLI again with the same `--thread-id` to answer. A thread that already reached END cannot be re-run: the CLI exits with `thread already finished; use a new --thread-id`, because `sources`, `findings` and `usage` are append channels that a new seed cannot reset.

`ExaClient` accepts an injected SDK. `ElicitClient` is dormant but still accepts an injected `post`. Tests must not call live vendors.

---

## 8b. Trace sidecar and verbose lines

### Controls

| Knob | CLI | Env | `Settings` field | Default |
| :--- | :--- | :--- | :--- | :--- |
| Trace | `--trace` / `--no-trace` | `EXACT_TRACE` | `exact_trace: bool` | off |
| Trace path | `--trace-path PATH` | `EXACT_TRACE_PATH` | `exact_trace_path: str` | empty = derived |
| Verbose | `--verbose` / `--no-verbose` | `EXACT_VERBOSE` | `exact_verbose: bool` | off |

Precedence is flag > `Settings` field > default. The field reads the environment. An injected `Runtime` supplies the field, so these knobs reach it, unlike `--effort`. `--no-trace` overrides `EXACT_TRACE=1`. `--no-verbose` overrides `EXACT_VERBOSE=1`. The two booleans accept `0`/`1`, `true`/`false`, `yes`/`no` and `on`/`off`. Use `0` or `1`. Any other value exits `1` with `EXACT_TRACE must be a boolean such as 0 or 1; got 'maybe'` on stderr (or the same text for `EXACT_VERBOSE`). An invalid effort value has precedence over an invalid boolean. `--trace-path` only moves the file. It never turns tracing on. Only the CLI reads these three fields.

The two controls are independent. `--verbose` alone writes no sidecar. `--trace` alone changes no status line.

### Path and startup refusals

The derived path is the `traces/{thread_id}.jsonl` child of the directory that holds `EXACT_DB`. The CLI joins the path parts. `EXACT_DB=exact.sqlite` gives `./traces/{thread_id}.jsonl`. A relative path resolves against the working directory at startup. `.gitignore` holds `traces/`.

When tracing is on, the CLI validates and opens the file before it prints a line and before any model call. Each refusal exits `1` with its message on stderr and nothing on stdout:

```text
trace: --thread-id <id> cannot be a file name; pass --trace-path
trace: <path> is the checkpoint database; pass a different --trace-path
trace: cannot write <path>: <reason>
```

The first refusal applies only to a derived path, when the id holds `/` or `\`, or is `.` or `..`. The second compares both paths after `Path.resolve(strict=False)`. The third covers a parent directory that the CLI cannot create and a file that it cannot open. The CLI creates the parent directory at startup. When the open succeeds, stdout gets `trace=<absolute path>` on the line after `thread_id=`.

The open comes before the effort and preference guards. An `effort mismatch` or `preference mismatch` exit therefore leaves an empty file, or an unchanged file on a resume. It writes no line.

### Resume warnings

Neither the state nor the checkpoint holds the trace flags or the path. A resume must repeat them. The CLI prints each warning that holds on stderr, in this order, and continues:

```text
warning: trace off; <path> holds earlier turns of this thread                                          (W1)
warning: thread <id> resumes, but <path> did not exist; pass the same --trace-path as the first run   (W2)
warning: <path> holds lines for thread <other>; this run is thread <id>                                (W3)
```

- W1: tracing is off, `--thread-id` is given, and the resolved path exists. This is the one change that a run with no trace flag can show. Stdout does not change.
- W2: tracing is on, `--thread-id` is given, the checkpoint holds the thread, and the path did not exist before the open. The first run of a new thread gets no W2.
- W3: tracing is on, and the first line of the file names another `thread_id`. The CLI reads the first line only. A first line that is not JSON, or has no `thread_id`, gives no warning.

### Format

UTF-8 JSONL, one object per line, `ensure_ascii=False`. The tracer flushes each line. Each line has seven envelope keys:

| Key | Meaning |
| :--- | :--- |
| `v` | Integer format version. Starts at `1` |
| `ts` | UTC ISO-8601 time with six fractional digits and `+00:00` |
| `run_id` | A new UUID4 for each open of the file |
| `thread_id` | LangGraph thread id |
| `seq` | Integer. Starts at `1` in each `run_id` and rises by one for each written line |
| `kind` | Event kind below |
| `data` | The whole payload |

The order of lines is `(run_id, seq)`. Do not sort by `ts`: parallel workers write at the same time. Runs in one file are in the order of the first line of each `run_id`. A resume with the same trace path appends to the file under a new `run_id`.

Version rule: an added field keeps `v`. A renamed or removed field increases `v`.

Every payload key is always present. An unknown or not applicable value is `null`.

A payload that names a topic carries `topic_id` and `wave` together. The emitter reads `wave` from the topic id. Do not parse the topic id. The first wave is wave `0`. `wave` is `null` when `topic_id` is `null`, is `"scout"`, or has no wave in it. `topic_id` is `"scout"` on the lines of the scout node and `null` on the lines of each other node that is not `research_agent`. This rule applies to a scalar `topic_id` key only, so `plan` has no `topic_id`.

### Kinds

| Kind | `data` keys | Emitter |
| :--- | :--- | :--- |
| `run_start` | `query` (the argv text), `verbose` (the resolved flag), `resume` (`bool(snap.next)`), `settings` | CLI |
| `decision` | `stage`=`clarify`: `stage`, `needed`. `stage`=`reflect`: `stage`, `continue`, `followups`, `uncovered` | CLI sink |
| `brief` | `intent`, `must_cover`, `question` | CLI sink |
| `plan` | `wave`, `topics` (list of `{id, query, focus}`) | CLI sink |
| `tool` | `name`, `outcome`, `topic_id`, `wave`, `query`, `url`, `hit_count`, `sources`, `error` | `Runtime` tracer |
| `finding` | `topic_id`, `wave`, `claims`, `source_ids`, `gaps` | CLI sink |
| `usage` | `kind`, `node`, `role`, `model`, `input_tokens`, `output_tokens`, `cache_read`, `cache_creation`, `calls`, `topic_id`, `wave` | CLI sink |
| `report_refs` | `cited`, `uncited`, `dangling` | CLI |
| `run_end` | `outcome`, `dangling`, `dropped`, `error` | CLI |

The shapes of `run_start`, `run_end`, `tool` and `report_refs` are **provisional**. They can change before an eval reads them. The envelope is not provisional.

- `run_start.settings` holds the eight keys of the `effort=` echo line (`effort`, `max_iterations`, `max_clarify_turns`, `max_topics_first_wave`, `max_topics_followup`, `max_tool_rounds`, `max_hits`, `max_concurrency`), plus `models` and `max_tokens` (each a map of the four roles), `temperature` and `thinking_budget`. These are the configured values, not the values that thinking writes into a request. It also holds `prefs`: the full `prefs` dict of §4, the derived keys included, as the `prefs` echo line reads it.
- **Redaction rule:** the sidecar never holds an API key or any `Settings` field whose name ends in `_api_key`.
- **Summary-only rule:** the sidecar never holds a snippet body, a highlights body or a vendor JSON blob. A source appears only as a crumb.
- The sink writes one `decision` per `decide_clarify` chunk and one per `reflect` chunk. `ask_user` and `audit_citations` write no `decision`. `reflect.followups` is `[]` when the node returns none. The key name `continue` is a Python keyword: read it by subscript.
- `brief` holds the raw values of the `brief` channel. `intent` is `null` when the node gives none.
- `plan.wave` is the chunk `iteration`, else the wave of the first topic id. An empty topic list is still one line.
- `finding` has five keys. `finding.claims` is a count, not the claim list of `Finding`. `Finding.covered` is not written. A worker that found nothing still writes one `finding` with its gap text.
- `usage` has one line per event of a chunk `usage` list. A vendor tool event writes `null`, not `0`, for `role`, `model` and the four token keys. To sum tokens, keep the lines where `kind` is `llm`. The file holds no USD. A structured LLM call that fails returns no usage event, so no `usage` line records it.
- `tool` has one line per attempt. `outcome` is `ok`, `refused` or `error`. `query` is set for a search and `url` for a highlights read; the other one is `null`. `hit_count` is the raw hit count of the attempt, before the prior-title drop, and `null` on `refused` and `error`. `sources` is one crumb `{id, title, url, doi}` per minted source, and `[]` on `refused` and `error`. `url` and `doi` can each be `null`. A hit that the prior-title drop removes has no crumb. `error` is `str(exc)` cut to 500 characters on `error`, else `null`. The `errors` channel keeps its own label prefix, so join a `tool` error to an `errors` item on `topic_id`, not on the text.
- A failed attempt has a `tool` line and no `usage` line: `usage` counts billable calls and `tool` records attempts. A tool loop that fails before any attempt gives a `finding` with `lane <focus>: retrieval failed` and no `tool` line.
- The scout writes one `tool` line per Exa leg that ran, after it mints the `src_scout_*` ids. Its `hit_count` is the number of hits of that leg.
- `report_refs` is written on a `finished` run only, just before `run_end`. `cited` is the sorted unique set of the `[src_*]` ids in the final report. `uncited` is the sorted set of `sources` ids not in `cited`. `dangling` is the sorted set of `cited` ids not in `sources`.
- `run_end.outcome` is `finished`, `interrupted` (the clarify pause, or Ctrl-C), `rejected` (`thread already finished`) or `error` (any other exception, with `error` = `<Class>: <message>` cut to 500 characters). `dangling` is the count of `dangling:` items in `uncovered` on `finished`, else `null`. A dangling-citation run is `finished` and exits `1`. `dropped` is the number of events the run could not write.
- `run_end` is the last line of its run. A `run_id` with no `run_end` means that the process stopped before the end.

**Join invariant.** In one `run_id`, each id in `finding.source_ids`, and each `report_refs.cited` id that is not in `dangling`, is in the crumbs of a `tool` line whose `topic_id` is not `"scout"`. No `dangling` id is in such a crumb.

### Write rules

- The tracer is the only writer of the file. One process-local lock guards each write and the `seq` it takes. Two processes on one path can mix their lines.
- `--trace` sends each worker's write through this lock and one flush for each line. This serializes the workers at each write. The ceilings limit the cost: concurrency is at most 4 and tool rounds at most 6.
- A write that fails does not stop the run. The first failure prints `warning: trace write failed: <exc>; later failures are counted in run_end` on stderr. Later failures only increase the count. A chunk that the sink cannot read also counts as one dropped event.
- After `run_end` the tracer is closed. A later write from a worker thread is discarded without a count or a warning.

### Verbose detail lines

`--verbose` adds detail lines under four default status lines. Each detail line starts with two spaces. The items keep the order of the state list. An empty list adds no line.

| After | Detail line | Source |
| :--- | :--- | :--- |
| `[brief] …` and its question line | `  - {item}` | `brief.must_cover` |
| `[research tN] …` | `  gap: {gap}`, then `  error: {error}` once per distinct error | `findings[0].gaps`, `errors` |
| `[reflect] …` and its follow-ups | `  uncovered: {item}` | `uncovered` |
| `[audit] …` | `  dangling: {id}`, without the `dangling:` prefix | `uncovered` items that start with `dangling:` |

`[scout]`, `[clarify]`, `[plan]` and `[write]` print the same lines under both settings. The default status lines do not change.

---

## 9. Layout

```
src/exact/
  cli.py config.py models.py graph.py prompts.py audit.py intent.py usage.py
  status.py sink.py trace.py
  nodes/   scout, clarify, brief, plan, research, reflect, write, audit_node
  tools/   exa.py elicit.py
tests/
  test_audit.py test_clarify.py test_research.py test_graph.py
  test_cli.py test_exa.py test_elicit.py test_status.py test_usage.py
  test_sink.py test_trace.py
```

---

## 10. Out of scope

Firecrawl, Elicit Reports/Systematic Review/MCP product, LangGraph Studio as required UI, unbounded reflection, parallel section writing, `create_supervisor`, guaranteed truth.
