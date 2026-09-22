# User preferences

Topic: user-preferences
Revision: 3
Status: Ready
Superseded by: None

## Goal

Give the user run-level preferences for output taste, source mix, and search bias. Preferences are separate from `--effort`. A preference never raises a spend ceiling, never changes a model, and never adds a vendor. A preference changes prompts, brief defaults, Exa filter arguments, the lanes that a run searches, and clarify routing. It works under the ceilings of the effort profile.

## Requirements

### R1 — Resolve each preference from flag, environment, and default
- **Status:** active
- **Behavior:** Each preference resolves once at run start. A CLI flag wins over its environment variable. The environment variable wins over the default. D49 gives each flag, variable and `Settings` field. The value lists are in D1 and D3. The defaults are `language=auto`, `tone=neutral`, `length=standard`, `structure=report`, `source_mix=auto`, empty domain lists, `denylist=none`, `recency=any`, both booleans false, and `clarify_mode=auto`. `--prefer-primary` and `--news` each have a `--no-` form. `--include-domain` and `--exclude-domain` repeat. One use of a domain flag replaces the whole environment list. A domain environment variable is a comma-separated host list. No flag clears a domain list that the environment sets. `--skip-clarify` is a second name for `--clarify skip`. Each preference flag also overrides the settings of an injected `Runtime`, and the result passes the R2 checks. `--effort` stays the only flag that does not reach an injected `Runtime`.

### R2 — Refuse an invalid preference before any model call
- **Status:** active
- **Behavior:** An invalid preference exits `1` with one message on stderr. The check runs before the live-key check, as the effort check does. `Settings` validators hold the preference checks, so an invalid `Settings` fails wherever it is built. The CLI holds only the `--skip-clarify` conflict check. Only the first failure is reported: effort first, then the preferences in D49 order, then the trace and verbose booleans. An enum value must match exactly, in lowercase, with no spaces. A domain entry must be a strict ASCII host (D28, D74). A user domain list holds at most 20 hosts after duplicates are removed. Include domains together with exclude domains or a `denylist` preset are invalid. `--skip-clarify` together with `--clarify auto` or `--clarify prefer` is invalid. D35 and D55 give the messages.

### R3 — Keep preferences orthogonal to effort
- **Status:** active
- **Behavior:** No preference changes a value of the effort profile, the requested hit count of a search, the model of a role, or the temperature. Every bound in `docs/spec.md` §1 holds for every combination of preferences.

### R4 — Apply output preferences in the writer prompt
- **Status:** active
- **Behavior:** `write_report` puts one fixed instruction for each of `language`, `tone`, `length` and `structure` into the `WRITE` prompt. Every value adds its instruction, the defaults included, except `tone=neutral`, which adds none. D40, D41 and D42 give the meaning of each value. Code holds the exact strings. Every structure keeps the citation rule and ends with the literal English heading `## Open questions`. Other headings, the `memo` headings included, follow `language`. Under `bullets`, the `## Open questions` bullets need no citation. `language=auto` tells the writer to use the language of `initial_query`. `en`, `es` and `pt` name English, Spanish and Portuguese. Claims may be translated. Uncited content may not be added. No check compares `length=long` with `EXACT_MAX_TOKENS_WRITE`.

### R5 — Accept no free-form prompt text
- **Status:** active
- **Behavior:** The preference surface holds enums, booleans and host lists only. No flag or variable passes free text into a prompt. Validated host strings may reach a prompt through the brief notes of R6.

### R6 — Seed the brief from preferences
- **Status:** active
- **Behavior:** When `source_mix` is `web`, `academic` or `mixed`, `generate_brief` sets `ResearchBrief.intent` to that value after `_normalize`. No signal, model output or clarify answer changes it. With `source_mix=auto`, the current academic-signal rule sets `intent`. When `tone` is not `neutral`, `generate_brief` sets `ResearchBrief.audience` after the model: `academic` gives `academic researchers`, `executive` gives `executives`, and `plain` gives `general public`. `generate_brief` appends notes to `ResearchBrief.exclusions`, after the model entries, with duplicates removed. It appends one note for the user exclude list, one for the `denylist` preset, and one restriction note for the include list. Each note names its hosts in stored order. Duplicates are exact-string duplicates. An empty list or `denylist=none` gives no note. The forced `intent`, the `audience` and the notes apply on the model path and on the fallback path.

### R7 — Apply hard domain and date filters to Exa search
- **Status:** active
- **Behavior:** Four searches send the filters: the scout web leg, the scout publication leg, `exa_search` and `exa_publication_search`. They send `include_domains`, `exclude_domains` and `start_published_date`. The raw publication request body uses `includeDomains`, `excludeDomains` and `startPublishedDate`. The degraded publication path sends the snake-case names. `exa_people_search` and `exa_company_search` never send a filter. The exclude list is the user list plus the `denylist` preset hosts, with duplicates removed. An empty list and `recency=any` leave the key out of the request.

### R8 — Name the filters in a filtered lane gap
- **Status:** active
- **Behavior:** Each lane gap of a filtered lane ends with a suffix. A lane is filtered when it is `web` or `publication` and `prefs` holds at least one active filter. A search attempt is not necessary. The suffix names the active filters in the fixed order `include`, `exclude`, `recency`, for example `lane web: no sources (filters: exclude, recency)`. A `denylist` preset counts as `exclude`. The suffix applies to `no sources`, `no new sources` and `retrieval failed`. An unfiltered lane keeps its current gap text. The graph still finishes, and the writer never fills a gap with uncited content.

