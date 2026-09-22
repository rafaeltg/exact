# Exact — Architecture (ODR v1.5)

Contract: [spec.md](./spec.md) v1.5.0. LangChain [Open Deep Research](https://www.langchain.com/blog/open-deep-research) pipeline. Tools: Exa. Clarification grounded in scout. `Source` carries a `focus` lane.

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
 EXACT_THINKING_BUDGET       0 (Anthropic; 0 = off)
 EXACT_EFFORT                normal (normal | max)
```

Empty `EXACT_MODEL_*` still inherits `EXACT_MODEL`. `.env.example` sets every role to Haiku so the cost-optimal Anthropic profile is copy-paste ready.

**Client rules** (built in `config.chat_kwargs` from Settings):

- Temperature comes from `EXACT_TEMPERATURE`, except when thinking is on.
- `max_tokens` comes from the role `EXACT_MAX_TOKENS_*` value, except when thinking is on.
- Anthropic model ids: if `EXACT_THINKING_BUDGET` > 0, enable extended thinking with that budget. Default `0` leaves thinking off. Thinking overrides the two rules above: the request uses `temperature=1` and `max_tokens = budget + role cap`, because Anthropic rejects other temperatures and needs a reply budget above the thinking budget.
- Other models: ignore the thinking budget.

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
                                        Send   Send   Send     1..first cap
                                           \     |     /
                                        research_agent
                                        create_agent <= tool rounds
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

`plan_topics` changes lanes by `prefs.source_mix`: `web` changes each `publication` topic to `web`, and `academic` changes each `web` topic to `publication`. `people` and `company` topics do not change; `auto` and `mixed` change nothing. The change applies to planner and fallback topics, after an unknown focus drops to `web` and before the dedup. The unknown-focus line names the final lane (`used <lane>`). A lane change writes no other `errors` line, and on a collision the first topic in planner order survives. The `PLAN` prompt does not change for `source_mix`.

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

`prefs.source_mix` gates the scout publication lane: `auto` runs it on the query academic heuristic only (scout is before clarify), `web` never runs it, and `academic` and `mixed` always run it. No key gates it. Both scout legs send the filters. A filtered leg with no hits appends `exa scout: no hits (filters: <names>)` or `exa publication scout: no hits (filters: <names>)`; a leg that raises keeps only its failure line.

`decide_clarify` reads `prefs.clarify_mode`. `skip` makes no router call. `prefer` swaps the skip-bias sentence of `DECIDE_CLARIFY` for one that prefers to ask. The prompt names each axis that a preference settles (`source_mix`: web versus academic; `recency`: time range; `tone`: audience) and tells the model not to ask about it. A `language` other than `auto` makes the model ask in that language and quote scout titles unchanged. Brief intent also promotes `web` → `academic` when clarification text or a picked option label/description matches the heuristic.

---

## Isolated research

```
 plan_topics
      |
      |  Send({ topic, brief, prior_titles, prefs })
      +------------------+
      v                  v
 research_agent     research_agent
   create_agent         ...
   ModelCallLimitMiddleware(run_limit <= tool rounds)
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

A `web` or `publication` lane is filtered when `prefs` holds an active filter. Each gap of a filtered lane ends with a space and `(filters: <names>)`, with the names in `include`, `exclude`, `recency` order, for example `lane web: no sources (filters: exclude, recency)`. A search attempt is not necessary. `prefer_primary` adds one primary-source line to `RESEARCH_SYS` on every lane.

---

## Tools

```
 exa_search          discovery and news, max_hits (5 normal, 8 max)
 exa_people_search   people profiles (category=people), max_hits (5 normal, 8 max)
 exa_company_search  company profiles (category=company), max_hits (5 normal, 8 max)
 exa_highlights      read a known URL (not full page)
 exa_publication_search  papers with abstract + DOI (category=publication), max_hits (5 normal, 8 max), bound by focus
```

Scout runs a general Exa search, plus an Exa `category=publication` search on an academic signal; the lanes are interleaved before ids are minted. The planner assigns each topic a `focus` lane, and the worker binds only that lane's search tool plus `exa_highlights` — the agent no longer picks between categories. The planner is the only source of topics on every wave; topics are `{query, focus}` and identity is the pair. A wave with no usable planner topic falls back to the unused follow-ups, else the brief question; the fallback skips the cross-wave dedup, because no planner rephrased it around `prior`, so a retry of a failed lane still runs. Entity metadata (person, company, publication) is folded into `Source.snippet`.

`exa_search`, `exa_publication_search` and both scout legs send the Exa filter arguments `include_domains`, `exclude_domains` and `start_published_date`. The raw publication body uses `includeDomains`, `excludeDomains` and `startPublishedDate`; the degraded path uses the snake-case names. `exa_people_search` and `exa_company_search` send none. An empty filter leaves its key out. With `recency` set, Exa drops pages with no known publish date. The `denylist` presets:

```
 social  facebook.com instagram.com tiktok.com x.com twitter.com reddit.com pinterest.com linkedin.com
 seo     quora.com wikihow.com ehow.com answers.com reference.com medium.com hubpages.com ezinearticles.com
```

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
 prefs  (frozen at the seed; never written again)

 messages  +=  clarify thread only (add_messages)
```

`prefs` holds the twelve preferences under their state names (`language`, `tone`, `length`, `structure`, `source_mix`, `include_domains`, `exclude_domains`, `denylist`, `recency`, `prefer_primary`, `news_bias`, `clarify_mode`), plus the derived `start_published_date` and `effective_exclude_domains`. Nodes read `prefs` from state, never from `Settings`. There is no `skip_clarify` channel.

`usage` events are LLM and vendor call counts/tokens. The CLI prints a `## Usage` footer with estimated USD (dated rates in `usage.py`), including cache_read / cache_creation when present (Anthropic cache multipliers). Elicit calls are counted at $0. Vendor retries are not metered. See spec §7b.

The CLI also prints `## References` from `sources` after the report so citations resolve even if the writer omits a bibliography.

---

## Bounds

```
                       normal   max
 clarify turns             3       3    (max_clarify_turns)
 waves                     3       4    (max_iterations)
 topics/first wave         3       4
 topics/follow-up wave     2       3
 tool rounds / worker      4       6    (ModelCallLimitMiddleware run_limit)
 hits/call                 5       8    (max_hits)
 concurrency               3       4    (max_concurrency, top-level config)
 tool text              8000    8000    chars into the agent loop
```

`ask_user` and the route after `ask_user` read `max_clarify_turns` from state.

Vendor exception: `errors` + finding `gaps=["retrieval failed"]`. Empty hits: finding `gaps=["no sources"]`. Prior-title drop that leaves the bag empty: finding `gaps=["no new sources"]`. The graph still finishes.

If `uncovered` contains a `dangling:` item, the CLI exits with status `1`.

---

## Preferences

```
 flag                 env                    values
 --lang               EXACT_LANGUAGE         auto en es pt
 --tone               EXACT_TONE             neutral academic executive plain
 --length             EXACT_LENGTH           short standard long
 --structure          EXACT_STRUCTURE        report memo bullets
 --sources            EXACT_SOURCE_MIX       auto web academic mixed
 --include-domain     EXACT_INCLUDE_DOMAINS  hosts (flag repeats; env comma list)
 --exclude-domain     EXACT_EXCLUDE_DOMAINS  hosts (flag repeats; env comma list)
 --denylist           EXACT_DENYLIST         none social seo
 --since              EXACT_RECENCY          any year month week
 --[no-]prefer-primary EXACT_PREFER_PRIMARY  boolean
 --[no-]news          EXACT_NEWS_BIAS        boolean
 --clarify            EXACT_CLARIFY_MODE     auto skip prefer   (--skip-clarify = skip)
```

A preference never changes a cap, a hit count, a model or the temperature. Flag > environment > default. Each flag also reaches an injected `Runtime`; `--effort` does not. `Settings` validators hold the checks; the CLI holds only the `--skip-clarify` conflict. The first failure is reported: effort, preferences in table order, the `--skip-clarify` conflict, then the trace and verbose booleans. Messages:

```
 <name> must be one of '<v1>', …; got '<value>' (<flag> or <ENV>)
 <name> must be a boolean such as 0 or 1; got '<value>' (<flag> or <ENV>)
 <name>: '<entry>' is not a host name (<flag> or <ENV>)
 <name> holds <n> hosts; at most 20 (<flag> or <ENV>)
 include domains cannot combine with exclude domains or a denylist (--include-domain, --exclude-domain, --denylist)
 --skip-clarify cannot combine with --clarify <value>
```

The seed writes `prefs` once. `recency` becomes a UTC start date at the seed instant and is reused on every resume. A resume compares the resolved preferences with the checkpoint (host lists as sets) after the effort guard, and exits `1` on a difference with no trace line:

```
 preference mismatch: <name> thread=<v> run=<v>; …; rerun with the same preferences or use a new --thread-id
```

A checkpoint with no `prefs` reads as defaults, or as `clarify_mode=skip` when it holds `skip_clarify=true`. After the `effort=` line the CLI prints `prefs=default`, or `prefs` plus each non-default `name=value`, in table order. `run_start.settings.prefs` holds the full dict.

`generate_brief` forces `intent` from a set `source_mix`, sets `audience` from a non-neutral `tone`, and appends host notes to `exclusions`. `PLAN` gets a primary-source line with `prefer_primary` and a news line with `news_bias`. `WRITE` gets one line each for `language`, `tone` (none for `neutral`), `length` (300–500, 800–1500, 2000–3500 words) and `structure` (`report`, `memo`, `bullets`). `## Open questions` stays in English, and its bullets need no citation under `bullets`. `length=long` can end early under a write cap below 8192 tokens.

---

## Trace sidecar and status lines

```
 stream updates  --sink.py-->    tracer  --append-->  traces/{thread_id}.jsonl
                 --status.py-->  CLI stdout
 _Bag / scout    --emit-->       Runtime.tracer  --append-->  same file (one lock)
 CLI: flags, path checks, open, run_start, report_refs, run_end, close
```

| Role | Owns |
| :--- | :--- |
| Tracer (`trace.py`) | The only writer of the sidecar. One lock, `run_id`, `seq`, one flush for each line. `NullTracer` writes nothing when tracing is off. |
| CLI sink (`sink.py`) | Derives `decision`, `brief`, `plan`, `finding` and `usage` from the `stream_mode=updates` chunks that the status loop reads. It needs no node binding. A chunk that it cannot read is one dropped event, not a failed run. |
| `_Bag`, `_Tools`, scout | Emit one `tool` summary for each attempt: name, args, hit count and one crumb for each minted source. They never put raw tool I/O on parent state. |
| `status.py` | Human lines only. `--verbose` adds detail lines. It never writes the sidecar. |
| CLI | Resolves the flags, checks and opens the path, writes `run_start`, `report_refs` and `run_end`, and closes the tracer in a `finally`. |

The tracer is run-scoped. The CLI builds it after it derives `thread_id`, then gives `build_graph` a copy of the runtime made with `dataclasses.replace`. The CLI never changes the injected `Runtime`: every node closes over one runtime object. `Runtime.tracer` is a field, not an `extras` key, because `replace` would share the `extras` dict with the caller. The tracer never goes into checkpointed state. `trace.py` imports nothing from `exact`, so every module can import it without a cycle.

The parent graph still never sees raw tool I/O. The sidecar holds summaries only. See spec §8b.

---

## Layout

```
 cli.py --> config.py --> trace.py
        --> usage.py
        --> status.py
        --> sink.py --> trace.py
        --> graph.py --> models.py
                     --> nodes/* --> trace.py
                     --> tools/exa.py
                     --> tools/elicit.py
```

Not in the system: Firecrawl, MCP product, Elicit Reports, `create_supervisor`, parallel writers, guaranteed truth.
