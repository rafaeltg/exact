# Plan: Research effort levels (`normal` / `max`)

**Status:** Ready to implement  
**Spec impact:** Bounds, runtime, CLI — update `docs/spec.md` and `docs/architecture.md` in the same change  
**Depends on:** [`exa-publication-and-focus-lanes.md`](exa-publication-and-focus-lanes.md) lands first  
**Out of scope:** LLM reasoning / thinking depth (a follow-up change); extra modes beyond two; changing role models; changing snippet / tool-text caps; HTTP API / web UI

---

## 1. Goal

Give the user one switch that sets research depth. Higher effort means more graph
spend: more waves, more topics, more tool rounds, more hits.

Effort does **not** set LLM reasoning or thinking depth in this change. §11.1 gives
the reason.

Modes:

| Mode | Meaning |
| :--- | :--- |
| `normal` | Today's shipped graph contract |
| `max` | Modest bump above today (graph spend only) |

Do not add a third mode in this change.

---

## 2. Locked decisions

1. Effort controls **graph spend only** in this change. LLM reasoning and thinking
   stay env-driven (`EXACT_REASONING_EFFORT`, `EXACT_THINKING_BUDGET`) and no
   profile sets them. A follow-up plan adds the LLM half after measurement.
2. `max` **may raise** today's AGENTS / spec graph ceilings.
3. `normal` **equals today**. One correction is part of this change:
   `max_concurrency` is inert today (§4). After the fix LangGraph reads the key, but
   at the §3 values it still bounds nothing, because the only fan-out is one `Send`
   per topic and topics/wave equals `max_concurrency` in each profile. Behaviour does
   not change; `docs/spec.md` stops documenting an unenforced bound. `max` is the only
   raised profile.
4. Role models stay env-driven. Effort does **not** swap Haiku → Sonnet.
5. Clarify UX stays at 3 turns on both modes. Clarify is not research depth.
6. Snippet caps (1200 / 240) and tool-text cap (8000) stay fixed.
7. Name the product switch `effort` (`--effort`, `EXACT_EFFORT`). Keep
   `EXACT_REASONING_EFFORT` as the GPT reasoning knob, outside the profile.
8. The `max` column bounds **profiles only**. An explicit per-knob env keeps the
   range it has today. No per-knob env value that is legal today fails after this
   change. (A new, invalid `EXACT_EFFORT` does fail — `Settings` uses
   `extra="ignore"`, so that name has no meaning today.)
9. `max_hits` and `max_tool_rounds` are **process-scoped**, not thread-scoped. The
   resume guard does not cover them (§5).

---

## 3. Profiles

| Knob | `normal` | `max` |
| :--- | ---: | ---: |
| `max_iterations` (waves) | 3 | 4 |
| topics / first wave | 3 | 4 |
| follow-up topics / wave | 2 | 3 |
| `max_tool_rounds` | 4 | 6 |
| `max_hits` (scout + tools) | 5 | 8 |
| `max_concurrency` | 3 | 4 |
| `max_clarify_turns` | 3 | 3 |
| Reasoning / thinking | env-driven | env-driven |
| Role models | unchanged | unchanged |
| Snippet / tool-text caps | unchanged | unchanged |

The `max` column is the ceiling a **profile** may set. It does not bound an
explicit per-knob env (§4).

**The ratio is measured, not guessed.** This table gives about 13 topics against
7, and about 78 tool rounds against 28. Do not write an acceptance band into the
spec before step 5 of §8 measures one. Write the measured number.

---

## 4. Selection surface and precedence

**Surface**

- Env: `EXACT_EFFORT` with values `normal` | `max`. Default when unset: `normal`.
- CLI: `--effort {normal,max}`. The argparse default is `None`, so "not passed" is
  a value the code can read. Do not default the flag to `normal`.

**Precedence** (highest wins)

1. CLI `--effort` (when it is not `None`)
2. `EXACT_EFFORT`
3. Default `normal`

**Knob overlay**

1. Resolve the effort profile → baseline for all knobs in §3.
2. An **explicit** per-knob env (`MAX_ITERATIONS`, `MAX_CLARIFY_TURNS`,
   `MAX_TOOL_ROUNDS`, `MAX_HITS`) overrides the profile baseline. That value is not
   clamped. It keeps the range it has today.
3. Read explicitness from the env source, not from a comparison against a default.
   Settings defaults equal the `normal` baseline, so `MAX_TOOL_ROUNDS=4` and unset
   look the same to a diff. Use `model_fields_set`, or give each profile-owned
   field a sentinel `None` default that the profile fills after load.

Invalid `EXACT_EFFORT` / `--effort` → fail at startup with a clear error. Do not
silently fall back.