### R9 — Apply search-bias preferences in prompts only
- **Status:** active
- **Behavior:** `prefer_primary` adds one instruction to `PLAN` and to `RESEARCH_SYS`, on every lane. The instruction prefers official and primary sources over secondary roundups. `PRUNE` does not change. `news_bias` adds one line to `PLAN` that shapes web-lane queries as news queries with event, outlet and date cues. The `news_bias` text is the same with or without `recency`. Neither preference changes a filter argument or a cap.

### R10 — Control clarification with `clarify_mode`
- **Status:** active
- **Behavior:** `decide_clarify` reads `prefs.clarify_mode`. The `skip_clarify` state channel is removed. `clarify_mode=skip` forces `clarify_needed=false` with no router call, as `--skip-clarify` does today. `clarify_mode=auto` keeps the current behavior. `clarify_mode=prefer` replaces the `DECIDE_CLARIFY` sentence "Prefer skipping if the query is specific enough" with a sentence that prefers to ask. The scout-title grounding rule, the generic question on an empty scout, and the turn cap apply in every mode.

### R11 — Do not re-ask an axis that a preference settles
- **Status:** active
- **Behavior:** The `DECIDE_CLARIFY` prompt names each axis that a set preference settles and tells the model not to ask about it. `source_mix` other than `auto` settles web versus academic. `recency` other than `any` settles the time range. `tone` other than `neutral` settles the audience. The entity axis stays open to a question. The rule applies in every `clarify_mode`.

### R12 — Freeze preferences in the thread and refuse drift on resume
- **Status:** active
- **Behavior:** The run seed writes one `prefs` value into `ExactState` (D50). Every preference is thread-scoped. Scout, clarify, brief, planner, workers and writer read `prefs` from state, never from `Settings`. Workers get `prefs` in the `Send` payload. A clarify answer never changes `prefs`. A resume resolves the preferences from flags, environment and defaults, and compares them with the checkpoint (D21). A difference exits `1` with one message on stderr that names each differing preference with its stored and resolved values (D73). A resume with `--skip-clarify` of a thread seeded with `clarify_mode=auto` is a difference. Startup runs the effort guard, the preference guard, the `effort=` echo, the `prefs` echo and `run_start`, in that order. The finished-thread check runs later. A preference mismatch writes no trace line. A checkpoint with no `prefs` reads as all defaults. When that checkpoint holds `skip_clarify=true`, it reads as `clarify_mode=skip`.

### R13 — Keep the contract documents current
- **Status:** active
- **Behavior:** The change that adds a preference flag or an Exa filter also updates `docs/spec.md` and `docs/architecture.md`. `docs/spec.md` §5 states that Exa drops pages with no known publish date when `recency` is set, and lists the preset hosts of D31 and D32. `docs/spec.md` §8 states that `length=long` can end early under a write cap below 8192 tokens.

### R14 — Test preferences without the network
- **Status:** active
- **Behavior:** Tests use `tests/fakes.py`. The fake Exa client records `include_domains`, `exclude_domains` and `start_published_date` for each search, and tests assert them. No test calls a live vendor.

### R15 — Gate lanes by `source_mix`
- **Status:** active
- **Behavior:** With `source_mix=auto`, the scout publication leg runs on an academic signal, as today. With `web`, it never runs. With `academic` or `mixed`, it always runs. The scout web leg always runs. In `plan_topics`, `source_mix=web` changes each `publication` topic to `web`. `source_mix=academic` changes each `web` topic to `publication`. `people` and `company` topics do not change. `auto` and `mixed` change no topic. The change applies to planner topics and fallback topics. It runs after an unknown focus drops to `web` and before the topic dedup. The unknown-focus `errors` line names the final lane. A lane change writes no other `errors` line. When a changed topic and another topic have the same query and lane, the first in planner order survives. The `PLAN` prompt does not change for `source_mix`.

### R16 — Echo the resolved preferences
- **Status:** active
- **Behavior:** The CLI prints one line directly after the `effort=` echo line. With every preference at its default, the line is `prefs=default`. Otherwise it is `prefs` followed by one `name=value` pair for each preference that is not at its default, for example `prefs tone=plain exclude_domains=a.com,b.com recency=month`. Names are the D50 names, in D49 order. A list joins its hosts with commas, in stored order. The derived keys are not shown. On a resume the values come from the checkpoint. The trace `run_start.settings` payload of `docs/spec.md` §8b gets a `prefs` key that holds the full `prefs` dict, the derived keys included. The trace `tool` line does not change.

### R17 — Write clarify questions in the preferred language
- **Status:** active
- **Behavior:** When `language` is not `auto`, the `DECIDE_CLARIFY` prompt tells the model to ask in that language. Scout titles are quoted unchanged, so the grounding check still finds them. With `language=auto`, the clarify prompt does not change.

### R18 — Record a filtered scout leg that returns nothing
- **Status:** active
- **Behavior:** When a filtered scout leg returns with no hits, the scout appends one `errors` line: `{label} scout: no hits (filters: <names>)`. The label is `exa` or `exa publication`, as in the current scout failure line. The names follow the order of R8. A filtered leg that raises keeps only its `{label} scout failed: <exc>` line. The clarify behavior does not change.

## Out of scope

