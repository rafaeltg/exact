# Plan: Trace sidecar and verbose CLI

**Status:** Ready to implement  
**Spec impact:** Runtime, CLI, observability — update `docs/spec.md` and `docs/architecture.md` in the same change  
**Out of scope:** Model thinking / CoT tokens; raw vendor payloads on state; live tool crumbs on stdout; eval harness / replay UI; HTTP API / web UI

---

## 1. Goal

Give Exact two independent controls:

| Control | Job |
| :--- | :--- |
| `--trace` | Write a complete **structured** run trace to a JSONL sidecar for later eval |
| `--verbose` | Enrich human CLI status (plan + decisions + parallel clarity) |

Default status lines stay as they are today. Live “CoT theater” is not a requirement.

Isolation stays: the parent graph never sees raw research tool I/O. The tracer is a side channel. Tool events hold **summaries only** (name, args crumb, hit count, titles, URL crumbs).

**Acceptance target for the payloads.** No eval harness reads the file yet, so the
payload shapes have no consumer to answer to. Two written questions take that role. A
payload is sufficient when a reader can answer both from the sidecar alone:

1. *Which topic in which wave produced no usable source, and which tool attempt failed
   first for that topic?*
2. *Did a settings change (model, reasoning effort, thinking budget, or a bound) move the
   claim count or the source count between two runs of the same query?*

A kind that no question needs is still written in v1, but its payload stays provisional
(§4).

---

## 2. Locked decisions

1. Primary deliverable is the **sidecar trace**, not real-time spectacle.
2. CLI enrichment is light and **opt-in** via `--verbose`.
3. Trace lives in a **sidecar JSONL** file, not in checkpointed graph state.
4. Tool capture is **structured summaries**, one event per tool **attempt**, each with an
   explicit outcome (`ok` / `refused` / `disabled` / `error`) — not full I/O, and not a
   pre/post pair around `note` / `call`. The seam is `_Bag.call` plus the two early returns
   in `_Tools` (§6.2).
5. Keep parent isolation; do not loosen it when tracing.
6. Two knobs: `--trace` / `EXACT_TRACE` and `--verbose` / `EXACT_VERBOSE` (either alone is
   valid).
7. Emitters are **split by source of truth**: a CLI-side sink on the existing
   `stream_mode=updates` loop derives every stage kind; a `Runtime` tracer emits `tool`
   only, from `_Bag` and the scout wrappers.
8. v1 includes **all** event kinds in §4.
9. Parallel workers: a process-local lock guards **every** emit and the `seq` it takes.
   The sink emits on the CLI thread while the workers emit `tool` events from their own
   threads, so the two write concurrently during a wave. Interleaved lines are acceptable;
   events carry `topic_id` / `wave` when known.
10. Clarify resume with the same `thread_id` **appends** the same file. Each open starts a
    new `run_id` and a new `seq` series (§4).
11. Default CLI (no flags) is **unchanged**.

---

## 3. Controls and paths

**Surface**

| Knob | CLI | Env | Default |
| :--- | :--- | :--- | :--- |
| Trace | `--trace` / `--no-trace` | `EXACT_TRACE` (`0`/`1`) | off |
| Verbose | `--verbose` / `--no-verbose` | `EXACT_VERBOSE` (`0`/`1`) | off |
| Trace path | `--trace-path PATH` | `EXACT_TRACE_PATH` | derived (below) |

**Precedence:** CLI flag > env > default.

**Default path:** the `traces/{thread_id}.jsonl` child of the directory that holds
`EXACT_DB`. **Join the parts; do not interpolate a string.** `EXACT_DB` defaults to the
bare `exact.sqlite`, whose dirname is empty, so `{dirname(EXACT_DB)}/traces/…` would yield
the absolute `/traces/…`. Example: `EXACT_DB=exact.sqlite` → `./traces/{thread_id}.jsonl`.

**Validation, before any model spend.** Resolve and open the path once at startup. Fail
loud — do not defer these to the fail-soft path of §6.1:

- Refuse a `--thread-id` that holds a path separator **when the path is derived**. The id
  becomes a file name only in that case; an explicit `--trace-path`, or a run with tracing
  off, must keep accepting the thread ids that are valid today.
- Refuse a path equal to `EXACT_DB`. Compare the two **resolved absolute** paths, not the
  raw strings. An append into the SqliteSaver file corrupts the checkpoint irreversibly.