**Ordering.** Effort resolution is a pure function from `(flag, env)` to a
`Settings`. That `Settings` must exist **before** `Runtime` builds the role LLMs.
`Runtime.from_env()` takes no argument and calls the cached `get_settings()`, so
this change must add the seam. State what `--effort` does when a caller injects a
`Runtime`: the injected runtime wins, and the CLI does not re-resolve.

**Concurrency.** `max_concurrency` is a top-level `RunnableConfig` key.
`cli.thread_config` nests it under `configurable`, where LangGraph never reads it,
so today's `3` bounds nothing. Move the key to the top level and set it from the
profile. `docs/spec.md` already documents `max_concurrency=3`, so the document
becomes true. At the §3 values the key still binds nothing: `route_research` is the
only `Send` site, one per topic, and topics/wave equals `max_concurrency` in both
profiles. Fix it anyway, so a later profile that raises topics above concurrency is
bounded as the spec says.

---

## 5. Resume and state

- Seed `max_iterations`, `max_clarify_turns` and the resolved topics-per-wave caps
  into graph state at run start.
- Every cap read from state must fall back to a concrete settings value.
  `ExactState` is `total=False`, so `queries[:state.get("max_topics_first_wave")]`
  becomes `queries[:None]` on a thread seeded before this change and removes the
  cap without a message.
- `max_hits` and `max_tool_rounds` **cannot** reach a worker through state.
  `research_agent` receives only `ResearchPayload` (`topic`, `brief`,
  `prior_titles`) and reads `runtime.settings`; `scout` does the same. These two
  knobs are process-scoped. A resume from a shell with a different `.env` runs new
  worker depth inside an old thread. Say so in the spec. Do not claim the resume
  guard covers them.
- On `--thread-id` resume, compare the **resolved** effort against the
  checkpointed `effort`, not the raw flag. `EXACT_EFFORT=max` resuming a `normal`
  thread must fail the same way `--effort max` does.
- An **absent** `effort` key in a checkpoint means `normal`. Do not raise. Threads
  parked at a clarify interrupt across the upgrade carry no key, and an error rule
  would brick every one of them.
- Persist the resolved knob **values**, not only the effort name. A later retune of
  the `max` column is then visible in an old checkpoint.
- **Echo the profile.** Print the resolved effort and the resolved §3 values in one
  line at run start, next to `thread_id=`, and repeat the effort label in the Usage
  block. A saved transcript then describes itself, and triage does not need to
  decode `exact.sqlite`.

---

## 6. Code changes (by area)

### 6.0 State

Add the new channels to `ExactState` in
[`src/exact/models.py`](../../src/exact/models.py): `effort`,
`max_topics_first_wave`, `max_topics_followup`, and the other resolved values §5
persists. A write to a channel the `TypedDict` does not declare is not a no-op in
LangGraph.

`ResearchPayload` does not change (locked decision 9).

### 6.1 Config

- Add `exact_effort: Literal["normal", "max"]` to `Settings`. The field name carries
  the prefix: `Settings` sets no `env_prefix`, so a field named `effort` would bind
  `EFFORT` and ignore `EXACT_EFFORT` without an error.
- Add a single profile table (dict or small module) mapping effort → knob baselines.
- Resolve settings as: profile baseline → explicit env overrides. No clamp on env.
- Topics / follow-up caps move from hard-coded slices onto Settings
  (`max_topics_first_wave`, `max_topics_followup`). Effort sets them; code reads
  settings or state only.
- Expose `max_concurrency` on Settings from the profile.

Files: [`src/exact/config.py`](../../src/exact/config.py), possibly new `src/exact/effort.py`.

### 6.2 CLI

- Add `--effort` to argparse with default `None`.
- Resolve effort → `Settings` → `Runtime`, in that order (§4).
- Pass resolved `max_concurrency` at the **top level** of the thread config.
- On resume with a mismatched resolved effort, exit with an error. An absent
  checkpoint key is `normal`, not an error.
- Echo the resolved effort and knob values at run start (§5).
- Document in `--help` and `.env.example`.

File: [`src/exact/cli.py`](../../src/exact/cli.py).

### 6.3 Graph consumers

Four slices truncate topics, not two. Follow-ups truncate **twice**: once in
`reflect`, again in `plan`. Raising only the `reflect` cap leaves `max` at two
topics per follow-up wave.