- Raising a spend ceiling, or any knob that changes a cap of the effort profile.
- Model changes, temperature changes, and a new retrieval vendor.
- A free-form system prompt, a style prompt, an `--audience` text, and composite `--profile` presets.
- A JSON or TOML preference file, and global preferences stored outside a thread.
- An HTTP API, a web UI, Firecrawl, PDF or paywall text, and an MCP product.
- Domain or date filters on `exa_people_search` and `exa_company_search`.
- A source-language filter on Exa, and output languages other than `en`, `es` and `pt`.
- A change to citation ids, `audit_citations`, snippet caps, or tool-text caps.
- A CLI form that clears a domain list that the environment sets.
- Filter names in the trace `tool` line.
- Lane instructions in `PLAN` for `source_mix`.

## Decisions

### D1 — The enum values are the plan lists
- **Status:** active
- **Question:** What values do `tone`, `length`, `source_mix`, `denylist` and `recency` accept?
- **Answer:** The plan §3 lists, word for word. `tone`: `neutral`, `academic`, `executive`, `plain`. `length`: `short`, `standard`, `long`. `source_mix`: `auto`, `web`, `academic`, `mixed`. `denylist`: `none`, `social`, `seo`. `recency`: `any`, `year`, `month`, `week`. `structure`: `report`, `memo`, `bullets`. `clarify_mode`: `auto`, `skip`, `prefer`.
- **Impact:** The `Settings` literal types, the R2 checks and the R4 prompt text.
- **Evidence:** E1

### D2 — `language` is a closed list plus `auto`
- **Status:** active
- **Question:** Is `language` a closed enum or an open BCP-47 code?
- **Answer:** A closed list of codes plus `auto`. Each code maps to a fixed language name in the prompt.
- **Impact:** R2 validation and R5. No user string reaches the prompt. This overrides plan §3.1.
- **Evidence:** person-decision

### D3 — The language codes are `en`, `es` and `pt`
- **Status:** active
- **Question:** Which codes does the `language` list hold besides `auto`?
- **Answer:** `en`, `es` and `pt`.
- **Impact:** The `language` literal type and the R4 language names.
- **Evidence:** person-decision

### D4 — Preferences may change lanes and clarify routing
- **Status:** active
- **Question:** Does the Goal limit preferences to prompts, brief defaults and filter arguments?
- **Answer:** No. A preference may also change clarify routing and the lanes that a run searches. It still never raises a cap, changes a model, or adds a vendor.
- **Impact:** The Goal, R10 and R15.
- **Evidence:** E15

### D5 — A set `source_mix` forces `brief.intent`
- **Status:** active
- **Question:** With `source_mix` other than `auto`, is `brief.intent` forced or only a seed?
- **Answer:** Forced. It is set after `_normalize`, and no signal, model output or clarify answer changes it.
- **Impact:** R6 and the order of steps in `generate_brief`.
- **Evidence:** E24

### D6 — `source_mix` gates the scout publication leg
- **Status:** active
- **Question:** Does `source_mix` gate the scout publication leg?
- **Answer:** Yes. `auto` keeps the academic signal. `web` never runs the leg. `academic` and `mixed` always run it.
- **Impact:** R15 and the scout inputs.
- **Evidence:** E4

### D7 — `source_mix` is a hard filter on planner lanes
- **Status:** active
- **Question:** Does `source_mix` limit the lanes of the planner?
- **Answer:** Yes, as a hard filter on topic focus. `web` changes publication topics to web. `academic` changes web topics to publication. People and company topics do not change. `auto` and `mixed` change nothing.
- **Impact:** R15 and `plan_topics`.
- **Evidence:** E5

### D8 — The publication lane gets every filter
- **Status:** active
- **Question:** Do `exa_publication_search` and the scout publication leg get the domain and date filters?
- **Answer:** Yes. Both get all filters, in the raw request body and in the degraded path.
- **Impact:** R7, `ExactClient` publication request body, and the fake client.
- **Evidence:** E7

### D9 — Include and exclude filters together are refused
- **Status:** active
- **Question:** What does one request send when both include and exclude lists are set?
- **Answer:** Nothing. The combination exits `1` at startup. A `denylist` preset counts as an exclude list.
- **Impact:** R2. No request sends both keys.
- **Evidence:** E27

### D10 — `recency` is a rolling window in UTC days
- **Status:** active
- **Question:** How does `recency` become `start_published_date`?
- **Answer:** `year` is 365 days, `month` is 30 days and `week` is 7 days before the instant that the first run seeds the thread, in UTC. The value is a date, `YYYY-MM-DD`.
- **Impact:** R7 and the date that `prefs` stores.
- **Evidence:** E26

### D11 — The start date is computed once and frozen
- **Status:** active
- **Question:** When is the recency start date computed?
- **Answer:** Once, when the thread is seeded. It is stored in `prefs` and reused on every resume.
- **Impact:** R12 and D50.
- **Evidence:** E14

### D12 — A filtered lane gap names its filters
- **Status:** superseded by D59
- **Question:** Must a lane gap say that filters were active?
- **Answer:** Yes. It gets a suffix such as `(filters: include, recency)`, only on a lane that sent at least one filter.
- **Impact:** R8 and `_gap_kind`.
- **Evidence:** E20

### D13 — Every gap kind gets the filter suffix
- **Status:** active
- **Question:** Which gap kinds get the suffix, and what are its names?
- **Answer:** All three kinds. The names are `include`, `exclude` and `recency`, in that order. A `denylist` preset counts as `exclude`.
- **Impact:** R8.
- **Evidence:** E20

