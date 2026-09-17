# Plan: Exa-only paper retrieval and focused research lanes

**Status:** Change A ready to implement. Change B starts after a live Change A publication result is observed.  
**Spec impact:** Change A — tools, scout, usage kinds, source focus; bump `docs/spec.md` and `docs/architecture.md` to v1.3. Change B — planner topics, worker tool filter, wave semantics; bump both to v1.4. Update the contract documents in the same change as the code.  
**Out of scope:** Elicit Reports / Systematic Review / MCP; Exa Answer / Deep / Agent as writer; PDF / paywall full text; new retrieval vendors (Semantic Scholar, OpenAlex, Consensus); raising spend ceilings

**Related:** Prior analysis in chat — Exa `category=publication` replaces unpaid Elicit search; Exact keeps its own write path.

---

## 1. Goal

1. **(A)** Replace **live** academic paper retrieval with Exa `publication` search.
2. **(A)** Keep **Elicit client and unit tests** in-tree, but remove Elicit from the live tool list and scout (dormant for a later re-enable).
3. **(A)** Improve the literature path: scout + DOI/abstract mapping + paper counts that do not depend on the vendor name.
4. **(B)** Let the research planner split a brief into **multiple retrieval lanes** in one wave (e.g. people + publications), on every wave.

---

## 2. Locked decisions

1. Live retrieval is **Exa only**. Do not call Elicit in scout or `research_agent` tool registration.
2. Keep `src/exact/tools/elicit.py`, `ELICIT_API_KEY` / Settings field, `FakeElicit`, and `tests/test_elicit.py`. Mark the live path dormant in code comments and docs.
3. Do **not** wire Exa `/answer`, Deep, or Agent into Exact. Exact's writer stays the report synthesizer.
4. Ship the work as **two changes in two pull requests**:
   - **Change A — vendor swap.** Exa `publication` goes live, Elicit goes dormant. No planner or model-shape change.
   - **Change B — focus lanes.** Planner topics carry a focus and workers get filtered tools.

   Change B starts only after a **live Change A run returns a real publication result**. The reason is that Change B fixes the planner schema around a retrieval path whose live behaviour is not yet observed. The two changes also revert independently, so bad lane behaviour does not drag publication retrieval back with it.
5. **(B)** Planner topics become `{query, focus}` with  
   `focus ∈ {web, people, company, publication}`.
6. **(B)** Each `research_agent` worker gets **only** the tools for its topic `focus` (plus `exa_highlights`).

   In Change A the worker keeps today's mixed bag. `exa_publication_search` takes the `elicit_search` slot and stays gated on `brief.intent in {academic, mixed}` (`research.py:165`). This interim state is accepted, and it ends when Change B lands.
7. **(A)** Scout: always Exa web; on academic query signal, also Exa `publication` (no Elicit key gate). Widen `academic_signal` in the same change, because the Elicit key gate that masked its misfires is going away.
8. **(B)** The planner is the **only source of topics on every wave**. Remove the `_wave_queries` follow-up override (`plan.py:31-36`). The `PLAN` prompt must carry every unused follow-up through as a topic and assign it a focus.
9. Spec / architecture / AGENTS / README move to **Exa live; Elicit dormant** in Change A at version **1.3.0**, and to **focus lanes** in Change B at version **1.4.0**.

---

## 3. Why (short)

| Need | Choice |
| :--- | :--- |
| No Elicit Pro spend | Exa `publication` (~350M papers) already on the Exa bill |
| Literature + people in one query | Planner emits separate focused topics; workers do not share one mixed tool bag |
| Future Elicit Reports or search | Keep client code; do not delete |
| Report quality | Stay with Exact write + `[src_*]` audit; do not buy Elicit Reports |

Honest limit: BioASQ-style paper recall trails paid Elicit. Acceptable for this POC.

Accepted losses. Record them here so a later reader does not read them as defects:

- **Follow-up wording is no longer guaranteed.** Decision 8 moves the guarantee from code to the `PLAN` prompt. The planner can reword a reflect follow-up. Two tests in §7 hold the behaviour, but a prompt is a weaker guarantee than a code path.
- **A mislabeled lane costs a topic slot.** A worker with one search tool and zero hits has no second action, because `exa_highlights` refuses a URL that is not already in the bag (`research.py:154`). §3's recall limit makes empty publication sets likely. The repair is legibility, not a wider tool bag: the gap names its focus (§4.5) so the next wave can re-lane instead of re-query. Inside the 3x3 wave budget this remains a real loss.

---

## 4. Design

Each subsection marks the change that owns it.

### 4.1 Models

**Change A** adds:

```text
TopicFocus = web | people | company | publication

Source.focus: TopicFocus | None   # set when the search category is known
```

`UsageEvent.kind` adds `exa_publication_search`. Keep `elicit_search` in the literal for dormant / historical events.

`Source.focus` lands in Change A, not Change B. Papers arrive from Exa as soon as Change A ships, so `provider == "elicit"` stops separating papers from web on day one (§4.6).

**Change B** adds:

```text
PlannedTopic { query: str, focus: TopicFocus = web }

Topic { id, query, focus: TopicFocus = web, status }
```

`PlanDecision.topics` becomes `list[PlannedTopic]`.

A Pydantic `before` validator on `PlanDecision.topics` does two jobs. Both are **production** paths, not test aids:

1. Coerce a legacy string topic to `{query, focus=web}`. `plan.py:93-99` builds `PlanDecision(topics=[brief.question or initial_query])` — a bare string — when structured output fails. `usage.py:131-134` records that Anthropic cannot force a tool call while thinking is on, so with `EXACT_THINKING_BUDGET > 0` this is a normal path. List that construction among the call sites the new shape must keep working.
2. Normalize an unrecognized focus string to `web`. `TopicFocus` is a strict Literal inside the planner's structured output, but Exa's own category list also holds `news`, `personal site` and `financial report` (verified in `exa_py/api.py:268-277`). A router LLM that emits `focus="news"` would otherwise fail validation for the **whole** `PlanDecision`, not one topic, and `plan.py` would fall back to a single-topic plan built from `brief.question`. The whole wave would lose its lanes. §4.5's "unknown focus → web" rule runs later, in the worker, and is therefore too late.

The fallback plan built in `plan.py:93-99` derives its focus from `brief.intent`: `academic` or `mixed` → `publication`, else `web`. Without this, every structured-output failure on an academic brief silently plans a web lane and the run still finishes green.

### 4.2 Exa client — Change A

| Change | Detail |
| :--- | :--- |
| Allow `category="publication"` | Same `search(..., category=)` path as people/company |
| Prefer raw `sdk.request("/search", …)` for publication | `exa-py` `_parse_entities` builds only `company` and `person` entities and drops `type=publication`; raw JSON keeps abstract/DOI |
| Fallback | `search_and_contents` if `request` is missing (fakes / older SDK) |
| Map DOI | Entity `doi`, else parse `doi.org/` from URL |
| Map snippet | Prefer publication `abstract`, else highlights; fold author/year/citations into snippet like people/company |
| Set `Source.focus` | From category when present |

**Normalize the two payload shapes once.** `sdk.request` returns a JSON-decoded **dict** with camelCase keys (`exa_py/api.py:1481`). Every mapper in `exa.py` reads attributes: `_map` uses `getattr(result, "results")`, and `_source`, `_item_text` and `_entity_props` are getattr too (`exa.py:77,131,166,178`). Fed a dict, every getattr returns `None`, the search returns `[]` with no exception, and `_gap_kind` reports "no sources" — a silent empty result.

The requirement is therefore a **single normalization step** that converts either payload shape into one intermediate before `_source` runs. Do not add dict-versus-object branches inside each helper.

**Specify the request body from a captured response, not from memory.** Before implementation, capture one real Exa `publication` response and commit it as a fixture. Write §4.2's field list from that fixture. The body must include the `contents` block: highlights arrive only when the request asks for them, so without it the "else highlights" snippet fallback is dead code.