| Site | Today | Becomes |
| :--- | :--- | :--- |
| [`plan.py:19`](../../src/exact/nodes/plan.py#L19) | `[:3]` | first-wave cap |
| [`plan.py:23`](../../src/exact/nodes/plan.py#L23) | `[:2]` for `wave > 0` | follow-up cap |
| [`plan.py:28`](../../src/exact/nodes/plan.py#L28) | `_followup_queries [:2]` | follow-up cap |
| [`reflect.py:36`](../../src/exact/nodes/reflect.py#L36) | `_followups [:2]` | follow-up cap |

- [`src/exact/nodes/research.py`](../../src/exact/nodes/research.py): already reads
  `max_tool_rounds` / `max_hits` from settings — confirm resolved values flow through.
- [`src/exact/nodes/scout.py`](../../src/exact/nodes/scout.py): same for `max_hits`.
- **Prompts carry the active cap.** A cap truncates; it cannot add a topic the model
  never wrote. [`prompts.py:39`](../../src/exact/prompts.py#L39) says "Use 2-3
  topics" and [`prompts.py:78`](../../src/exact/prompts.py#L78) says "give 1-2
  follow-up topic queries". Make the cap a format variable in both. Truncation stays
  as a guard, not as the mechanism. The `normal` rendering must equal the text the
  focus-lanes change leaves in place, so `normal` stays today's behaviour.

### 6.4 LLM kwargs

No change. `EXACT_REASONING_EFFORT` and `EXACT_THINKING_BUDGET` stay env-driven and
keep their present ranges. See §11.1.

### 6.5 Docs (same change)

- [`docs/spec.md`](../spec.md): graph bounds become "≤ profile / ≤ `max` ceiling";
  document `--effort` / `EXACT_EFFORT`; table for both modes; precedence; the resume
  rule; the process-scoped `max_hits` / `max_tool_rounds` exception; the measured
  spend ratio from §8 step 5.
- [`docs/architecture.md`](../architecture.md): Bounds section + runtime env table.
- [`AGENTS.md`](../../AGENTS.md): replace fixed graph numbers with "ceilings = `max`
  profile; default run = `normal`". Leave the LLM rows as they are.
- [`.env.example`](../../.env.example): `EXACT_EFFORT=normal`.
- [`README.md`](../../README.md): one short note on `--effort`.

Use ASD-STE100 in plan/spec prose.

### 6.6 Tests

- Unit: profile baselines for `normal` and `max`.
- Unit: `EXACT_EFFORT` set in the environment resolves the profile. An invalid-value
  test alone does not catch a wrong field name.
- Unit: precedence (CLI > env > default; explicit `MAX_*` overrides profile).
- Unit: an explicit env **equal to** the `normal` default stays at that value under
  `--effort max`. This is the test that catches a diff-against-default detector.
- Unit: an env value above the `max` column loads without error.
- Unit: invalid effort fails.
- Node: plan/reflect truncate to the active caps, not to 3/2.
- End to end: `reflect` → `plan_topics` under `max` yields three follow-up topics.
  A `reflect`-only test passes while the downstream `plan` slice still cuts to two.
- Graph: a `max` first wave fans out **four** `Send` calls. Do not assert that the
  configured cap reads 4.
- Concurrency: force `max_concurrency=1` against three fake topics and record peak
  concurrent `research_agent` entries. Do not assert the shape of the config dict. At
  the §3 values the bound never binds, so only a forced value proves the key is read.
- Seam: one test through the real `Runtime` build path asserts that `--effort max`
  reaches settings before the role LLMs exist. A test that injects `runtime=` passes
  on the broken path.
- Seam: an injected `Runtime` wins and the CLI does not re-resolve effort.
- Resume: mismatched resolved effort errors; an absent `effort` key resumes as
  `normal`.
- Keep fakes / graph seeds on `normal` unless a test targets `max`.
- No live network.

Use the test-design skill when writing tests.

---

## 7. Non-goals

- Setting reasoning or thinking depth from effort (a follow-up change).
- Auto-selecting effort from query difficulty.
- Changing temperature or `EXACT_MAX_TOKENS_*`.
- Per-role model upgrades via effort.
- Raising clarify turns on `max`.
- Raising snippet / tool-text caps.
- More than two modes.
- HTTP / Studio UI for effort.

---

## 8. Implementation order

0. Land [`exa-publication-and-focus-lanes.md`](exa-publication-and-focus-lanes.md)
   first. It owns the PLAN prompt rewrite and the spec v1.3 bump. This plan then
   applies its topic caps to lane-tagged topics and rebases §6.3 onto the new
   `PlannedTopic` shape.
1. Add `effort` profiles + settings resolve in `config` (and a small `effort`
   module if needed).
2. Plumb CLI `--effort`, top-level concurrency, the run-start echo, and seed
   `effort` plus resolved values into state.
3. Replace all four topic slices with settings/state caps and make the cap a prompt
   variable.
4. Tests for profiles, precedence, explicitness, caps, fan-out, concurrency, resume.
5. **Calibrate.** Run one fixed query at each effort. Compare the totals that
   `format_usage` prints. Define spend as one printed quantity and record the
   measured ratio. Record the ratio of cited sources over retrieved sources in the
   same run, for both modes.
6. Update spec, architecture, AGENTS, `.env.example`, README with the measured
   ratio.
7. Run: `ruff check`, `ruff format --check`, `complexity-guard.py --check`, `pytest -q`.

---

## 9. Done when

- `exact "…" --effort normal` matches today's documented contract, with the
  concurrency correction of locked decision 3.
- `exact "…" --effort max` fans out four `Send` calls in wave 0 and three in a
  follow-up wave.
- Explicit `MAX_*` env still overrides the profile and is not clamped.
- The run-start line and the Usage block name the resolved effort.
- The spec carries a **measured** spend ratio, not an estimate.
- The ratio of cited sources over retrieved sources is recorded for both modes. If
  it falls on `max`, the profile buys noise: either the write budget or the
  bibliography passed to WRITE must move with effort, in a follow-up.
- Spec, architecture, and AGENTS describe the two modes and the new graph ceilings.
- All quality gates in §8 step 7 are clean.

---

## 10. Open points closed in this plan

| Topic | Decision |
| :--- | :--- |
| Mode count / names | `normal`, `max` |
| Scope | Graph spend only; LLM depth is a follow-up |
| `normal` vs today | Identical, except enforced concurrency 3 |
| `max` numbers | §3 table |
| Models | Not part of effort |
| Clarify | Fixed at 3 |
| Surface | `EXACT_EFFORT` + `--effort`, flag default `None` |
| Precedence | CLI > env > default; explicit knobs > profile; no clamp on env |
| Ceiling | Bounds profiles only |
| Explicitness | Read from the env source, never from a diff against a default |
| Resume | Resolved effort compared; absent key = `normal`; hits/rounds process-scoped |
| Concurrency | Top-level config key; `normal` 3, `max` 4 |
| Spend ratio | Measured in §8 step 5, then written to the spec |
| Landing order | Focus lanes first |
| Naming | Product switch = `effort`; `Settings` field = `exact_effort` |

---

## 11. Ideas considered and rejected

1. **Set reasoning and thinking from the profile in this change.** Rejected. A
   thinking budget above 0 stops Anthropic forcing a tool call, so the router can
   answer in prose, `invoke_structured` raises `StructuredOutputError`, `plan` falls
   back to one topic and `reflect` takes `_cap_exit`. On the shipped Haiku-everywhere
   config, `max` could research less than `normal` and cost more. The follow-up plan
   must first measure the error rate under thinking on the default model.
2. **Keep thinking in the profile but switch it off for the router and compress
   roles.** Rejected for this change. It needs a per-role thinking split, which is a
   larger change than the graph half, and it still leaves `temperature=1` and a
   raised `max_tokens` on the other roles.
3. **Document that `max` implies `temperature=1` and `max_tokens = budget + role
   cap` on Anthropic.** Rejected together with idea 1. `config.py` forces both
   whenever the budget is above 0, so the non-goal "effort does not change
   temperature or `EXACT_MAX_TOKENS_*`" was false while the profile set a budget.
   Removing the budget from the profile makes the non-goal true instead.
4. **Clamp every resolved knob, including explicit env, to the `max` ceiling.**
   Rejected. A `.env` that is legal today would fail at startup even under
   `--effort normal`, against locked decision 3. The clearest case was
   `EXACT_THINKING_BUDGET=16000` and `EXACT_REASONING_EFFORT=high`; decision 1 now
   keeps both outside the profile, so no clamp could reach them anyway. The rejection
   still stands for the four `MAX_*` knobs, which the profile does own.
5. **Publish an order (`none < minimal < low < medium < high`) for the reasoning
   knob so it can be clamped.** Rejected with idea 4. No clamp needs it.
6. **Widen `ResearchPayload` and the `route_research` Send with the resolved caps.**
   Rejected for this change. It is a worker-contract change that `architecture.md`
   must record, and it buys thread-scoped depth for two knobs only. Locked decision 9
   states the limit instead.
7. **Effort lands first and focus lanes rebases onto it.** Rejected. Lanes rewrites
   `PlanDecision.topics` into `list[PlannedTopic]` and rewrites the PLAN prompt, so
   it owns the shape this plan truncates.
8. **Correct the concurrency nesting outside this plan, and drop the
   `max_concurrency` row.** Rejected. The correction does not change fan-out at the
   §3 values, but the key and the profile row define each other, so they belong in
   one change.
9. **Keep the "about 1.5–2× research spend" acceptance feel.** Rejected. The §3
   table gives about 2.8× model calls. A band that the table contradicts is not an
   acceptance criterion.