### D14 — A filtered empty scout leg appends an error
- **Status:** active
- **Question:** What happens when filters empty a scout leg?
- **Answer:** The clarify behavior does not change. The scout appends one `errors` line that names the leg and the active filters.
- **Impact:** R18.
- **Evidence:** E33

### D15 — Undated pages are dropped and documented
- **Status:** active
- **Question:** Exa drops pages with no known publish date when a start date is set. Is that accepted?
- **Answer:** Yes. `docs/spec.md` §5 states it.
- **Impact:** R13.
- **Evidence:** E27

### D16 — There is no `--audience` text
- **Status:** active
- **Question:** Is `--audience` free text part of the surface?
- **Answer:** No. Only `tone` sets `brief.audience`.
- **Impact:** R5 and R6. This overrides plan §3.1 rule 3.
- **Evidence:** person-decision

### D17 — `tone` maps to a fixed audience that replaces the model value
- **Status:** active
- **Question:** How does `tone` map to `brief.audience`?
- **Answer:** `academic` gives `academic researchers`, `executive` gives `executives`, and `plain` gives `general public`. The value replaces the model value. `neutral` keeps the model value.
- **Impact:** R6.
- **Evidence:** E2

### D18 — Brief notes name their hosts
- **Status:** active
- **Question:** Which brief notes do the domain filters produce, and may hosts reach prompts?
- **Answer:** One note for the user exclude list, one for the preset, and one restriction note for the include list. Notes follow the model entries, with duplicates removed. Validated hosts may reach prompts.
- **Impact:** R5 and R6.
- **Evidence:** E11

### D19 — Every preference is thread-scoped
- **Status:** active
- **Question:** Which preferences are thread-scoped?
- **Answer:** All of them. Nodes read `prefs` from state, and workers get it in the `Send` payload.
- **Impact:** R12 and the worker payload.
- **Evidence:** E19

### D20 — A resume with different resolved preferences is refused
- **Status:** active
- **Question:** A resume passes no preference flags, but the thread has non-default preferences. What happens?
- **Answer:** Absent flags resolve to the environment or the default. Any difference from the checkpoint exits `1`.
- **Impact:** R12.
- **Evidence:** E13

### D21 — The resume check compares normalized values
- **Status:** active
- **Question:** What does the resume check compare, and how does it read a checkpoint with no preferences?
- **Answer:** Enums by value, domain lists as sorted sets, `denylist` by preset name, and `recency` by enum, not by date. A checkpoint with no `prefs` reads as all defaults, except the `skip_clarify` case of D58.
- **Impact:** R12.
- **Evidence:** E13

### D22 — The effort check runs before the preference check
- **Status:** active
- **Question:** What is the order of the resume refusals?
- **Answer:** Effort mismatch, then preference mismatch, then finished thread. The preference message names each differing preference with its stored and resolved values.
- **Impact:** R12 and the CLI startup order.
- **Evidence:** E13

### D23 — A clarify answer never changes a preference
- **Status:** active
- **Question:** Can a clarify answer change a frozen preference?
- **Answer:** No. A clarify answer refines only the brief.
- **Impact:** R12.
- **Evidence:** E1

### D24 — CLI flags do not reach an injected `Runtime`
- **Status:** superseded by D52
- **Question:** Do preference flags reach an injected `Runtime`?
- **Answer:** No. The settings of the injected `Runtime` supply the preferences, as for `--effort`.
- **Impact:** R1 and the test setup.
- **Evidence:** E17

### D25 — `--skip-clarify` is a second name for `--clarify skip`
- **Status:** active
- **Question:** How do `--clarify` and `--skip-clarify` combine?
- **Answer:** `--skip-clarify` means `--clarify skip`. With `--clarify auto` or `--clarify prefer`, it exits `1`. Both feed `clarify_mode` and the resume check.
- **Impact:** R1, R2, R10 and R12.
- **Evidence:** E28

### D26 — A domain environment variable is comma-separated
- **Status:** active
- **Question:** What format do the domain environment variables use?
- **Answer:** A comma-separated list. Spaces around entries are removed, and empty entries are dropped. A parse failure gives the R2 message, not a traceback.
- **Impact:** R1, R2 and the `Settings` field type.
- **Evidence:** E12

### D27 — Both domain flags repeat and replace the environment list
- **Status:** active
- **Question:** Do the domain flags repeat, and do they merge with the environment list?
- **Answer:** Both flags repeat. Any use of a flag replaces the whole environment list for that preference.
- **Impact:** R1.
- **Evidence:** E1

### D28 — A domain entry is a strict host
- **Status:** active
- **Question:** What is a valid domain entry?
- **Answer:** Lowercase and strip spaces, then refuse a scheme, path, port, wildcard, IP address or single-label name. Duplicates are removed.
- **Impact:** R2.
- **Evidence:** E26

### D29 — The 20-host limit counts each user list alone
- **Status:** active
- **Question:** What does the 20-entry limit count?
- **Answer:** Each user list after duplicates are removed. Preset hosts do not count.
- **Impact:** R2.
- **Evidence:** E1

### D30 — The specification lists the preset hosts
- **Status:** active
- **Question:** Who owns the host lists of the `denylist` presets?
- **Answer:** The specification. D31 and D32 list them.
- **Impact:** R7 and R13.
- **Evidence:** person-decision