- Refuse an unwritable target, or a target directory that cannot be created.

Create the `traces/` directory during this startup step, not on first write. Add
`traces/` to `.gitignore`. When the open succeeds, the CLI prints the **absolute** resolved
path once as `trace=<path>`, next to `thread_id=…`. It prints nothing before the open
succeeds.

**Resume carries no trace config.** Neither the state nor the checkpoint holds the flags
or the path, so a resumed run must repeat them. The CLI prints one warning, and continues,
in either direction of the mistake:

- `--trace` is **off**, `--thread-id` is given, and the derived path already exists. The
  operator dropped the flag, and this resume writes nothing into a file that holds the
  earlier turns. Name the file in the warning.
- `--trace` is **on**, `--thread-id` is given, and the resolved path does **not** exist.
  The operator kept `--trace` but dropped `--trace-path`, so this resume starts a second
  file and one thread's turns land in two places.
- `--trace` is **on** and the resolved path holds lines for a different `thread_id`. The
  operator reused a path.

These warnings go to **stderr**. The first one can fire on a run with no `--trace`, so it
is the single exception to “default CLI unchanged” (§2.11) — stdout still matches today's
lines byte for byte.

---

## 4. Trace format

UTF-8 JSONL. One object per line. No pretty-print. Flush after each line, so a run that
dies mid-way keeps every line it emitted.

**Envelope (every line)**

| Field | Meaning |
| :--- | :--- |
| `v` | Integer format version. Starts at `1` |
| `ts` | UTC ISO-8601, microsecond resolution |
| `run_id` | UUID for this open of the file |
| `thread_id` | LangGraph thread id |
| `seq` | Monotonic int within this `run_id` |
| `kind` | Event kind below |
| `data` | Object holding the whole payload |

**Canonical order is `(run_id, seq)`.** A resumed file holds several `run_id` values and
several `seq=1` lines. `ts` does not break ties between parallel workers, so a consumer
must not sort by it.

**Version rule.** An added field keeps `v`. A renamed or removed field raises it. The
`usage` payload fields are enumerated in `docs/spec.md`, not defined by reference to the
internal `usage.py` dict, because those keys have already changed once (commit `2d29acf`).

**The whole payload sits under `data`.** No payload field can then shadow an envelope
field. This is not cosmetic: the existing usage events carry their own `kind` key (`llm`,
`exa_search`), so a flat `emit(kind, **payload)` would raise `TypeError` during argument
binding — outside the reach of the fail-soft handler inside `emit`.

**Kinds (v1 — all required)**

| Kind | `data` payload |
| :--- | :--- |
| `run_start` | query, flags (`trace`/`verbose`), resume marker, settings snapshot (below) |
| `run_end` | `outcome`, exit-relevant crumbs (dangling citation count), dropped-emit count, optional error summary |
| `decision` | clarify needed/skip; reflect continue/write + followups |
| `brief` | intent, must_cover, question |
| `plan` | wave, topic ids + queries |
| `agent` | role, model, node, optional `topic_id` / round |
| `tool` | name, `outcome`, `topic_id`, args summary (query/url), `hit_count`, ≤N titles with a URL crumb each, optional error |
| `finding` | topic_id, claim count, source_ids, gaps |
| `report_refs` | cited `src_*` vs present-but-uncited ids |
| `usage` | counts and tokens only; no USD in the file |

The payloads of `brief`, `plan`, `decision` and `finding` mirror state channels that
`docs/spec.md` already contracts, so they are stable. The four new shapes — `tool`,
`agent`, `run_start` / `run_end`, `report_refs` — are marked **provisional** in the spec
until the §1 questions are answered against a real trace. The envelope is not provisional.

**`run_start` settings snapshot.** Per-role model ids, temperature, reasoning effort,
thinking budget, `max_hits`, `max_iterations`, `max_tool_rounds`, `max_clarify_turns`.
Without it, two traces that differ only by `EXACT_THINKING_BUDGET` are indistinguishable
and question 2 of §1 has no answer. **Redaction rule:** never write an API key or any
`Settings` field whose name ends in `_api_key`. State the rule in the spec beside the
summary-only rule.

