# User preferences

Topic: user-preferences
Revision: 1
Status: Draft
Superseded by: None

## Goal

Give the user run-level preferences for output taste, source mix, and search bias. Preferences are separate from `--effort`. A preference never raises a spend ceiling, never changes a model, and never adds a vendor. A preference only changes prompts, brief defaults, or Exa filter arguments under the ceilings of the effort profile.

## Requirements

### R1 — Resolve each preference from flag, environment, and default
- **Status:** active
- **Behavior:** Each preference resolves once at run start. A CLI flag wins over its `EXACT_*` environment variable. The environment variable wins over the default. The names are `--lang`/`EXACT_LANGUAGE`, `--tone`/`EXACT_TONE`, `--length`/`EXACT_LENGTH`, `--structure`/`EXACT_STRUCTURE`, `--sources`/`EXACT_SOURCE_MIX`, `--include-domain`/`EXACT_INCLUDE_DOMAINS`, `--exclude-domain`/`EXACT_EXCLUDE_DOMAINS`, `--denylist`/`EXACT_DENYLIST`, `--since`/`EXACT_RECENCY`, `--prefer-primary`/`EXACT_PREFER_PRIMARY`, `--news`/`EXACT_NEWS_BIAS` and `--clarify`/`EXACT_CLARIFY_MODE`. The defaults are `language=auto`, `tone=neutral`, `length=standard`, `structure=report`, `source_mix=auto`, empty domain lists, `denylist=none`, `recency=any`, both booleans false, and `clarify_mode=auto`.

### R2 — Refuse an invalid preference before any model call
- **Status:** active
- **Behavior:** A value outside the enum of its preference exits `1` with a message on stderr. The message names the flag and the environment variable. The check runs before the live-key check, as the effort check does. A domain list longer than 20 entries is invalid. A domain entry that is not a host is invalid.

### R3 — Keep preferences orthogonal to effort
- **Status:** active
- **Behavior:** No preference changes a value of the effort profile, the hit count of a call, the model of a role, or the temperature. Every bound in `docs/spec.md` §1 holds for every combination of preferences.

### R4 — Apply output preferences in the writer prompt
- **Status:** active
- **Behavior:** `write_report` puts `language`, `tone`, `length` and `structure` into the `WRITE` prompt as fixed instruction text for each enum value. `length` changes the report size only, not the research. `structure` selects the outline: `report`, `memo` or `bullets`. Each structure keeps the citation rule and the `## Open questions` section. `language=auto` tells the writer to write in the language of the query. Another `language` value tells the writer to write in that language. Claims may be translated. Uncited content may not be added.

### R5 — Accept no free-form prompt text
- **Status:** active
- **Behavior:** The preference surface holds enums, booleans and host lists only. No flag or variable passes free text into a system prompt.

### R6 — Seed the brief from preferences
- **Status:** active
- **Behavior:** `generate_brief` seeds `ResearchBrief.intent` from a `source_mix` other than `auto`. With `source_mix=auto`, the current academic-signal rule sets `intent`. `generate_brief` seeds `ResearchBrief.audience` from `tone` when `tone` is not `neutral`. `generate_brief` adds one human-readable note to `ResearchBrief.exclusions` for each excluded domain set.

### R7 — Apply hard domain and date filters to general Exa search
- **Status:** active
- **Behavior:** The scout web search and the `exa_search` tool send the resolved include domains, the resolved exclude domains and the recency start date to Exa. `exa_people_search` and `exa_company_search` never send a domain or date filter. The `denylist` preset expands in code to a fixed host list, which joins the exclude list. `recency=any` sends no date filter.

### R8 — Report an empty filtered retrieval as a gap
- **Status:** active
- **Behavior:** A filtered search that returns no hits gives the same lane gap as an unfiltered empty search. The graph still finishes. The writer never fills the gap with uncited content.

### R9 — Apply search-bias preferences in prompts only
- **Status:** active
- **Behavior:** `prefer_primary` adds an instruction to the planner and research prompts to prefer official and primary sources. `news_bias` adds an instruction to the planner prompt to shape news queries. Neither preference changes a filter argument or a cap.

### R10 — Control clarification with `clarify_mode`
- **Status:** active
- **Behavior:** `clarify_mode=skip` forces `clarify_needed=false`, as `--skip-clarify` does. `clarify_mode=auto` keeps the current behavior. `clarify_mode=prefer` tells `decide_clarify` to ask when the scout gives a grounded angle. The scout-title grounding rule applies in every mode.

### R11 — Do not re-ask an axis that a preference settles
- **Status:** active
- **Behavior:** The `DECIDE_CLARIFY` prompt names each axis that a set preference answers and tells the model not to ask about it. `source_mix` other than `auto` settles web versus academic. `recency` other than `any` settles the time range. `tone` other than `neutral` settles the audience.

### R12 — Freeze preferences in the thread and refuse drift on resume
- **Status:** active
- **Behavior:** The run seed writes the resolved preferences into `ExactState` as one frozen value. A resume with `--thread-id` uses the checkpointed preferences. A resume whose resolved preferences differ from the checkpoint exits `1` with a mismatch message on stderr.

### R13 — Keep the contract documents current
- **Status:** active
- **Behavior:** The change that adds a preference flag or an Exa filter also updates `docs/spec.md` and `docs/architecture.md`.