### D31 — The `social` preset holds eight hosts
- **Status:** active
- **Question:** Which hosts does the `social` preset hold?
- **Answer:** `facebook.com`, `instagram.com`, `tiktok.com`, `x.com`, `twitter.com`, `reddit.com`, `pinterest.com`, `linkedin.com`.
- **Impact:** R7.
- **Evidence:** person-decision

### D32 — The `seo` preset holds eight hosts
- **Status:** active
- **Question:** Which hosts does the `seo` preset hold?
- **Answer:** `quora.com`, `wikihow.com`, `ehow.com`, `answers.com`, `reference.com`, `medium.com`, `hubpages.com`, `ezinearticles.com`.
- **Impact:** R7.
- **Evidence:** person-decision

### D33 — Enum values match exactly
- **Status:** active
- **Question:** Are enum values case-sensitive and space-sensitive?
- **Answer:** Yes. Only the exact lowercase value is valid, as for effort.
- **Impact:** R2.
- **Evidence:** E16

### D34 — Boolean preferences have a `--no-` flag
- **Status:** active
- **Question:** How can a flag turn off a boolean that the environment sets?
- **Answer:** `--prefer-primary` and `--no-prefer-primary`, `--news` and `--no-news`.
- **Impact:** R1.
- **Evidence:** E43

### D35 — The first invalid preference is reported in the effort style
- **Status:** active
- **Question:** What does an invalid preference report?
- **Answer:** The first failure only. An enum: `<pref> must be one of <values>; got <X> (--<flag> or EXACT_<ENV>)`. A boolean: `<pref> must be a boolean such as 0 or 1; got <X> (--<flag> or EXACT_<ENV>)`. A host or a count failure names the entry or the count.
- **Impact:** R2.
- **Evidence:** E12

### D36 — `language` applies to the writer and to clarify
- **Status:** active
- **Question:** Where does `language` apply?
- **Answer:** In `WRITE` always, and in `DECIDE_CLARIFY` when it is not `auto`. Scout titles stay unchanged in the question.
- **Impact:** R4 and R17.
- **Evidence:** E1

### D37 — The `## Open questions` heading stays in English
- **Status:** active
- **Question:** Is the `## Open questions` heading translated?
- **Answer:** No. It stays literal in every language.
- **Impact:** R4.
- **Evidence:** E10

### D38 — `language=auto` follows `initial_query`
- **Status:** active
- **Question:** With `language=auto`, what decides the language?
- **Answer:** The language of `initial_query` only.
- **Impact:** R4.
- **Evidence:** E14

### D39 — The specification gives meanings and code gives strings
- **Status:** active
- **Question:** Who fixes the instruction text for each output value?
- **Answer:** The specification states what each value means. Code holds the exact strings. Tests assert that the string of each value reaches `WRITE`.
- **Impact:** R4.
- **Evidence:** E10

### D40 — `length` values are word ranges
- **Status:** active
- **Question:** What do the `length` values mean?
- **Answer:** `short` is 300 to 500 words. `standard` is 800 to 1500 words. `long` is 2000 to 3500 words, which fits the default write cap of 8192 tokens.
- **Impact:** R4.
- **Evidence:** E32

### D41 — Each structure has a fixed outline
- **Status:** active
- **Question:** What does each `structure` value mean?
- **Answer:** `report` is the current cohesive report with sections. `memo` has Summary, Findings and Implications sections, in prose. `bullets` has headed sections whose bodies are bullet lists, with one cited claim for each bullet.
- **Impact:** R4.
- **Evidence:** E10

### D42 — Each tone has a fixed meaning
- **Status:** active
- **Question:** What does each `tone` value mean in `WRITE`?
- **Answer:** `neutral` adds no tone line. `academic` is formal, with precise terms and hedged claims. `executive` leads with conclusions and decisions, with little jargon. `plain` uses short sentences and everyday words, and defines terms.
- **Impact:** R4.
- **Evidence:** E10

### D43 — `prefer_primary` changes `PLAN` and `RESEARCH_SYS`
- **Status:** active
- **Question:** Which prompts get the `prefer_primary` text, and on which lanes?
- **Answer:** `PLAN` and `RESEARCH_SYS`, on every lane. `PRUNE` does not change.
- **Impact:** R9.
- **Evidence:** E34

### D44 — `news_bias` adds one web-lane line to `PLAN`
- **Status:** active
- **Question:** What does `news_bias` add, and does it depend on `recency`?
- **Answer:** One `PLAN` line that shapes web-lane queries as news queries. The line is the same with or without `recency`.
- **Impact:** R9.
- **Evidence:** E30

### D45 — `prefer` replaces the skip-bias line
- **Status:** active
- **Question:** Under `clarify_mode=prefer`, does the prefer text replace the skip-bias line?
- **Answer:** Yes. The grounding rule, the empty-scout question and the turn cap do not change.
- **Impact:** R10.
- **Evidence:** E29

### D46 — Three preferences settle three clarify axes
- **Status:** active
- **Question:** Which clarify axes do preferences settle?
- **Answer:** `source_mix` settles web versus academic, `recency` settles the time range, and `tone` settles the audience. The entity axis stays open. The rule applies in `prefer` mode too.
- **Impact:** R11.
- **Evidence:** E8

### D47 — The CLI echoes the preferences
- **Status:** active
- **Question:** Are the resolved preferences shown to the user?
- **Answer:** Yes. One `prefs` line follows the `effort=` line. The trace `run_start.settings` payload gets a `prefs` key.
- **Impact:** R16.
- **Evidence:** E31

