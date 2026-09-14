# Plan: Research effort levels (`normal` / `max`)

**Status:** Ready to implement  
**Spec impact:** Bounds, runtime, CLI — update `docs/spec.md` and `docs/architecture.md` in the same change  
**Out of scope:** Extra modes beyond two; changing role models; changing snippet / tool-text caps; HTTP API / web UI

---

## 1. Goal

Give the user one switch that sets research depth. Higher effort means deeper research (more graph spend and more LLM reasoning / thinking).

Modes:

| Mode | Meaning |
| :--- | :--- |
| `normal` | Exact copy of today’s shipped contract |
| `max` | Modest bump above today (graph + LLM spend) |

Do not add a third mode in this change.

---

## 2. Locked decisions

1. Effort controls **graph spend and LLM spend** (not graph-only).
2. `max` **may raise** today’s AGENTS / spec ceilings.
3. `normal` **equals today**. `max` is the only raised profile.
4. Role models stay env-driven. Effort does **not** swap Haiku → Sonnet.
5. Clarify UX stays at 3 turns on both modes. Clarify is not research depth.
6. Snippet caps (1200 / 240) and tool-text cap (8000) stay fixed.
7. Name the product switch `effort` (`--effort`, `EXACT_EFFORT`). Keep `EXACT_REASONING_EFFORT` as the GPT reasoning knob inside a profile.

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
| `EXACT_REASONING_EFFORT` (GPT-5/6 only) | `none` | `medium` |
| `EXACT_THINKING_BUDGET` (Anthropic) | `0` | `8000` |
| Role models | unchanged | unchanged |
| Snippet / tool-text caps | unchanged | unchanged |

Acceptance feel: on a busy run, `max` is about 1.5–2× research spend vs `normal`, not an unbounded tier.

Hard product ceilings after this change = the `max` column. No mode may exceed that table.

---

## 4. Selection surface and precedence

**Surface**

- Env: `EXACT_EFFORT` with values `normal` | `max`. Default when unset: `normal`.
- CLI: `--effort {normal,max}`.

**Precedence** (highest wins)

1. CLI `--effort` (if passed)
2. `EXACT_EFFORT`
3. Default `normal`

**Knob overlay**

1. Resolve the effort profile → baseline for all knobs in §3.
2. If the user set an **explicit** per-knob env (`MAX_ITERATIONS`, `MAX_CLARIFY_TURNS`, `MAX_TOOL_ROUNDS`, `MAX_HITS`, `EXACT_REASONING_EFFORT`, `EXACT_THINKING_BUDGET`), that value **overrides** the profile baseline.
3. Clamp every resolved knob to the `max` ceiling in §3. Reject or clamp values above the ceiling (prefer: fail fast at settings load with a clear error).

Invalid `EXACT_EFFORT` / `--effort` → fail at startup with a clear error. Do not silently fall back.

**Concurrency:** derive `max_concurrency` from the resolved effort profile (and allow no separate env in v1 unless one already exists). Wire it into `cli.thread_config` instead of the hard-coded `3`.

---

## 5. Resume and state

- Seed `max_iterations` and `max_clarify_turns` into graph state at run start (already done). Also seed (or otherwise make available) the resolved topics-per-wave caps and tool/hits caps so workers and planner do not read a different profile mid-run.
- On `--thread-id` resume, **do not** re-apply a new `--effort` to an in-flight graph. Caps already in checkpointed state / the first seed win. Document this. If the user passes a different `--effort` on resume, either ignore it with a warning or error; prefer **error** (explicit, no silent mismatch).
- Persist the chosen effort name in initial state (e.g. `effort: "normal" | "max"`) for observability and resume checks.

---

## 6. Code changes (by area)

### 6.1 Config

- Add `effort: Literal["normal", "max"]` to `Settings` (`EXACT_EFFORT`).
- Add a single profile table (dict or small module) mapping effort → knob baselines.
- Resolve settings as: profile baseline → explicit env overrides → clamp to `max` ceilings.
- Topics / follow-up caps move from hard-coded slices in `plan.py` / `reflect.py` onto Settings (e.g. `max_topics_first_wave`, `max_topics_followup`). Effort sets them; code reads settings/state only.
- Expose `max_concurrency` on Settings from the profile.

Files: [`src/exact/config.py`](../../src/exact/config.py), possibly new `src/exact/effort.py`.

### 6.2 CLI