**`FakeExaSdk` must implement `request`.** Today it does not, so the §7 DOI and category rows exercise the fallback and the production path would ship untested. `FakeExaSdk.request` serves the captured raw fixture, and the tests assert **which path ran**.

**Make the fallback observable.** `pyproject` pins `exa-py>=1.2.0` — a floor only — and `search_and_contents` is marked DEPRECATED in the installed SDK. A routine `uv sync` that removes or renames `request` would drop production to the path this section calls lossy for abstract and DOI, while fake-based tests stay green. When the fallback runs, append one line to the existing `errors` channel that names the degraded capability.

**Record the verified SDK version.** The `_parse_entities` workaround was verified against **exa-py 2.20.0** (`_parse_entities` at `api.py:146`, entity dispatch at `api.py:250-264`, `Exa.request` at `api.py:1481`). Put that version and date in the code comment. The condition that retires the workaround is upstream support for publication entities. Consider an upper bound on `exa-py` so a dependency bump forces a re-check.

### 4.3 Scout — Change A

1. Exa web search (unchanged) → usage `exa_search`.
2. If `academic_signal(query)`: Exa `publication` → usage `exa_publication_search`.
3. Remove the Elicit scout branch entirely from the live path.
4. Status: count papers by `focus == "publication"`, not `provider == "elicit"`.

**Widen `academic_signal` (`src/exact/intent.py:12`).** `settings.elicit_api_key` (`scout.py:28`) masked the predicate's misfires for every user without a key, which is most of them. Removing the key gate makes the regex the sole gate. The current pattern is both too loose and too narrow:

- Too loose: "case study of Tesla marketing" trips on `study`. A false positive injects up to 5 paper hits into the 8-line scout block and skews `brief.intent`.
- Too narrow: `literature`, `evidence`, `journal` and `arxiv` do not match. "What does the literature say about GLP-1" gets no paper hits to cite in clarify.

Widen the term list and remove the bare `study` false positive. `src/exact/intent.py` joins the files to touch.

**The predicate also decides intent, not only the scout.** `brief.py:46-55 _has_academic_signal` calls `academic_signal` on the query, the clarification text, the picked option and the chat, and `brief.py:59-60 _normalize` promotes `intent web → academic` from the result. Widening the term list therefore changes which briefs get `exa_publication_search` at all, because the Change A worker gates that tool on `brief.intent` (`research.py:165`). Test the predicate at both levels: the scout call and the resulting `brief.intent`.

### 4.4 Planner — Change B

Update the `PLAN` prompt:

- Emit 1 topic for a single lane; 2–3 when the brief needs **more than one lane** or compares entities.
- Each topic has `query` + `focus`.
- Explicitly allow mixed waves: people + publication, company + web, etc.
- Do not invent a lane for every mode when one lane covers the brief.
- Carry **every unused follow-up** through as a topic. Prefer the follow-up's own wording. Assign each one a focus.

**Remove the follow-up override.** `_wave_queries` (`plan.py:31-36`) returns fresh follow-ups and discards `_planned_queries(...)` whenever any exist. That is the normal continue path, so on waves 1 and 2 the whole `PlanDecision` — and every focus in it — is thrown away. People and company lanes would be unreachable after wave 0.

Follow-ups stay `list[str]`, so they cannot carry a focus themselves. The planner already receives them verbatim: `PLAN` renders `Suggested follow-ups: {followups}` (`prompts.py:50`). Delete `_wave_queries` and let `decision.topics` be the plan on every wave. The new prompt rule above preserves what the override protected — reflect's gaps still get researched — and moves the guarantee from code to prompt. §7 holds it with two wave-1 tests.

Removing `_wave_queries` also leaves `_followup_queries` (`plan.py:27-28`) with no caller, and makes the `plan_topics` docstring false (`plan.py:86`, "prefer unused follow-ups on later waves"). Delete the one and rewrite the other in the same change.

This removal deletes the focus-inference heuristic entirely. No `academic_signal(followup)` rule and no `brief.intent` rule run in the planner, because the planner now assigns every focus itself. The only site that still needs an inferred focus is the structured-output fallback (§4.1).