### D48 — An empty filter leaves its key out
- **Status:** active
- **Question:** Is an empty filter key left out of the request or sent empty?
- **Answer:** Left out. An unfiltered call sends the same arguments as today.
- **Impact:** R7 and R14.
- **Evidence:** E6

### D49 — The specification fixes the field and argument names
- **Status:** active
- **Question:** Does the specification fix the `Settings` field names and the Exa argument names?
- **Answer:** Yes. The `Settings` fields are `exact_language`, `exact_tone`, `exact_length`, `exact_structure`, `exact_source_mix`, `exact_include_domains`, `exact_exclude_domains`, `exact_denylist`, `exact_recency`, `exact_prefer_primary`, `exact_news_bias` and `exact_clarify_mode`. The variables are the same names in upper case. The flags are `--lang`, `--tone`, `--length`, `--structure`, `--sources`, `--include-domain`, `--exclude-domain`, `--denylist`, `--since`, `--prefer-primary`, `--news` and `--clarify`. The Exa arguments are in R7.
- **Impact:** R1, R7 and R14.
- **Evidence:** E16

### D50 — `prefs` holds resolved and derived values
- **Status:** active
- **Question:** What is the frozen state value called, and what does it hold?
- **Answer:** `prefs`, a dict. It holds each resolved value under its `Settings` name without `exact_`. It also holds `start_published_date`, the frozen date or `null`, and `effective_exclude_domains`, the user and preset hosts. Readers never compute them again.
- **Impact:** R12 and every node that reads `prefs`.
- **Evidence:** E14

### D51 — R3 counts the requested hits
- **Status:** active
- **Question:** Does R3 mean the requested hit count or the returned count?
- **Answer:** The requested count. Every search requests the resolved `max_hits`. Filters may return fewer.
- **Impact:** R3.
- **Evidence:** E6

### D52 — Every preference flag reaches an injected `Runtime`
- **Status:** active
- **Question:** Do preference flags, `--skip-clarify` included, reach an injected `Runtime`?
- **Answer:** Yes. Each preference flag overrides the settings of an injected `Runtime`, as the trace flags do. `--effort` stays the only flag that does not.
- **Impact:** R1 and the CLI tests that pass `--skip-clarify` with an injected `Runtime`.
- **Evidence:** E38

### D53 — `Settings` validators hold the preference checks
- **Status:** active
- **Question:** Do the R2 checks run in `Settings` or on the CLI path only?
- **Answer:** In `Settings` validators, so an invalid `Settings` fails wherever it is built. The `--skip-clarify` conflict stays a CLI check.
- **Impact:** R2.
- **Evidence:** E16

### D54 — Effort failures come first, trace booleans last
- **Status:** active
- **Question:** When several knobs are invalid, which failure is reported?
- **Answer:** Effort first, then the preferences in D49 order, then the trace and verbose booleans.
- **Impact:** R2.
- **Evidence:** E38

### D55 — The combination refusals have fixed messages
- **Status:** active
- **Question:** What do the combination refusals print?
- **Answer:** `include domains cannot combine with exclude domains or a denylist (--include-domain, --exclude-domain, --denylist)` and `--skip-clarify cannot combine with --clarify <value>`. The boolean message keeps the D35 form with the flag names.
- **Impact:** R2.
- **Evidence:** E12

### D56 — Both resume guards run before both echo lines
- **Status:** active
- **Question:** Where does the preference guard run at startup, and does a mismatch write a trace line?
- **Answer:** Effort guard, preference guard, `effort=` echo, `prefs` echo, then `run_start`. A mismatch writes no trace line.
- **Impact:** R12 and R16.
- **Evidence:** E19

### D57 — No flag clears an environment domain list
- **Status:** active
- **Question:** How does the CLI clear a domain list that the environment sets?
- **Answer:** It does not. The user edits the environment. `--denylist none` clears a preset.
- **Impact:** R1.
- **Evidence:** E1

### D58 — `prefs.clarify_mode` replaces the `skip_clarify` channel
- **Status:** active
- **Question:** What happens to the `skip_clarify` state channel?
- **Answer:** It is removed. The seed writes `prefs` only. A checkpoint with `skip_clarify=true` and no `prefs` reads as `clarify_mode=skip`.
- **Impact:** R10, R12 and the test seeds.
- **Evidence:** E15

### D59 — A lane is filtered by configuration, not by attempts
- **Status:** active
- **Question:** When does a lane gap get the filter suffix?
- **Answer:** A filtered lane gap gets a suffix such as `(filters: include, recency)`. A lane is filtered when it is `web` or `publication` and `prefs` holds an active filter, with or without a search attempt.
- **Impact:** R8.
- **Evidence:** E20

### D60 — The scout records only a filtered leg with zero hits
- **Status:** active
- **Question:** What is the R18 line, and does a raising leg get it?
- **Answer:** `{label} scout: no hits (filters: <names>)`, with the label `exa` or `exa publication`. A leg that raises keeps only its failure line.
- **Impact:** R18.
- **Evidence:** E42

### D61 — The unknown-focus line names the final lane
- **Status:** active
- **Question:** After a lane change, what does the unknown-focus `errors` line say?
- **Answer:** The lane change runs after the drop to `web`, and the line names the final lane.
- **Impact:** R15.
- **Evidence:** E39

### D62 — A lane change writes no `errors` line
- **Status:** active
- **Question:** Does a lane change by `source_mix` write an `errors` line?
- **Answer:** No, also when the changed topic is then removed as a duplicate.
- **Impact:** R15.
- **Evidence:** E37

