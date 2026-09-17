# Plan: Exa-only paper retrieval and focused research lanes

**Status:** Ready to implement  
**Spec impact:** Tools, planner topics, scout, usage kinds — update `docs/spec.md` and `docs/architecture.md` in the same change (bump to v1.3)  
**Out of scope:** Elicit Reports / Systematic Review / MCP; Exa Answer / Deep / Agent as writer; PDF / paywall full text; new retrieval vendors (Semantic Scholar, OpenAlex, Consensus); raising spend ceilings

**Related:** Prior analysis in chat — Exa `category=publication` replaces unpaid Elicit search; Exact keeps its own write path.

---

## 1. Goal

1. Replace **live** academic paper retrieval with Exa `publication` search.
2. Keep **Elicit client and unit tests** in-tree, but remove Elicit from the live tool list and scout (dormant for a later re-enable).
3. Improve the literature path: scout + focused publication lane + DOI/abstract mapping.
4. Let the research planner split a brief into **multiple retrieval lanes** in one wave (e.g. people + publications).

---

## 2. Locked decisions

1. Live retrieval is **Exa only**. Do not call Elicit in scout or `research_agent` tool registration.
2. Keep `src/exact/tools/elicit.py`, `ELICIT_API_KEY` / Settings field, `FakeElicit`, and `tests/test_elicit.py`. Mark the live path dormant in code comments and docs.
3. Do **not** wire Exa `/answer`, Deep, or Agent into Exact. Exact’s writer stays the report synthesizer.
4. Planner topics become `{query, focus}` with  
   `focus ∈ {web, people, company, publication}`.
5. Each `research_agent` worker gets **only** the tools for its topic `focus` (plus `exa_highlights`).
6. Scout: always Exa web; on academic query signal, also Exa `publication` (no Elicit key gate).
7. Spec / architecture / AGENTS / README move to **Exa live; Elicit dormant**. Version **1.3.0**.

---

## 3. Why (short)

| Need | Choice |
| :--- | :--- |
| No Elicit Pro spend | Exa `publication` (~350M papers) already on the Exa bill |
| Literature + people in one query | Planner emits separate focused topics; workers do not share one mixed tool bag |
| Future Elicit Reports or search | Keep client code; do not delete |
| Report quality | Stay with Exact write + `[src_*]` audit; do not buy Elicit Reports |

Honest limit: BioASQ-style paper recall trails paid Elicit. Acceptable for this POC.

---

## 4. Design

### 4.1 Models

Add:

```text
TopicFocus = web | people | company | publication

PlannedTopic { query: str, focus: TopicFocus = web }

Topic { id, query, focus: TopicFocus = web, status }

Source.focus: TopicFocus | None   # set when search category is known
```

`PlanDecision.topics` becomes `list[PlannedTopic]`.

Coerce legacy string topics → `{query, focus=web}` in a Pydantic `before` validator so fakes and old checkpoints stay easy to migrate in tests.

`UsageEvent.kind` adds `exa_publication_search`. Keep `elicit_search` in the literal for dormant / historical events.

### 4.2 Exa client

| Change | Detail |
| :--- | :--- |
| Allow `category="publication"` | Same `search(..., category=)` path as people/company |
| Prefer raw `sdk.request("/search", …)` for publication | Current `exa-py` drops `type=publication` entities in `_parse_entities`; raw JSON keeps abstract/DOI |
| Fallback | `search_and_contents` if `request` is missing (fakes / older SDK) |
| Map DOI | Entity `doi`, else parse `doi.org/` from URL |
| Map snippet | Prefer publication `abstract`, else highlights; fold author/year/citations into snippet like people/company |
| Set `Source.focus` | From category when present |

### 4.3 Scout

1. Exa web search (unchanged) → usage `exa_search`.
2. If `academic_signal(query)`: Exa `publication` → usage `exa_publication_search`.
3. Remove Elicit scout branch entirely from the live path.
4. Status: count papers by `focus == "publication"`, not `provider == "elicit"`.

### 4.4 Planner

Update `PLAN` prompt:

- Emit 1 topic for a single lane; 2–3 when the brief needs **more than one lane** or compares entities.
- Each topic has `query` + `focus`.
- Explicitly allow mixed waves: people + publication, company + web, etc.
- Do not invent a lane for every mode when one lane covers the brief.

