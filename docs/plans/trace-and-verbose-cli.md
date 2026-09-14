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

Isolation stays: the parent graph never sees raw research tool I/O. The tracer is a side channel. Tool events hold **summaries only** (name, args crumb, hit count, titles).

---

## 2. Locked decisions

1. Primary deliverable is the **sidecar trace**, not real-time spectacle.
2. CLI enrichment is light and **opt-in** via `--verbose`.
3. Trace lives in a **sidecar JSONL** file, not in checkpointed graph state.
4. Tool capture is **structured summaries** via pre/post wrappers — not full I/O.
5. Keep parent isolation; do not loosen it when tracing.
6. Two knobs: `--trace` / `EXACT_TRACE` and `--verbose` / `EXACT_VERBOSE` (either alone is valid).
7. Emitters are **hybrid**: stage/decision events from nodes; tool summaries from `_Bag` / scout wrappers into a `Runtime` tracer.
8. v1 includes **all** event kinds in §4.
9. Parallel workers: process-local lock, interleaved lines OK; events carry `topic_id` / `wave` when known.
10. Clarify resume with the same `thread_id` **appends** the same file (`run_start` may repeat).
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

**Default path:** `{dirname(EXACT_DB)}/traces/{thread_id}.jsonl`  
Example: `EXACT_DB=exact.sqlite` → `./traces/{thread_id}.jsonl`.

When `--trace` is on, CLI prints `trace=<path>` once next to `thread_id=…`. Create the `traces/` directory on first write. Add `traces/` to `.gitignore`.

---

## 4. Trace format

UTF-8 JSONL. One object per line. No pretty-print.

**Envelope (every line)**

| Field | Meaning |
| :--- | :--- |
| `ts` | UTC ISO-8601 |
| `thread_id` | LangGraph thread id |
| `seq` | Monotonic int for this process open of the file |
| `kind` | Event kind below |

**Kinds (v1 — all required)**

| Kind | Payload (structured) |
| :--- | :--- |
| `run_start` | query, flags (`trace`/`verbose`), optional resume marker |
| `run_end` | exit-relevant crumbs (e.g. dangling citation count), optional error summary |
| `decision` | clarify needed/skip; reflect continue/write + followups |
| `brief` | intent, must_cover, question |
| `plan` | wave, topic ids + queries |
| `agent` | role, model, node, optional `topic_id` / round |
| `tool` | name, args summary (query/url), `hit_count`, ≤N titles, optional error |
| `finding` | topic_id, claim count, source_ids, gaps |
| `report_refs` | cited `src_*` vs present-but-uncited ids |
| `usage` | Mirror existing usage event shape (counts/tokens only; no USD in file) |

**Hard rule:** never write full snippets, highlights bodies, or vendor JSON blobs into the sidecar.

**Title cap:** pick a small fixed N (recommend **5**, same as `max_hits` default) and document it in the spec.

---

## 5. Roles

```text
nodes / _Bag / scout  --emit-->  Runtime.trace  --append-->  traces/{thread_id}.jsonl
stream updates        --format-->  status.py     --print-->   CLI stdout
CLI wires flags / path; status never writes the sidecar.
```

| Role | Owns |
| :--- | :--- |
| Tracer | Only sidecar writer; no-op when trace off; lock; `seq` |
| Nodes / `_Bag` / scout | Emit events; never put raw tool I/O on parent state |
| `status.py` | Human lines only; verbose enriches plan/decisions |
| CLI | Flags, open/close tracer, print path, existing `stream_mode=updates` loop |

---

## 6. Code changes (by area)

### 6.1 Tracer

New small module (e.g. `src/exact/trace.py`):

- `NullTracer` / `JsonlTracer` behind one protocol.
- `emit(kind, **payload)` appends one envelope line under a threading lock.
- Construct from settings + `thread_id`; attach on `Runtime` (field or `extras["trace"]`).
- Fail soft on I/O errors: append to `errors` or log once — do not crash the research run. Prefer: record a single stderr warning and continue as no-op for that emit.

Files: new `src/exact/trace.py`; wire in [`src/exact/config.py`](../../src/exact/config.py).