### D63 — `source_mix` does not change the `PLAN` prompt
- **Status:** active
- **Question:** Does the `PLAN` prompt name the allowed lanes?
- **Answer:** No. Only the lane change applies.
- **Impact:** R15.
- **Evidence:** E30

### D64 — The first topic in planner order survives a collision
- **Status:** active
- **Question:** A changed topic and an unchanged topic have the same query and lane. Which survives?
- **Answer:** The first in planner order, as the current dedup does.
- **Impact:** R15.
- **Evidence:** E36

### D65 — The trace `tool` line does not change
- **Status:** active
- **Question:** Do the filters appear in the trace `tool` line?
- **Answer:** No.
- **Impact:** R16.
- **Evidence:** E40

### D66 — `run_start.settings.prefs` holds the full `prefs` dict
- **Status:** active
- **Question:** What does `run_start.settings.prefs` hold?
- **Answer:** The full `prefs` dict, the derived keys included.
- **Impact:** R16 and `docs/spec.md` §8b.
- **Evidence:** E41

### D67 — The echo line uses state names in table order
- **Status:** active
- **Question:** What does the `prefs` echo line print?
- **Answer:** `prefs=default`, or `prefs` and one `name=value` pair for each non-default preference. Names are D50 names in D49 order. Lists are comma-joined in stored order. Derived keys are not shown.
- **Impact:** R16.
- **Evidence:** E31

### D68 — Every output value except `neutral` adds a `WRITE` line
- **Status:** active
- **Question:** Do the default output values change the `WRITE` prompt of a default run?
- **Answer:** Yes. `auto`, `standard` and `report` each add a line. `tone=neutral` adds none.
- **Impact:** R4.
- **Evidence:** E10

### D69 — `memo` headings follow `language`
- **Status:** active
- **Question:** With `es` or `pt`, are the `memo` headings translated?
- **Answer:** Yes. Only `## Open questions` stays in English.
- **Impact:** R4.
- **Evidence:** E10

### D70 — Open questions bullets need no citation
- **Status:** active
- **Question:** Under `bullets`, do the `## Open questions` bullets need a citation?
- **Answer:** No. That section is exempt from the one-citation rule.
- **Impact:** R4.
- **Evidence:** E10

### D71 — No check compares `length=long` with the write cap
- **Status:** active
- **Question:** Is there a check when `length=long` meets a write cap below 8192 tokens?
- **Answer:** No. The report can end early, as with any low cap. `docs/spec.md` §8 states it.
- **Impact:** R4 and R13.
- **Evidence:** E32

### D72 — Brief preferences apply on the fallback path too
- **Status:** active
- **Question:** When the brief model fails, do the forced intent, the audience and the notes apply?
- **Answer:** Yes. They apply after `_normalize` on the model path and on the fallback path.
- **Impact:** R6.
- **Evidence:** E24

### D73 — Code holds the other strings, and the mismatch message has a fixed form
- **Status:** active
- **Question:** Who fixes the brief notes, the other prompt lines and the mismatch message?
- **Answer:** D39 extends to them: the specification gives meanings, and code gives strings. Tests assert each host and key term. Notes dedupe on the exact string and keep hosts in stored order. The mismatch message is `preference mismatch: <name> thread=<v> run=<v>; …; rerun with the same preferences or use a new --thread-id`.
- **Impact:** R6, R9, R10, R11, R12 and R17.
- **Evidence:** E13

### D74 — A host is strict ASCII
- **Status:** active
- **Question:** How does the host rule treat a trailing dot, non-ASCII names, punycode and `www.`?
- **Answer:** Refuse a trailing dot and non-ASCII. Accept punycode. Do not fold `www.`, so `www.a.com` and `a.com` are different hosts.
- **Impact:** R2.
- **Evidence:** E26

## Repository evidence

- E1: person-decision
- E2: repo:src/exact/models.py::ResearchBrief
- E3: repo:src/exact/nodes/plan.py#L25
- E4: repo:src/exact/nodes/scout.py#L67
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
- E28: repo:src/exact/cli.py#L149
- E29: repo:src/exact/prompts.py#L9
- E30: repo:src/exact/prompts.py#L46
- E31: repo:src/exact/status.py::format_effort
- E32: repo:docs/spec.md#L278
- E33: repo:docs/spec.md#L232
- E34: repo:src/exact/prompts.py#L58
- E35: repo:src/exact/nodes/plan.py#L214
- E36: repo:src/exact/nodes/plan.py#L104
- E37: repo:docs/spec.md#L215
- E38: repo:docs/spec.md#L311
- E39: repo:src/exact/nodes/plan.py#L57
- E40: repo:docs/spec.md#L375
- E41: repo:docs/spec.md#L383
- E42: repo:src/exact/nodes/scout.py#L30
- E43: repo:src/exact/cli.py#L161
- E44: person-decision

## Acceptance criteria