**`run_end` outcome** is one of `finished` / `interrupted` / `rejected` / `error`.
`rejected` covers the `thread already finished` exit. `interrupted` covers the clarify
pause and Ctrl-C. A line with no `run_end` for its `run_id` means the process died or the
tracer went dark — state that reading in the spec, because a truncated run otherwise
scores as a complete one.

**Hard rule:** never write full snippets, highlights bodies, or vendor JSON blobs into the
sidecar. A URL beside a title is a crumb, not a body, and it is what makes a trace
readable after its checkpoint DB is deleted — `src_*` ids resolve only through the
`sources` channel inside the disposable `exact.sqlite`.

**Title cap:** a small fixed N (recommend **5**, same as `max_hits` default), documented in
the spec.

**`hit_count` means the raw hit count of the attempt, before prior-title dedupe.** Define
it that way in the spec. The deduplicated count is derivable from the titles that follow.

---

## 5. Roles

```text
stream updates  --sink-->    tracer  --append-->  traces/{thread_id}.jsonl
                --format-->  status.py  --print-->  CLI stdout
_Bag / scout    --emit-->    Runtime.trace  --append-->  same file (under lock)
CLI wires flags / path, validates, opens and closes the tracer.
```

| Role | Owns |
| :--- | :--- |
| Tracer | Only sidecar writer; no-op when trace off; lock; `run_id`; `seq`; flush |
| CLI sink | Derives `decision`, `brief`, `plan`, `finding`, `agent`, `usage` from the chunks the status loop already reads. The CLI emits `run_start`, `run_end`, `report_refs` outside the loop |
| `_Bag` / scout | Emit `tool` summaries; never put raw tool I/O on parent state |
| `status.py` | Human lines only; verbose enriches plan/decisions; never writes the sidecar |
| CLI | Flags, path validation, open/close tracer, print path, existing `stream_mode=updates` loop |

`ask_user` and `audit_citations` stay unbound to `Runtime`. `audit_citations` stays a pure
code-only node and the single owner of citation resolution.

---

## 6. Code changes (by area)

### 6.1 Tracer

New small module (e.g. `src/exact/trace.py`):

- `NullTracer` / `JsonlTracer` behind one protocol.
- `emit(kind, data)` appends one envelope line under a threading lock, then flushes.
- **Run-scoped, not process-scoped.** Derive `thread_id` before `build_graph`, construct
  the tracer, then build a per-call copy of the runtime with `dataclasses.replace` and
  pass that to `build_graph`. Never mutate the injected `Runtime`: `_bind` closes over one
  object for every node, so a mutation would bind a caller's runtime — a test's, or a
  future batch harness's — to one thread and one open file handle.
- **The tracer is a new `Runtime` field, not an `extras` key.** `dataclasses.replace`
  copies the field references, so a tracer written into `extras` would land in the very
  dict the caller still holds — the mutation the previous point forbids, reintroduced.
- Close the tracer in a `finally`, and emit `run_end` from that same `finally`.
- Fail soft on I/O errors after the startup validation of §3: record one stderr warning,
  count the dropped emit, and continue as a no-op for that emit. The count goes into
  `run_end`.

Files: new `src/exact/trace.py`; wire in [`src/exact/config.py`](../../src/exact/config.py).

### 6.2 Emitters

**CLI sink (every kind except `tool`).** The `stream_mode=updates` loop in
[`cli.py`](../../src/exact/cli.py) already yields the state deltas that
[`status.py`](../../src/exact/status.py) formats: `clarify_needed`, `brief`, `topics`,
`findings`, `sources`, `usage`, `uncovered`. One sink beside `format_update` derives
`decision`, `brief`, `plan`, `finding`, `agent` and `usage` from the same chunks. This
needs no new node bindings — no `Runtime` on `ask_user` or `audit_citations` — and no edits
to the non-retrieval node files. `research.py` and `scout.py` are still edited, for `tool`.

- `finding` comes from the chunk itself, so the zero-source branch is covered for free:
  `research.py` returns `_empty_finding` before `_prune` runs when `bag.collected` is
  empty, and that return still puts one `Finding` on `findings`. Retrieval failure is a
  graph invariant, so this branch is a real path, not an edge case.
- `agent` comes from the `llm` usage events, which already carry `node`, `role` and
  `model`. `topic_id` comes from the same chunk.