### R14 — Test preferences without the network
- **Status:** active
- **Behavior:** Tests use `tests/fakes.py`. The fake Exa client records the filter arguments of each search, and tests assert them. No test calls a live vendor.

## Out of scope

- Raising a spend ceiling, or any knob that changes a cap of the effort profile.
- Model changes, temperature changes, and a new retrieval vendor.
- A free-form system prompt, a style prompt, and composite `--profile` presets.
- A JSON or TOML preference file, and global preferences stored outside a thread.
- An HTTP API, a web UI, Firecrawl, PDF or paywall text, and an MCP product.
- Domain or date filters on `exa_people_search` and `exa_company_search`.
- A source-language filter on Exa.
- A change to citation ids, `audit_citations`, snippet caps, or tool-text caps.

## Decisions

## Repository evidence

- E1: repo:docs/plans/user-preferences.md
- E2: repo:src/exact/models.py::ResearchBrief
- E3: repo:src/exact/nodes/plan.py#L25
- E4: repo:src/exact/nodes/scout.py#L52
- E5: repo:docs/spec.md#L213
- E6: repo:src/exact/tools/exa.py#L286
- E7: repo:src/exact/tools/exa.py#L314
- E8: repo:src/exact/prompts.py#L11
- E9: repo:src/exact/prompts.py#L28
- E10: repo:src/exact/prompts.py#L91
- E11: repo:src/exact/nodes/write.py#L63
- E12: repo:src/exact/cli.py::_resolve_settings
- E13: repo:src/exact/cli.py::_guard_effort
- E14: repo:src/exact/cli.py::_seed
- E15: repo:src/exact/nodes/clarify.py#L124
- E16: repo:src/exact/config.py::Settings
- E17: repo:docs/spec.md#L287
- E18: repo:docs/spec.md#L206
- E19: repo:docs/spec.md#L291
- E20: repo:src/exact/nodes/research.py::_gap_kind
- E21: repo:src/exact/nodes/research.py::_Tools
- E22: repo:tests/fakes.py::FakeExa
- E23: repo:src/exact/intent.py::academic_signal
- E24: repo:src/exact/nodes/brief.py::_normalize
- E25: repo:docs/spec.md#L211
- E26: url:https://docs.exa.ai/reference/search
- E27: url:https://github.com/exa-labs/exa-py/blob/master/exa_py/api.py

## Acceptance criteria

- **R1:** For each preference, a test sets the flag and the variable to different values and the flag value wins. With neither set, the default applies.
- **R2:** An invalid enum value, a 21-entry domain list, or a non-host entry exits `1` with the flag and variable names on stderr, before the live-key check.
- **R3:** For every preference, the `effort=` echo line and the per-call hit count equal the values of a run without preferences.
- **R4:** For each enum value of `language`, `tone`, `length` and `structure`, the captured `WRITE` prompt holds the fixed text of that value, the citation rule and `## Open questions`.
- **R5:** The CLI parser and `Settings` hold no string field that reaches a prompt other than the enums of R1.
- **R6:** With `--sources academic`, the brief `intent` is `academic` for a query with no academic signal. With `--sources auto`, the current rule decides `intent`.
- **R7:** The fake Exa client records the include domains, the exclude domains with the preset hosts, and the start date on the scout and `exa_search` calls. It records none of them on people and company calls.
- **R8:** A filtered search with no hits gives the lane gap in `Finding.gaps` and in `uncovered`, and the graph reaches END.
- **R9:** The captured planner prompt holds the primary-source text only with `prefer_primary`, and the news text only with `news_bias`. The Exa arguments do not change.
- **R10:** `--clarify skip` gives `clarify_needed=false` with no router call. `--clarify prefer` puts the prefer text into the `DECIDE_CLARIFY` prompt. An ungrounded question still skips.
- **R11:** With `--sources academic`, the captured `DECIDE_CLARIFY` prompt tells the model not to ask web versus academic.
- **R12:** A resume with a different preference exits `1` with a mismatch message. A resume with the same preferences continues.
- **R13:** `docs/spec.md` and `docs/architecture.md` describe every flag and filter of this specification.
- **R14:** `make check` passes, and no test opens a network connection.

## Open questions

### Q1 — What does `source_mix` change now that no tool reads `brief.intent`
- **Affects:** R6
- **Evidence:** E5

### Q2 — Does the publication lane get the domain and date filters
- **Affects:** R7
- **Evidence:** E7

### Q3 — May one request send include domains and exclude domains together
- **Affects:** R7, R2
- **Evidence:** E27

### Q4 — How does `recency` become a date, and is that date frozen on resume
- **Affects:** R7, R12
- **Evidence:** E26

### Q5 — Is `--audience` free text part of the surface
- **Affects:** R5, R6
- **Evidence:** E1

### Q6 — Which preferences are thread-scoped and which are process-scoped
- **Affects:** R12
- **Evidence:** E19

### Q7 — Does a preference flag reach an injected `Runtime`
- **Affects:** R1
- **Evidence:** E17

### Q8 — How do `--clarify` and `--skip-clarify` combine
- **Affects:** R10
- **Evidence:** E15

### Q9 — Does a gap name the filter that emptied retrieval
- **Affects:** R8
- **Evidence:** E20

### Q10 — What is the environment format of a domain list
- **Affects:** R1, R2
- **Evidence:** E16

### Q11 — Does `language` also set the language of clarify questions
- **Affects:** R4
- **Evidence:** E8