- **R1:** For each preference, a test sets the flag and the variable to different values, and the flag value wins. With neither set, the default applies. `--no-news` overrides `EXACT_NEWS_BIAS=1`. `EXACT_EXCLUDE_DOMAINS=a.com, b.com` gives two hosts. One `--exclude-domain c.com` replaces them. `--skip-clarify` gives `clarify_mode=skip`. With an injected `Runtime`, `--tone plain` and `--skip-clarify` reach the run, `--effort max` does not, and `--tone Executive` exits `1`.
- **R2:** Each of these exits `1` before the live-key check. Its D35 or D55 message goes to stderr: `--tone Executive`, `--lang fr`, a 21-host list, `https://a.com`, `*.a.com`, `a.com/blog`, `localhost`, `a.com.`, `münchen.de`, include with exclude, include with `--denylist social`, and `--skip-clarify --clarify prefer`. A 20-host list and `xn--mnchen-3ya.de` are valid. An invalid effort with an invalid tone reports the effort. An invalid tone with an invalid `EXACT_TRACE` reports the tone. Building `Settings` with include and exclude domains raises.
- **R3:** For every preference, the `effort=` echo line equals the line of a run without preferences, and every search requests the resolved `max_hits`.
- **R4:** The captured `WRITE` prompt holds the string of each value, the citation rule and `## Open questions`. This applies to each value of `language`, `length` and `structure`, and to each `tone` except `neutral`. With `tone=neutral` it holds no tone string. The `bullets` string exempts `## Open questions` from the citation rule. The `es` and `pt` strings keep `## Open questions` in English and tell the writer to translate the other headings.
- **R5:** Every preference field is an enum, a boolean or a validated host list. No other preference string reaches a prompt.
- **R6:** With `--sources web`, a query about trials gives `intent=web`, on the model path and on the fallback path. With `--sources auto`, the current rule decides `intent`. `--tone executive` gives `audience=executives` over a model value. `--exclude-domain a.com --denylist seo` gives two notes that name the hosts, after the model entries. `--include-domain a.com` gives one restriction note. A note equal to a model entry appears once.
- **R7:** At node level, the fake Exa client records the filters on the scout web leg, the scout publication leg, `exa_search` and `exa_publication_search`. It records no filter on a people call or a company call. At client level, the raw publication body holds `includeDomains`, `excludeDomains` and `startPublishedDate`, and the degraded path passes the snake-case arguments. With no filter set, no filter key is sent. `--exclude-domain quora.com --denylist seo` sends `quora.com` once. With a seed instant of 2026-09-21T01:00Z, `--since week` sends `2026-09-14`, `month` sends `2026-08-22` and `year` sends `2025-09-21`.
- **R8:** A filtered empty `exa_search` gives `lane web: no sources (filters: exclude, recency)` in `Finding.gaps` and in `uncovered`, and the graph reaches END. A filtered lane whose tool loop fails before any attempt gets the suffix. `no new sources` gets the suffix. `--denylist social` alone gives `(filters: exclude)`. An unfiltered lane and a people lane keep their current text.
- **R9:** The captured `PLAN` and `RESEARCH_SYS` prompts hold the primary-source text only with `prefer_primary`. `PLAN` holds the news line only with `news_bias`. `RESEARCH_SYS` holds the primary-source text on every lane. The news line is the same with and without `recency`. The Exa arguments do not change.
- **R10:** `--clarify skip` gives `clarify_needed=false` with no router call. `ExactState` has no `skip_clarify` channel. With `--clarify prefer`, the captured `DECIDE_CLARIFY` prompt holds the ask sentence and not the skip sentence. An ungrounded question still skips.
- **R11:** With `--sources academic --since month --tone plain`, the captured `DECIDE_CLARIFY` prompt tells the model not to ask about web versus academic, time range or audience. The entity axis stays in the prompt.
- **R12:** A resume with a different preference exits `1` with the D73 message, after the effort check, before the `effort=` echo, and with no trace line. A resume with the same values in another list order continues. A resume with `--skip-clarify` of an `auto` thread exits `1`. A thread with no `prefs` resumes under default preferences. A thread with no `prefs` and `skip_clarify=true` resumes under `--skip-clarify`. A resume a day later reuses the stored start date. The `Send` payload of each worker holds `prefs`. With `Settings` changed after the seed, nodes still use the checkpointed `prefs`. A clarify reply of "last month" leaves `prefs.recency=any`.
- **R13:** `docs/spec.md` and `docs/architecture.md` describe every flag, filter, lane rule, preset host and message of this specification. `docs/spec.md` §5 states the undated-page drop, and §8 states the `length=long` cap risk.
- **R14:** `make check` passes, and no test opens a network connection.
- **R15:** `--sources web` gives no scout publication leg on a query about trials, and a planned publication topic becomes web. `--sources academic` runs the scout publication leg on any query, and a planned web topic becomes publication. Under `--sources web`, planner topics `(q, publication)` then `(q, web)` give one topic, the first, with no `errors` line. Under `--sources academic`, an unknown focus gives `used publication`. A fallback topic follows the same change. People and company topics do not change. The captured `PLAN` prompt equals the prompt without `source_mix`.
- **R16:** A run with default preferences prints `prefs=default` after the `effort=` line. `--tone plain --exclude-domain b.com --exclude-domain a.com` prints `prefs tone=plain exclude_domains=b.com,a.com`. The trace `run_start.settings.prefs` holds every D50 key, `start_published_date` included. The trace `tool` line has no new key. A resume prints the checkpoint values in stored order.
- **R17:** With `--lang es`, the captured `DECIDE_CLARIFY` prompt tells the model to ask in Spanish and to quote scout titles unchanged. With `language=auto`, the prompt equals the current prompt.
- **R18:** A filtered scout web leg with no hits appends `exa scout: no hits (filters: exclude)`. An unfiltered empty leg appends none. A filtered publication leg with no hits appends `exa publication scout: no hits (filters: exclude)`. A filtered leg that raises appends only `exa scout failed: <exc>`.

## Open questions

None.