**Render and de-duplicate topics by lane.** `_prior_queries` (`plan.py:39-50`) and the `PLAN` line "Prior topics (do not repeat)" carry query strings only, and `_unique_topics` (`plan.py:53-57`) drops a repeat on the lowercase query alone. The planner therefore cannot tell that "GLP-1 cardiovascular outcomes" ran as `web` but not as `publication`, and a legitimate second lane on the same question is deleted with no error and no status line. A lane is now part of a topic's identity, so:

- Prior topics render with their focus, for example `GLP-1 cardiovascular outcomes [publication]`.
- The uniqueness key becomes `(query, focus)`.

CLI plan lines: `t0_1 [publication]  query…`

### 4.5 Research worker

**Change A.** The tool bag keeps its current shape. `exa_publication_search` replaces `elicit_search` in the same slot and stays gated on `brief.intent in {academic, mixed}` (`research.py:165`). Do not register `elicit_search` in `as_list()`.

`RESEARCH_SYS` changes in **Change A**, not only in Change B. `prompts.py:58` reads "Use `elicit_search` only for academic/empirical questions when the tool is available." After Change A that line names a tool the worker no longer binds, and no line names `exa_publication_search`. Replace it in the same change.

**Change B.** Filter the bag by topic focus:

| Focus | Tools |
| :--- | :--- |
| `web` | `exa_search`, `exa_highlights` |
| `people` | `exa_people_search`, `exa_highlights` |
| `company` | `exa_company_search`, `exa_highlights` |
| `publication` | `exa_publication_search`, `exa_highlights` |

Missing/unknown focus → treat as `web`. §4.1 normalizes an unknown focus earlier, at parse time; this rule is the last defence.

**Name the focus in the empty-lane gap.** A worker whose single search tool returns nothing emits `gaps=["no sources"]`, which reflect can only turn into a plain query string. Emit `lane <focus>: no sources` instead, so the next wave can re-lane rather than re-query. This changes `_gap_kind` and any test that asserts the exact string `"no sources"`.

Keep `elicit_search` as a method on the tools bag if useful for unit tests of the dormant client, but **do not** register it in `as_list()`.

**Change B.** Update `RESEARCH_SYS` again to state the topic focus and tell the agent to use the matching tools only.

### 4.6 Usage / status — Change A

- Price `exa_publication_search` like other Exa searches. Confirm the publication rate against Exa's current price list before asserting parity, and date the rate-table comment.
- Status research suffix includes `exa_publication_search` when present.
- Keep the elicit line in `## Usage` at $0 for dormant / future events (or show zero always — match the current footer shape).

**Derive the accepted vendor kinds from one shared constant.** `_fold_tool` (`usage.py:256`) has no else branch, so a kind absent from `_EXA_SEARCH_KINDS` (`usage.py:215`) is dropped from `exa_cost` and from `total`. The per-vendor string is repeated across the `UsageEvent` literal, `_EXA_SEARCH_KINDS` (`usage.py:215`), `_empty_totals` (`usage.py:227-229`), `tool_counts`, `format_usage` (`usage.py:300-306`) and `status._research_tool_suffix`. A miss in any one of them under-reports Exa spend forever with every test green. One shared constant makes a new Exa category a one-line change.

**Replace `provider` with `focus` everywhere it separates papers from web, not only in status.** Five consumers break the moment papers arrive from Exa. The first is the most serious, because it feeds back into retrieval:

- `brief.py:14 _scout_text` renders each hit as `[{provider}]` **into the `BRIEF` prompt** (`brief.py:86`), which is the input the compress model uses to set `brief.intent`. After Change A every paper hit prints `[exa]`, so the paper signal disappears from that input and `brief.intent` skews toward `web`. The Change A worker gates `exa_publication_search` on `brief.intent in {academic, mixed}` (`research.py:165`), so this can silently strip papers from the flagship path. Label the hit by `focus`.
- `status.py:35` counts web as `provider == "exa"`, which now includes papers. 5 web + 5 papers would print `[scout] 10 web · 5 papers`. State the web count as the complement: `provider == "exa" AND focus != "publication"`. §4.1 stamps `focus` only when the category is known, and the web scout passes none.
- `clarify.py` `_scout_block` prints `[{provider}]` while `DECIDE_CLARIFY` describes "a SCOUT of web/paper hits". Every hit would print `[exa]`.
- `write.py:14 _reference_line` computes `loc = url or doi`, and every Exa source carries a URL, so the DOI that §4.2 invests in never reaches `## References`. A `focus == "publication"` reference line must render the DOI **in addition to** the URL. `write.py:15-19` also appends `" (exa)"` as the provider tag; label it by `focus` too.
- `research.py:56` prints `({provider})` in the worker's source listing that goes back to the model.

`brief.py`, `clarify.py`, `write.py` and `research.py` join the files to touch.

---

## 5. Literature path (target behavior)

**After Change A:**

```text
query with academic signal
  → scout: web + publication hits
  → brief.intent academic | mixed
  → plan: query strings, no lanes
  → workers: current tool bag; exa_publication_search when intent is academic | mixed
  → reflect / write / audit (unchanged)
```

**After Change B:**

```text
query with academic signal
  → scout: web + publication hits
  → brief.intent academic | mixed
  → plan: e.g.
       t0_1 [people]        "GLP-1 outcomes researchers"
       t0_2 [publication]   "GLP-1 cardiovascular trial evidence"
  → workers: filtered tools per focus
  → later waves: planner re-assigns lanes and carries follow-ups through
  → reflect / write / audit (unchanged)
```

Pure academic one-lane question → single `focus=publication` topic (planner choice).

---

## 6. Files to touch

### Change A

| Area | Files |
| :--- | :--- |
| Models | `src/exact/models.py` (`TopicFocus`, `Source.focus`, `UsageEvent.kind`) |
| Exa | `src/exact/tools/exa.py` |
| Intent | `src/exact/intent.py` (widen `academic_signal`) |
| Scout / research | `src/exact/nodes/scout.py`, `research.py` |
| Focus instead of provider | `src/exact/nodes/brief.py`, `clarify.py`, `write.py`, `research.py`, `src/exact/status.py` |
| Usage | `src/exact/usage.py` (one shared vendor-kind constant) |
| Prompts | `src/exact/prompts.py` (`RESEARCH_SYS:58` still names `elicit_search`) |
| Fakes | `tests/test_exa.py` (`FakeExaSdk`, at `test_exa.py:24`, gains `request` serving the captured fixture); `tests/fakes.py` (`FakeExa`, `fakes.py:240`, stamps `focus=publication` on a category search) |
| Fixtures | one captured Exa publication response, committed |
| Tests | `tests/test_exa.py`, `test_research.py` (scout rows live at `test_research.py:164-282`), `test_status.py`, `test_usage.py`, `test_clarify.py` (brief-intent rows at `test_clarify.py:332-472`) |
| Docs | `docs/spec.md`, `docs/architecture.md`, `AGENTS.md`, `README.md` |
| Onboarding / packaging | `.env.example`, `CONTRIBUTING.md`, `pyproject.toml` |
| Leave dormant | `src/exact/tools/elicit.py`, `tests/test_elicit.py`, config `elicit_api_key` |

`ELICIT_API_KEY` is **reserved for the dormant client**, not an optional feature switch. Say so in `.env.example:3` and `CONTRIBUTING.md:26`. Without this, a contributor provisions and later rotates a key that no live code reads, then files a bug because academic runs look identical with and without it. Update the `pyproject.toml:4` description ("Exa + Elicit, LangGraph") for the same reason.

Re-sync `docs/plans/trace-and-verbose-cli.md` when Change A lands. Its tracer rationale rests on "a disabled `elicit_search` calls `note` and returns", which Change A makes false.

### Change B