### 6.2 Emitters (hybrid)

- **Scout** ([`nodes/scout.py`](../../src/exact/nodes/scout.py)): `tool` summaries for Exa/Elicit scout calls; no raw hits in the event.
- **Clarify / brief / plan / reflect / write / audit:** emit `decision`, `brief`, `plan`, `agent`, `report_refs` at node boundaries (after structured results exist).
- **Research** ([`nodes/research.py`](../../src/exact/nodes/research.py)): pre/post around `_Bag.note` / `_Bag.call` for `tool`; `agent` for research + compress; `finding` after prune.
- **Usage:** emit `usage` when usage events are already produced (mirror; do not recompute cost).
- **CLI:** `run_start` at start; `run_end` before exit.

Do **not** route tool detail through `stream_mode=updates` or parent state.

### 6.3 CLI

File: [`src/exact/cli.py`](../../src/exact/cli.py).

- Add `--trace`, `--verbose`, `--trace-path`.
- Resolve knobs; build tracer; pass into `Runtime`.
- Print `trace=…` when tracing.
- Pass a verbose flag into `format_update` (or a thin CLI wrapper). Keep the updates loop.

### 6.4 Status (verbose)

File: [`src/exact/status.py`](../../src/exact/status.py).

When verbose:

- Plan: wave header + indented topics (tighten grouping).
- Research: always show wave/topic so parallel workers read cleanly.
- Decisions: clarify needed/skip; reflect continue/write + followups; brief one-liner.

When not verbose: **bit-identical** to today’s lines (golden tests).

No live `[tool …]` stdout lines in v1.

### 6.5 Docs (same change)

- [`docs/spec.md`](../spec.md): flags, path, kinds, summary-only rule, isolation, resume append.
- [`docs/architecture.md`](../architecture.md): tracer role, hybrid emit, status vs sidecar.
- [`.env.example`](../../.env.example): `EXACT_TRACE=0`, `EXACT_VERBOSE=0`, optional `EXACT_TRACE_PATH`.
- [`.gitignore`](../../.gitignore): `traces/`.
- Short README note if the README already documents CLI flags.

Use ASD-STE100 in plan/spec prose.

### 6.6 Tests

- Tracer: no-op when off; append + monotonic `seq`; concurrent emits do not corrupt JSONL.
- Tool wrapper: summary fields present; raw body absent.
- Status: default vs verbose golden lines for plan / research / clarify / reflect / brief.
- CLI: flag precedence; path derivation from `EXACT_DB`; resume appends same file.
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

1. Spec + architecture + `.env.example` + `traces/` gitignore (contract first).
2. `trace.py` + Runtime injection + CLI flags / path / `run_start`/`run_end`.
3. Hybrid emitters: nodes + `_Bag`/scout pre/post summaries.
4. `status.py` verbose path; keep default golden.
5. Tests for tracer, wrappers, status, CLI path/resume.
6. Run: `make check`.

---

## 9. Done when

- Default run (no flags) matches today’s CLI status and writes no sidecar.
- `--verbose` alone enriches plan/decision/parallel lines; no sidecar.
- `--trace` alone writes JSONL with all §4 kinds (on a full happy-path fake run) and prints `trace=…`.
- Parent state / updates still hold no raw tool I/O.
- Same `--thread-id` resume appends the existing JSONL.
- Spec and architecture describe the contract.
- `make check` is clean.

---

## 10. Open points closed in this plan

| Topic | Decision |
| :--- | :--- |
| Primary job | Structured eval trace |
| CLI job | Light plan + decision enrichment |
| Persistence | Sidecar JSONL beside `EXACT_DB` |
| Tool detail | Summaries only (pre/post wrappers) |
| Isolation | Kept |
| Knobs | Independent `--trace` and `--verbose` |
| Emitters | Hybrid (nodes + bag/scout → tracer) |
| Event kinds | All of §4 in v1 |
| Parallelism | Locked append; interleaved; `topic_id`/`wave` |
| Resume | Append same file; `run_start` may repeat |
| Default CLI | Unchanged without flags |
| Live tool stdout | Out of v1 |