- A **failed** LLM call returns no usage event: `decide_clarify`, `generate_brief`,
  `plan_topics` and `reflect` all fall back without one when the structured call raises.
  The sink therefore writes no `agent` and no `usage` line for that call — the run most
  worth tracing. v1 accepts this and states it in the spec. To close it, those fallbacks
  must return a usage event, which is a node change and is out of this scope.
- `usage` is emitted **once per chunk delta**. `run_end` never dumps totals:
  `research_agent` returns loop, bag and prune usage, and the parent append channel
  re-accumulates it, so a second emit would double-count.
- `report_refs` is emitted from the CLI at `run_end`, from
  `audit.cited_ids(result["final_report"])` against `result["sources"]`. A second
  extraction path inside an emitter would drift from the audit whose `dangling:` entries
  drive the exit code. It is emitted **only when the outcome is `finished`** — no other
  outcome has a `final_report` to read.
- `run_start` is emitted after the §3 validation succeeds and after the first
  `app.get_state(config)`, because its resume marker is not knowable before that call.

The sink reads what the nodes return on state. A node that stops returning a field loses
its event silently, so the key-set test of §6.6 guards the shapes.

**`Runtime` tracer (`tool` only).** `research_agent` and `scout` are already bound to
`Runtime`, so no new **node** binding is needed. `_Bag` and `_Tools` do gain a tracer
argument.

- **Research** ([`nodes/research.py`](../../src/exact/nodes/research.py)): no single
  existing method sees a whole attempt, so the emit needs two places and one new return
  value:
  - **`_Bag.call`** owns the label and the `try` / `except`, so it owns the `ok` and
    `error` events. `ingest` must hand it the raw hit count (`len(found)`, before the
    prior-title dedupe) and the minted titles with their URLs; today `ingest` returns only
    a compacted string, so it gains a structured return beside it.
  - **`_Tools`** owns the two attempts that never reach `call`: `exa_highlights` returns
    its refusal before `note`, and `exa_publication_search` calls `note` then returns when
    the intent is non-academic. Each emits its own event.

  A pre/post pair around `note` / `call` would both invent and drop events here, and the
  obvious post-hook would write snippet bodies. `_Bag.ingest` alone cannot carry the event:
  it receives only the source list — no tool name, no args, no outcome — and `call` reaches
  it only after `fetch()` returns, so it is unreachable on three of the four outcomes.
  `_Bag` and `_Tools` therefore take the tracer as a new constructor argument.
- **Scout** ([`nodes/scout.py`](../../src/exact/nodes/scout.py)): `tool` summaries for the
  Exa/Elicit scout calls; no raw hits in the event.

Do **not** route tool detail through `stream_mode=updates` or parent state.

### 6.3 CLI

File: [`src/exact/cli.py`](../../src/exact/cli.py).

- Add `--trace`, `--verbose`, `--trace-path`.
- Resolve knobs; derive `thread_id`; validate and open the path (§3); build the tracer;
  pass a replaced `Runtime` into `build_graph`.
- Print `trace=…` after the open succeeds.
- Add the sink to the updates loop.
- Wrap the run in `try` / `finally`; emit `run_end` with its outcome and close the tracer
  there. The three paths that otherwise skip it are the `SystemExit("thread already
  finished")` raised after `run_start`, the clarify-interrupt path that returns normally,
  and a Ctrl-C or vendor error that unwinds `main`.
- Pass a verbose flag into `format_update` (or a thin CLI wrapper). Keep the updates loop.

### 6.4 Status (verbose)

File: [`src/exact/status.py`](../../src/exact/status.py).

**This section is not ready to implement. Write the target lines before step 5.**
Every item the plan calls “verbose” is already in the default output:
`format_plan` prints the wave header and the indented `  tid  query` lines; `_research`
prints `[research {topic_id}] n sources`; `_decide_clarify`, `_reflect` with its followups
and `_brief` with its question line all print today. So the list below states **no delta**,
and both the §6.6 “default vs verbose golden lines” test and the §9 criterion are
unverifiable as written.

Decide the real delta first. Candidates, none of them chosen yet: the wave and topic id on
every research line (today only the topic id appears, and only when a finding exists); the
brief `must_cover` items rather than their count; the reflect reason, not only
continue/write; per-topic source counts as a wave closes.

The original intent, kept for the record:

- Plan: wave header + indented topics (tighten grouping).
- Research: always show wave/topic so parallel workers read cleanly.
- Decisions: clarify needed/skip; reflect continue/write + followups; brief one-liner.

When not verbose: **bit-identical** to today’s lines (golden tests).

No live `[tool …]` stdout lines in v1.

### 6.5 Docs (same change)

- [`docs/spec.md`](../spec.md): flags, path and its validation, envelope, kinds, which
  payloads are provisional, the version rule, the summary-only and redaction rules,
  isolation, resume append and `(run_id, seq)` order.
- [`docs/architecture.md`](../architecture.md): tracer role, CLI sink vs `Runtime` tracer,
  status vs sidecar.
- [`.env.example`](../../.env.example): `EXACT_TRACE=0`, `EXACT_VERBOSE=0`, optional
  `EXACT_TRACE_PATH`.
- [`.gitignore`](../../.gitignore): `traces/`.
- Short README note if the README already documents CLI flags.

Use ASD-STE100 in plan/spec prose.

### 6.6 Tests

- **Env isolation first.** [`tests/fakes.py`](../../tests/fakes.py) builds
  `Settings(**settings)` with no `_env_file=None`, and `Settings` reads `.env`. A developer
  who sets `EXACT_VERBOSE=1` or `EXACT_TRACE=1` in `.env` for daily use would then fail the
  golden status tests and have fake runs write `traces/` into the repo, where `.gitignore`
  hides them. Build the fake settings with `_env_file=None`, which disables the file. The
  **process** environment needs a second step — pydantic-settings offers no constructor
  switch for it, so use a `settings_customise_sources` override or `monkeypatch`. Give
  every CLI trace test an explicit `--trace-path` under `tmp_path`. Without all of this,
  `make check` is machine-dependent.
- Tracer: no-op when off; append; `seq` monotonic within one `run_id`; a second open starts
  a new `run_id`; concurrent emits do not corrupt the JSONL.
- Key-set per kind: one test pins the exact `data` key set of each kind, so a node that
  stops returning a field turns the test red instead of silently shrinking the trace.
- **Per-worker chunks.** A fake run with two topics in one wave writes one `finding` line
  and one `[research tN]` status line per topic. The whole sink rests on `updates` yielding
  one chunk per `Send` worker; today only a one-topic run is covered.
- Tool emit: summary fields present; no snippet substring reaches the sidecar; one event
  per attempt for each outcome (ok / refused / disabled / error).
- `run_end`: written for a finished run, for the clarify-interrupt exit, and for the
  `thread already finished` exit, each with the right outcome.
- A fake run whose Exa client raises still writes one `finding` line carrying the gap text.
- Path validation: a `--thread-id` holding a separator and a `--trace-path` equal to
  `EXACT_DB` are both refused before the graph runs.
- Status: default vs verbose golden lines for plan / research / clarify / reflect / brief.
- CLI: flag precedence; path derivation from the `EXACT_DB` directory, including the bare
  default whose dirname is empty; resume appends the same file.
- **§1 questions.** One test reads the trace of a two-topic fake run — one topic failing —
  and answers both §1 questions from the file alone, with no checkpoint DB. This is what
  makes the §9 criterion checkable rather than aspirational.
- No live network; use [`tests/fakes.py`](../../tests/fakes.py).

Use the test-design skill when writing tests.

---

## 7. Non-goals

- Streaming model reasoning / extended thinking tokens.
- Full tool input/output or tool transcripts on checkpoint state.
- Always-on richer status without `--verbose`.
- Live tool crumbs on the CLI in v1.
- Eval harness, diff tools, or replay UI (sidecar is the foundation only).
- HTTP API / web UI.

---

## 8. Implementation order

1. Spec + architecture + `.env.example` + `traces/` gitignore (contract first). Freeze the
   envelope; mark the four new payloads provisional.
2. `trace.py` + run-scoped `Runtime` copy + CLI flags / path validation /
   `run_start` / `run_end` in a `finally`.
3. Test env isolation in `tests/fakes.py`, before any test can read a developer's `.env`.
4. CLI sink for the stage kinds; `_Bag.ingest` and scout `tool` emits.
5. `status.py` verbose path; keep default golden. **Blocked** until §6.4 names the target
   lines — today it names none.
6. Tests for tracer, sink, tool emits, key sets, status, CLI path/resume.
7. Run: `make check`.

---