- Add `--effort` to argparse.
- Apply precedence when building `Runtime` / `Settings` for the run.
- Pass resolved `max_concurrency` into thread config.
- On resume with mismatched effort vs checkpointed `effort`, exit with error.
- Document in `--help` and `.env.example`.

File: [`src/exact/cli.py`](../../src/exact/cli.py).

### 6.3 Graph consumers

- [`src/exact/nodes/plan.py`](../../src/exact/nodes/plan.py): replace `[:3]` / `[:2]` with settings/state caps.
- [`src/exact/nodes/reflect.py`](../../src/exact/nodes/reflect.py): follow-up slice uses follow-up cap.
- [`src/exact/nodes/research.py`](../../src/exact/nodes/research.py): already uses `max_tool_rounds` / `max_hits` from settings — ensure resolved profile values flow through.
- [`src/exact/nodes/scout.py`](../../src/exact/nodes/scout.py): same for `max_hits`.
- Planner / reflect **prompts**: update copy that says “2–3 topics” so the model sees the active cap (or stay soft and let code truncate — prefer soft prompt + hard truncate).

### 6.4 LLM kwargs

- `chat_kwargs()` already reads `exact_reasoning_effort` and `exact_thinking_budget`. After profile resolve, `max` sets `medium` / `8000` unless the user overrode those envs.
- No per-role thinking split in this change (global budget as today).

### 6.5 Docs (same change)

- [`docs/spec.md`](../spec.md): acceptance bounds become “≤ profile / ≤ max ceiling”; document `--effort` / `EXACT_EFFORT`; table for both modes; resume mismatch rule; precedence.
- [`docs/architecture.md`](../architecture.md): Bounds section + runtime env table.
- [`AGENTS.md`](../../AGENTS.md): replace fixed “do not loosen” numbers with “ceilings = `max` profile; default run = `normal`”.
- [`.env.example`](../../.env.example): `EXACT_EFFORT=normal`.
- [`README.md`](../../README.md): one short note on `--effort`.

Use ASD-STE100 in plan/spec prose.

### 6.6 Tests

- Unit: profile baselines for `normal` and `max`.
- Unit: precedence (CLI > env > default; explicit `MAX_*` overrides profile; clamp/fail above ceiling).
- Unit: invalid effort fails.
- Node: plan/reflect truncate to active topic caps (not hard-coded 3/2).
- CLI: `--effort max` seeds higher `max_iterations` / concurrency.
- Resume: mismatched `--effort` errors.
- Keep fakes / graph seeds on `normal` unless a test targets `max`.
- No live network.

Use the test-design skill when writing tests.

---

## 7. Non-goals

- Auto-selecting effort from query difficulty.
- Changing temperature or `EXACT_MAX_TOKENS_*` via effort.
- Per-role model upgrades via effort.
- Raising clarify turns on `max`.
- Raising snippet / tool-text caps.
- More than two modes.
- HTTP / Studio UI for effort.

---

## 8. Implementation order

1. Add `effort` profiles + settings resolve / clamp in `config` (and small `effort` module if needed).
2. Plumb CLI `--effort` + concurrency + seed `effort` into state.
3. Replace hard-coded topic slices with settings caps.
4. Confirm LLM kwargs pick up resolved reasoning / thinking.
5. Update spec, architecture, AGENTS, `.env.example`, README.
6. Tests for profiles, precedence, plan/reflect caps, resume mismatch.
7. Run: `ruff check`, `ruff format --check`, `complexity-guard.py --check`, `pytest -q`.

---

## 9. Done when

- `exact "…" --effort normal` matches today’s behaviour and defaults.
- `exact "…" --effort max` uses the `max` column in §3.
- Explicit `MAX_*` / reasoning / thinking env still overrides the profile, but never above the `max` ceiling.
- Spec, architecture, and AGENTS describe the two modes and the new ceilings.
- All quality gates in §8 step 7 are clean.

---

## 10. Open points closed in this plan

| Topic | Decision |
| :--- | :--- |
| Mode count / names | `normal`, `max` |
| `normal` vs today | Identical |
| `max` numbers | §3 table |
| Graph + LLM | Both |
| Models | Not part of effort |
| Clarify | Fixed at 3 |
| Surface | `EXACT_EFFORT` + `--effort` |
| Precedence | CLI > env > default; explicit knobs > profile; clamp to `max` |
| Resume | Checkpointed effort wins; mismatch → error |
| Naming vs GPT reasoning | Product switch = `effort`; GPT knob stays `EXACT_REASONING_EFFORT` |