| Area | Files |
| :--- | :--- |
| Models | `src/exact/models.py` (`PlannedTopic`, `Topic.focus`, `PlanDecision.topics`, `before` validator) |
| Plan | `src/exact/nodes/plan.py` (remove `_wave_queries`; focus in `_prior_queries` and `_unique_topics`; fallback focus) |
| Research | `src/exact/nodes/research.py` (tool filter, lane-named gap) |
| Prompts | `src/exact/prompts.py` (`PLAN`, `RESEARCH_SYS`) |
| Status | `src/exact/status.py` (plan lines show `[focus]`) |
| Tests | `tests/test_research.py` (plan rows live at `test_research.py:352-421`), `test_status.py`, `test_graph.py` if the plan shape breaks it |
| Docs | `docs/spec.md`, `docs/architecture.md`, `AGENTS.md`, `README.md` |

Do not loosen complexity budgets. Extract helpers first if scout / research / plan grow over budget. Removing `_wave_queries` reduces `plan.py`, so the budget pressure falls on `exa.py` and `research.py`.

---

## 7. Test plan

### Change A

| Spec behavior | Test |
| :--- | :--- |
| Publication category passed | FakeExa / FakeExaSdk records `category=publication` |
| Raw path is the one under test | `FakeExaSdk.request` serves the captured camelCase fixture; the test asserts the raw path ran |
| Raw dict maps to sources | The captured fixture yields non-empty sources with DOI and abstract — the regression guard for getattr-on-dict |
| DOI / abstract mapping | Entity props and `doi.org` URL fallback |
| The request asks for `contents` | Assert on the payload `FakeExaSdk.request` captured: it carries a `contents` block. A fixture without an abstract then yields a highlight snippet. Asserting only the snippet proves nothing but that the fixture held highlights. |
| Fallback is observable | Missing `request` appends one `errors` line naming the degraded capability |
| Scout academic → publication call | Categories `[None, "publication"]`; no Elicit calls |
| Scout non-academic → web only | Single search, no publication |
| `academic_signal` false positive | "case study of Tesla marketing" plans no publication scout |
| `academic_signal` recall | A paper-seeking query holding none of the old keywords does trigger the publication scout |
| Widened predicate and intent | The same two queries also produce the right `brief.intent`, since `_normalize` promotes `web → academic` from the predicate (`brief.py:59-60`) |
| Brief input labels papers | `_scout_text` labels a publication hit as a paper, so the paper signal reaches the `BRIEF` prompt |
| Worker source listing | The worker's source block labels a publication source by focus, not `(exa)` |
| Elicit not on the live tool list | Assert the tool names the worker binds, at the DI seam (`FakeLLM.bind_tools`), or the `ToolNode` invalid-tool response. **Mutation-check this row**: re-register `elicit_search` and confirm it fails. The old form — "agent asking `elicit_search` does not hit FakeElicit" — already passes on HEAD, because `tests/fakes.py:274` defaults `FakeElicit(enabled=False)` and `research.py:165-167` returns the disabled string without calling `search`. It cannot fail. |
| Usage aggregate, not the event | One publication event raises the `exa` search count **and** the `total` in `format_usage`, and appears in the research status suffix |
| Status counts | A fixture that mixes web and publication hits prints `[scout] N web · M papers` with an exact-string assertion |
| Clarify block | A publication hit is labelled as a paper, not as `[exa]` |
| References carry DOI | A publication source with **both** a URL and a DOI renders both. A DOI-only source already passes on HEAD (`write.py:14` is `url or doi`), so that case does not discriminate. |

### Change B

| Spec behavior | Test |
| :--- | :--- |
| Focus filters tools | `focus=people` only people category; same for company/publication |
| Planner preserves focus | `PlanDecision` with people + publication → topics carry both focuses |
| String topic coerce | `PlanDecision(topics=["q"])` still works |
| Unknown focus survives | `PlanDecision(topics=[{"query":"q","focus":"news"}])` parses as a **web lane**; the plan does not collapse |
| Fallback keeps the lane | A structured-output failure on an academic brief still plans a publication lane |
| Fallback covers `mixed` | The same failure on a **mixed** brief also plans a publication lane, not a web lane |
| Lanes survive wave 1 | A follow-up from a people lane still plans as `people` on wave 1 |
| Follow-ups are not lost | An unused follow-up still appears as a topic on wave 1 |
| Same query, second lane | A prior `web` topic does not delete a new `publication` topic with the same query |
| Empty lane names itself | A worker with no hits emits `lane people: no sources` |
| Plan status lines | Plan lines show `[focus]` |
| Existing bounds | Topics/wave, tool rounds, hits/call unchanged |