Follow-ups from reflect stay `list[str]`. When planning the next wave, infer focus:

- `academic_signal(followup)` → `publication`
- else if brief.intent == `academic` → `publication`
- else → `web`

CLI plan lines: `t0_1 [publication]  query…`

### 4.5 Research worker

| Focus | Tools |
| :--- | :--- |
| `web` | `exa_search`, `exa_highlights` |
| `people` | `exa_people_search`, `exa_highlights` |
| `company` | `exa_company_search`, `exa_highlights` |
| `publication` | `exa_publication_search`, `exa_highlights` |

Missing/unknown focus → treat as `web`.

Keep `elicit_search` as a method on the tools bag if useful for unit tests of the dormant client, but **do not** register it in `as_list()`.

Update `RESEARCH_SYS` to state the topic focus and tell the agent to use the matching tools only.

### 4.6 Usage / status

- Price `exa_publication_search` like other Exa searches.
- Status research suffix includes `exa_publication_search` when present.
- Keep elicit line in `## Usage` at $0 for dormant / future events (or show zero always — match current footer shape).

---

## 5. Literature path (target behavior)

```text
query with academic signal
  → scout: web + publication hits
  → brief.intent academic | mixed
  → plan: e.g.
       t0_1 [people]        "GLP-1 outcomes researchers"
       t0_2 [publication]   "GLP-1 cardiovascular trial evidence"
  → workers: filtered tools per focus
  → reflect / write / audit (unchanged)
```

Pure academic one-lane question → single `focus=publication` topic (planner choice).

---

## 6. Files to touch

| Area | Files |
| :--- | :--- |
| Models | `src/exact/models.py` |
| Exa | `src/exact/tools/exa.py` |
| Scout / plan / research | `src/exact/nodes/scout.py`, `plan.py`, `research.py` |
| Prompts | `src/exact/prompts.py` |
| Status / usage | `src/exact/status.py`, `usage.py` |
| Fakes | `tests/fakes.py` (stamp `focus=publication` on FakeExa category search) |
| Tests | `tests/test_exa.py`, `test_research.py`, `test_status.py`, `test_usage.py` (+ graph if plan shape breaks) |
| Docs | `docs/spec.md`, `docs/architecture.md`, `AGENTS.md`, `README.md` |
| Leave dormant | `src/exact/tools/elicit.py`, `tests/test_elicit.py`, config `elicit_api_key` |

Do not loosen complexity budgets. Extract helpers first if scout / research / plan grow over budget.

---

## 7. Test plan

| Spec behavior | Test |
| :--- | :--- |
| Publication category passed | FakeExa / FakeExaSdk records `category=publication` |
| DOI / abstract mapping | Entity props and `doi.org` URL fallback |
| Scout academic → publication call | Categories `[None, "publication"]`; no Elicit calls |
| Scout non-academic → web only | Single search, no publication |
| Elicit not on live tool list | Agent asking `elicit_search` does not hit FakeElicit |
| Focus filters tools | `focus=people` only people category; same for company/publication |
| Planner preserves focus | `PlanDecision` with people + publication → topics carry both focuses |
| String topic coerce | `PlanDecision(topics=["q"])` still works in tests |
| Usage kind | Scout / research emit `exa_publication_search` |
| Status | `[scout] N web · M papers` via `focus`; plan lines show `[focus]` |
| Existing bounds | Topics/wave, tool rounds, hits/call unchanged |

`make check` clean.

---

## 8. Implementation order

1. Models + PlanDecision coerce + docs skeleton (spec 1.3 tool table).
2. Exa publication search + DOI/abstract + tests.
3. Scout switch web → publication; retire live Elicit scout; status/usage.
4. Planner focus + prompts + plan status lines.
5. Research tool filter + `exa_publication_search`; drop live `elicit_search` registration.
6. Replace elicit live-path tests with publication / dormant tests; keep `test_elicit.py`.
7. AGENTS / README / architecture diagram; `make check`.
8. Fresh-context review of the diff (per AGENTS).

---

## 9. Done when

- Academic runs retrieve papers through Exa without an Elicit key.
- Mixed briefs can plan people + publication (or other lane pairs) in one wave with filtered tools.
- Elicit code still imports and unit-tests, but is unused on the live graph path.
- Spec v1.3 and architecture match the code.
- `make check` is green.
