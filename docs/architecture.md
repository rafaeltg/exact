# Exact — Architecture (ODR v1.4)

Contract: [spec.md](./spec.md) v1.4.0. LangChain [Open Deep Research](https://www.langchain.com/blog/open-deep-research) pipeline. Tools: Exa. Clarification grounded in scout. `Source` carries a `focus` lane.

```
 User                         exact                         vendors
  |                             |                              |
  |  query                      |                              |
  |---------------------------->|  scout highlights ---------> Exa
  |                             |  scout papers .............> Exa (publication)
  |  clarify? (0..3 turns)      |                              |
  |<--------------------------->|                              |
  |                             |  tool loop ----------------> Exa
  |                             |  role LLMs (temp 0) -------> LLM
  |  cited report               |                              |
  |<----------------------------|                              |
```

CLI process. SQLite checkpointer. No HTTP API.

`Runtime` holds one chat client per role (`router`, `research`, `compress`, `write`) in `extras["llms"]`. Empty role env vars inherit `EXACT_MODEL`. The parent graph still does not see raw tool I/O. Research tool-loop messages carry compact snippets; prune still receives full snippets.

---

## LLM agent configs

Four LLM roles. Scout and `audit_citations` use no LLM. All values below are Settings / env.

| Role | Nodes | Model env | Max tokens env | Default max tokens |
| :--- | :--- | :--- | :--- | ---: |
| router | `decide_clarify`, `plan_topics`, `reflect` | `EXACT_MODEL_ROUTER` | `EXACT_MAX_TOKENS_ROUTER` | 1024 |
| research | `research_agent` (`create_agent` tool loop) | `EXACT_MODEL_RESEARCH` | `EXACT_MAX_TOKENS_RESEARCH` | 1024 |
| compress | `generate_brief`, prune | `EXACT_MODEL_COMPRESS` | `EXACT_MAX_TOKENS_COMPRESS` | 2048 |
| write | `write_report` | `EXACT_MODEL_WRITE` | `EXACT_MAX_TOKENS_WRITE` | 8192 |

```
 EXACT_MODEL                 anthropic:claude-haiku-4-5
 EXACT_MODEL_ROUTER          anthropic:claude-haiku-4-5
 EXACT_MODEL_RESEARCH        anthropic:claude-haiku-4-5
 EXACT_MODEL_COMPRESS        anthropic:claude-haiku-4-5
 EXACT_MODEL_WRITE           anthropic:claude-haiku-4-5
 EXACT_TEMPERATURE           0
 EXACT_MAX_TOKENS_ROUTER     1024
 EXACT_MAX_TOKENS_RESEARCH   1024
 EXACT_MAX_TOKENS_COMPRESS   2048
 EXACT_MAX_TOKENS_WRITE      8192
 EXACT_REASONING_EFFORT      none (GPT-5/6 only)
 EXACT_THINKING_BUDGET       0 (Anthropic; 0 = off)
```

Empty `EXACT_MODEL_*` still inherits `EXACT_MODEL`. `.env.example` sets every role to Haiku so the cost-optimal Anthropic profile is copy-paste ready.

**Client rules** (built in `config.chat_kwargs` from Settings):

- Temperature comes from `EXACT_TEMPERATURE`, except when thinking is on.
- `max_tokens` comes from the role `EXACT_MAX_TOKENS_*` value, except when thinking is on.
- GPT-5 / GPT-6 model ids: pass `reasoning_effort` from `EXACT_REASONING_EFFORT` when non-empty. Default `none` keeps cost low (API default is not `none`).
- Anthropic model ids: if `EXACT_THINKING_BUDGET` > 0, enable extended thinking with that budget. Default `0` leaves thinking off. Thinking overrides the two rules above: the request uses `temperature=1` and `max_tokens = budget + role cap`, because Anthropic rejects other temperatures and needs a reply budget above the thinking budget.
- Other models: ignore reasoning effort and thinking budget.

`Runtime.from_env` builds one client per distinct model + sampling key and maps each role in `extras["llms"]`. Nodes call `runtime.model(role)`.

Quality upgrade (higher cost): set write only to Sonnet.

```
EXACT_MODEL_WRITE=anthropic:claude-sonnet-4-5
```

---

## Graph

```
 START
   |
 scout
   |
 decide_clarify ---- needed=false ----------------+
   |                                              |
   needed=true                                    |
   |                                              |
 ask_user  (interrupt)                            |
   |  skip | pick | text                          |
   |                                              |
   +-- turns < max_clarify_turns --> decide_clarify               |
   +-- else --------------------------------------+
                                                  |
                                           generate_brief
                                                  |
                                            plan_topics
                                           /     |     \
                                        Send   Send   Send     1..3
                                           \     |     /
                                        research_agent
                                        create_agent <=4
                                        then prune
                                           \     |     /
                                            reflect
                                          /          \
                         follow-ups and               done or
                    iteration + 1 < max_iter        iteration + 1 >= max_iter
                              |                            |
                        plan_topics                  write_report
                                                     audit_citations
                                                          END
```

If `plan_topics` has no new query, the graph goes to `write_report`.

---

## Clarification + Exa

```
 query + scout titles/snippets
            |
            v
     decide_clarify
      /           \
   skip            ask, citing scout titles
                    |
                 interrupt
                    |
              skip | pick | text
```

Stock ODR asks in the blind. Exact scouts first. Generic “narrow or broaden?” only if scout is empty.

If the model sets `needed=true` and scout hits exist, the question must contain a scout title. If it does not, Exact sets `needed=false`. Do not interrupt on an ungrounded question.

Routing flags `clarify_needed` and `continue_research` live on state (replace). Structured LLM parse failures skip clarify, fall back to a query brief / single topic, or force write — they do not crash the run.

The scout publication lane uses the query academic heuristic only (scout is before clarify); no key gates it. Brief intent also promotes `web` → `academic` when clarification text or a picked option label/description matches the heuristic.

---

## Isolated research

```
 plan_topics
      |
      |  Send({ topic, brief, prior_titles })
      +------------------+
      v                  v
 research_agent     research_agent
   create_agent         ...
   ModelCallLimitMiddleware(run_limit<=4)
   one lane search tool (by topic focus) + exa_highlights
      |                  |
   prune -> Finding      prune
      +--------+---------+
               v
        sources  +=
        findings +=
        errors   +=     ids src_{topic}_{i}
```

Parent never sees raw tool I/O. The worker ReAct loop is an ephemeral LangChain `create_agent` invoked from the `research_agent` node, not a Python `for`. Spend is still capped in code (`ModelCallLimitMiddleware` counts model-call rounds; one round may run several tools). Tool strings into the loop are clipped at 8000 chars.

---

## Tools

```
 exa_search          discovery and news, 5 hits
 exa_people_search   people profiles (category=people), 5 hits
 exa_company_search  company profiles (category=company), 5 hits
 exa_highlights      read a known URL (not full page)
 exa_publication_search  papers with abstract + DOI (category=publication), 5 hits, bound by focus
```

Scout runs a general Exa search, plus an Exa `category=publication` search on an academic signal; the lanes are interleaved before ids are minted. The planner assigns each topic a `focus` lane, and the worker binds only that lane's search tool plus `exa_highlights` — the agent no longer picks between categories. The planner is the only source of topics on every wave; topics are `{query, focus}` and identity is the pair. A wave with no usable planner topic falls back to the unused follow-ups, else the brief question; the fallback skips the cross-wave dedup, because no planner rephrased it around `prior`, so a retry of a failed lane still runs. Entity metadata (person, company, publication) is folded into `Source.snippet`.

`ExaClient` accepts an injected SDK and a clock. Each search and highlights call uses the HTTP timeout. `ElicitClient` is dormant: it accepts an injected `post` and a clock, but no live path builds it. Each client retries once on timeout, HTTP 429, or HTTP 5xx.

---

## State (short)

```
 REPLACE                         APPEND
 -------                         ------
 scout_hits                      sources
 clarification_options           findings
 brief                           errors
 topics                          usage
 prior_titles
 prior_queries
 followups
 uncovered
 clarify_needed
 continue_research

 messages  +=  clarify thread only (add_messages)
```

`usage` events are LLM and vendor call counts/tokens. The CLI prints a `## Usage` footer with estimated USD (dated rates in `usage.py`), including cache_read / cache_creation when present (Anthropic cache multipliers). Elicit calls are counted at $0. Vendor retries are not metered. See spec §7b.

The CLI also prints `## References` from `sources` after the report so citations resolve even if the writer omits a bibliography.

---

## Bounds

```
 clarify turns <= max_clarify_turns (default 3)
 waves         <= 3
 topics/wave   <= 3
 tool rounds   <= 4 / worker  (ModelCallLimitMiddleware run_limit = model calls)
 tool text     <= 8000 chars into the agent loop
 hits/call     <= 5
```

`ask_user` and the route after `ask_user` read `max_clarify_turns` from state.

Vendor exception: `errors` + finding `gaps=["retrieval failed"]`. Empty hits: finding `gaps=["no sources"]`. Prior-title drop that leaves the bag empty: finding `gaps=["no new sources"]`. The graph still finishes.

If `uncovered` contains a `dangling:` item, the CLI exits with status `1`.

---

## Layout

```
 cli.py --> config.py
        --> usage.py
        --> graph.py --> models.py
                     --> nodes/*
                     --> tools/exa.py
                     --> tools/elicit.py
```

Not in the system: Firecrawl, MCP product, Elicit Reports, `create_supervisor`, parallel writers, guaranteed truth.