`make check` clean on each change.

---

## 8. Implementation order

### Change A — Exa publication live, Elicit dormant (spec 1.3.0)

1. Capture one real Exa publication response. Commit it as a fixture.
2. `TopicFocus`, `Source.focus`, `UsageEvent.kind`; one shared vendor-kind constant in `usage.py`.
3. Exa publication search: single payload normalization, DOI/abstract mapping, observable fallback, `FakeExaSdk.request` + tests.
4. Widen `academic_signal` + scout tests.
5. Scout switch web → publication; retire the live Elicit scout.
6. Focus instead of provider in `brief.py`, `status.py`, `clarify.py`, `write.py`, `research.py` + tests.
7. `exa_publication_search` into the `elicit_search` slot in `research.py`; drop the live `elicit_search` registration; update `RESEARCH_SYS`; make the binding test discriminating and mutation-check it.
8. Spec 1.3 / architecture / AGENTS / README / `.env.example` / `CONTRIBUTING.md` / `pyproject.toml`; re-sync `docs/plans/trace-and-verbose-cli.md`; `make check`.
9. Fresh-context review of the diff (per AGENTS).

**Gate: run Change A live on an academic query and confirm real publication sources with DOIs reach the report. Change B does not start before this.**

### Change B — focus lanes (spec 1.4.0)

1. `PlannedTopic`, `Topic.focus`, `PlanDecision.topics`, and the `before` validator (string coerce + unknown-focus normalization).
2. Fallback plan derives focus from `brief.intent`.
3. Remove `_wave_queries`; focus in `_prior_queries` and `_unique_topics`; plan status lines.
4. `PLAN` prompt: lanes, and carry unused follow-ups through with a focus.
5. Research tool filter by focus; `RESEARCH_SYS`; lane-named empty gap.
6. Spec 1.4 / architecture / AGENTS / README; `make check`.
7. Fresh-context review of the diff (per AGENTS).

---

## 9. Done when

### Change A

- Academic runs retrieve papers through Exa without an Elicit key, on the raw `request` path, proven by a test that asserts which path ran.
- Paper and web counts, the clarify scout block, the `BRIEF` prompt input, the worker source listing and the `## References` provider tag all read `focus`, not `provider`. A publication reference line shows its DOI next to its URL.
- `academic_signal` is widened, and both its scout effect and its `brief.intent` effect are tested.
- `RESEARCH_SYS` no longer names `elicit_search` and does name `exa_publication_search`.
- A publication event moves the Exa total in `format_usage`.
- Elicit code still imports and unit-tests, but is unused on the live graph path, proven by a mutation-checked binding assertion.
- Spec v1.3 and architecture match the code. `.env.example` and `CONTRIBUTING.md` call `ELICIT_API_KEY` reserved.
- `make check` is green.
- A live academic run returned real publication sources.

### Change B

- Mixed briefs can plan people + publication (or other lane pairs) in one wave with filtered tools.
- Lane pairs still work on waves 1 and 2, and an unused follow-up still becomes a topic.
- An unknown focus token degrades one topic to `web` and never collapses the plan.
- Spec v1.4 and architecture match the code.
- `make check` is green.

---

## 10. Ideas considered and rejected

1. **An unconditional publication scout on every run**, in place of the `academic_signal` gate (locked decision 7). Rejected. It would add one Exa search to every run, including plainly non-academic ones, and it would delete a behaviour the scout is meant to have: a non-academic query returns web hits only. Widening the predicate corrects both failure directions — the `study` false positive and the missing `literature` / `evidence` / `journal` / `arxiv` terms — at lower per-run cost, and it keeps locked decision 7 intact.