## 9. Done when

- Default run (no flags) matches today’s CLI status and writes no sidecar.
- `--verbose` alone enriches plan/decision/parallel lines; no sidecar.
- `--trace` alone writes JSONL with all §4 kinds (on a full happy-path fake run) and prints
  the absolute `trace=…` after a successful open.
- A fake run whose Exa client raises still writes one `finding` line with the gap text, and
  one `tool` line with an error outcome.
- A fake run with two topics in one wave writes one `finding` line per topic.
- Every terminated run writes exactly one `run_end` per `run_id`, with the right outcome —
  including the clarify pause and the `thread already finished` exit.
- A `--trace-path` equal to `EXACT_DB` is refused before the graph runs.
- Both §1 eval questions are answerable from one trace file, with no checkpoint DB present.
- Parent state / updates still hold no raw tool I/O.
- Same `--thread-id` resume appends the existing JSONL under a new `run_id`.
- `make check` is clean on a machine whose `.env` sets `EXACT_TRACE=1`.
- Spec and architecture describe the contract.

---

## 10. Open points closed in this plan

| Topic | Decision |
| :--- | :--- |
| Primary job | Structured eval trace |
| CLI job | Light plan + decision enrichment |
| Persistence | Sidecar JSONL beside `EXACT_DB`, validated at startup |
| Tool detail | Summaries at `_Bag.call` + the `_Tools` early returns; one per attempt, with an outcome |
| Tool crumbs | Title plus URL, so a trace outlives its checkpoint DB |
| Isolation | Kept |
| Knobs | Independent `--trace` and `--verbose` |
| Emitters | CLI sink for stage kinds; `Runtime` tracer for `tool` |
| `report_refs` | From the CLI at `run_end`; `audit_citations` stays pure |
| Event kinds | All of §4 in v1; four payloads provisional |
| Ordering | `(run_id, seq)`; `ts` never breaks ties |
| Versioning | Integer `v`; additive keeps it, rename or removal raises it |
| Parallelism | Locked append for `tool` emits; interleaved; `topic_id`/`wave` |
| Resume | Append same file; new `run_id`; flags must be repeated |
| Completeness | `run_end` from a `finally`, with an outcome and a dropped-emit count |
| Default CLI | Unchanged without flags |
| Live tool stdout | Out of v1 |

---

## 11. Ideas considered and rejected

1. **Node-side emit for the stage kinds (the original hybrid).** Rejected in favour of the
   CLI sink. The sink reads the same `stream_mode=updates` chunks that `status.py` already
   formats, so it needs no `Runtime` on `ask_user` or `audit_citations` and no edits to
   the non-retrieval node files. Node-side emit is closer to the source of truth, and it would keep
   working for a caller that drives the graph without the CLI loop — but no such caller
   exists, and a batch harness and an HTTP API are both out of scope. The cost is recorded
   in §6.2: the sink can only see what a node returns on state, so the key-set test guards
   the shapes.
2. **Pushing tool events through the stream with `stream_mode="custom"`.** Not attempted.
   It is unverified whether `get_stream_writer()` reaches the ToolNode worker threads
   inside `create_agent` on the pinned langgraph 1.2.11, and locked decision 5 keeps tool
   detail off the parent path regardless. The `Runtime` tracer needs no such guarantee.
3. **Writing a throwaway trace reader before the spec step.** Rejected in favour of the two
   written eval questions in §1 plus the provisional marking in §4. The stage payloads
   mirror state channels the spec already contracts, so only four shapes are genuinely new,
   and the `v` field of §4 carries the drift that remains. A reader built before any eval
   exists would itself be the speculative work the repo rules forbid.
4. **Freezing the four new payload shapes in `docs/spec.md` at step 1.** Rejected: no consumer
   and no eval question existed when the shapes were drawn, so the first real eval query
   would churn the format before anything read it.
5. **A process-scoped tracer mutated onto the injected `Runtime`.** Rejected: `_bind`
   closes over one `Runtime` for every node, so the mutation would reach a caller's own
   object. §6.1 uses `dataclasses.replace` instead.
6. **Deferring an unwritable or dangerous trace path to the fail-soft handler.** Rejected:
   fail-soft turns a configuration error into one scrolled stderr line after model spend
   has started, and an append into `EXACT_DB` is not recoverable at all. §3 validates
   first.
