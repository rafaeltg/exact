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
| `--verbose` | Add detail lines under the brief, research, reflect and audit status lines (§6.4) |

Default status lines stay as they are today. Live “CoT theater” is not a requirement.

Isolation stays: the parent graph never sees raw research tool I/O. The tracer is a side channel. Tool events hold **summaries only** (name, args crumb, hit count, and one crumb per minted source: `src_*` id, title, URL, DOI).

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
   explicit outcome (`ok` / `refused` / `error`) — not full I/O, and not a pre/post pair
   around `note` / `call`. The seam is `_Bag.call` plus the one early return in
   `_Tools.exa_highlights` (§6.2). No other early return exists in `_Tools`.
5. Keep parent isolation; do not loosen it when tracing.
6. Two knobs: `--trace` / `EXACT_TRACE` and `--verbose` / `EXACT_VERBOSE` (either alone is
   valid). `--trace-path` / `EXACT_TRACE_PATH` only moves the file. It never switches
   tracing on.
7. Emitters are **split by source of truth**: a CLI-side sink on the existing
   `stream_mode=updates` loop derives every stage kind; a `Runtime` tracer emits `tool`
   only, from `_Bag` and the scout legs.
8. v1 includes **all** event kinds in §4.
9. Parallel workers: a process-local lock guards **every** emit and the `seq` it takes.
   The sink emits on the CLI thread while the workers emit `tool` events from their own
   threads, so the two write concurrently during a wave. Interleaved lines are acceptable.
   Every payload that names a topic carries `topic_id` and `wave` side by side (§4).
10. Clarify resume with the same `thread_id` **appends** the same file. Each open starts a
    new `run_id` and a new `seq` series (§4).
11. Default CLI (no flags) is **unchanged**.
12. `--trace` and `--verbose` are **CLI-scoped**. They reach an injected `Runtime`, unlike
    `--effort`. The tracer is built by the CLI and copied onto the runtime with
    `dataclasses.replace` (§6.1), so no setting inside the runtime has to change. The
    `docs/spec.md` sentence “An injected `Runtime` carries its own settings, so the flag
    does not reach it” stays true for `--effort` only.

---

## 3. Controls and paths

**Surface**

| Knob | CLI | Env | `Settings` field | Default |
| :--- | :--- | :--- | :--- | :--- |
| Trace | `--trace` / `--no-trace` | `EXACT_TRACE` | `exact_trace: bool` | off |
| Verbose | `--verbose` / `--no-verbose` | `EXACT_VERBOSE` | `exact_verbose: bool` | off |
| Trace path | `--trace-path PATH` | `EXACT_TRACE_PATH` | `exact_trace_path: str` (empty = derived) | derived (below) |

**Precedence:** CLI flag > env > default. The three knobs are `Settings` fields, like every
other knob. The env half of the rule therefore reads `runtime.settings`, which is also how
an injected `Runtime` (§2.12) supplies its values. The CLI half uses
`argparse.BooleanOptionalAction` with `default=None`: `None` means “fall to the field”, so
`--no-trace` overrides `EXACT_TRACE=1`. The two booleans accept the pydantic bool set
(`0`/`1`, `true`/`false`, `yes`/`no`, `on`/`off`); the docs recommend `0`/`1`. A value
outside that set is CLI misuse: `_resolve_settings` today re-raises every
`ValidationError` that is not on `exact_effort`, so `EXACT_TRACE=maybe` would print a
pydantic traceback. Extend that mapping so an invalid `EXACT_TRACE` or `EXACT_VERBOSE`
exits `1` with `EXACT_TRACE must be a boolean such as 0 or 1; got 'maybe'` on stderr,
like the effort message. A `--trace-path` or `EXACT_TRACE_PATH` while tracing is off is
ignored, except by warning W1 below.

**Default path:** the `traces/{thread_id}.jsonl` child of the directory that holds
`EXACT_DB`. **Join the parts; do not interpolate a string.** `EXACT_DB` defaults to the
bare `exact.sqlite`, whose dirname is empty, so `{dirname(EXACT_DB)}/traces/…` would yield
the absolute `/traces/…`. Example: `EXACT_DB=exact.sqlite` → `./traces/{thread_id}.jsonl`.
A relative `EXACT_DB` or `--trace-path` resolves against the current working directory at
startup, so a resume from another directory lands elsewhere; warning W2 reports that.

**Validation, before any model spend.** Resolve and open the path once at startup. Fail
loud — do not defer these to the fail-soft path of §6.1. Each refusal raises
`SystemExit(message)`: exit code `1`, message on stderr, nothing on stdout. This matches
the other CLI misuse exits in `docs/spec.md` §8.

- Refuse a `--thread-id` that cannot be a file name **when the path is derived**. The rule:
  the id holds `/` or `\`, or the id is `.` or `..`. The id becomes a file name only in
  that case; an explicit `--trace-path`, or a run with tracing off, must keep accepting the
  thread ids that are valid today.
- Refuse a path equal to `EXACT_DB`. Compare the two paths after `Path.resolve()` with
  `strict=False` — the DB file may not exist yet on a first run. An append into the
  SqliteSaver file corrupts the checkpoint irreversibly.
- Refuse an unwritable target, or a target directory that cannot be created.

Create the parent directory during this startup step, not on first write — for the
derived `traces/` and for an explicit path alike. Add `traces/` to `.gitignore`. When the
open succeeds, the CLI prints the **absolute** resolved path once as `trace=<path>`, on the
line after `thread_id=…` and before the effort guard. `docs/spec.md` §8 pins the start
order (“the `thread_id=` line, then the guard, then the echo line”); the same change edits
that sentence to “the `thread_id=` line, then `trace=` when tracing is on, then the guard,
then the echo line”. The CLI prints nothing before the open succeeds.

**Accepted consequence.** The open runs before `build_graph`, so it runs before the effort
guard. An `effort mismatch` exit therefore leaves the file open-and-empty (or, on a resume,
unchanged). No line is written (§6.2), and an empty file is not an error for any consumer.

**Resume carries no trace config.** Neither the state nor the checkpoint holds the flags
or the path, so a resumed run must repeat them. The CLI prints one warning, and continues,
in either direction of the mistake:

- **W1.** Tracing is **off**, `--thread-id` is given, and the resolved path (derived or
  configured) already exists. The operator dropped the flag, and this resume writes
  nothing into a file that holds the earlier turns. Name the file in the warning.
- **W2.** Tracing is **on**, `--thread-id` is given, the thread **exists in the
  checkpoint** (`snap.values` or `snap.next`), and the resolved path did **not** exist
  before this run opened it. The operator kept `--trace` but dropped `--trace-path`, or
  changed directory, so this resume starts a second file and one thread's turns land in
  two places. The first run of a new named thread has no checkpoint, so it gets no
  warning.
- **W3.** Tracing is **on** and the resolved path holds lines for a different `thread_id`.
  The operator reused a path. The check reads the **first line only**, through a separate
  read-mode handle opened before the append handle — an append handle cannot read. A first
  line that is not JSON, or has no `thread_id`, keeps the CLI silent.

These warnings go to **stderr**. W1 can fire on a run with no `--trace`, so it is the
single exception to “default CLI unchanged” (§2.11) — stdout still matches today's lines
byte for byte.

**Sequence matters.** An append-mode open creates the file, so the CLI records whether the
path existed **before** the open. W2 also needs the checkpoint snapshot, which exists only
after `build_graph` and `app.get_state`. §6.3 gives the full order.

**Exact texts.** Test assertions pin these strings:

```text
trace=<absolute path>                                              (stdout)
warning: trace off; <path> holds earlier turns of this thread     (W1, stderr)
warning: thread <id> resumes, but <path> did not exist; pass the same --trace-path as the first run   (W2, stderr)
warning: <path> holds lines for thread <other>; this run is thread <id>   (W3, stderr)
```

---

## 4. Trace format

UTF-8 JSONL. One object per line. No pretty-print. Flush after each line, so a run that
dies mid-way keeps every line it emitted. Encode with `json.dumps(obj, ensure_ascii=False)`
and write UTF-8 bytes, so a non-ASCII title stays readable.

**Envelope (every line)**

| Field | Meaning |
| :--- | :--- |
| `v` | Integer format version. Starts at `1` |
| `ts` | `datetime.now(UTC).isoformat(timespec="microseconds")`. Always six fractional digits and the `+00:00` suffix |
| `run_id` | `str(uuid.uuid4())` for this open of the file |
| `thread_id` | LangGraph thread id |
| `seq` | Monotonic int within this `run_id`. Starts at `1` |
| `kind` | Event kind below |
| `data` | Object holding the whole payload |

**Canonical order is `(run_id, seq)`.** A resumed file holds several `run_id` values and
several `seq=1` lines. `ts` does not break ties between parallel workers, so a consumer
must not sort by it. Runs inside one file are ordered by the **first appearance** of each
`run_id` in file order; a UUID4 does not sort by time, and Python 3.12 and 3.13 have no
`uuid.uuid7`.

**Version rule.** An added field keeps `v`. A renamed or removed field raises it. The
`usage` payload fields are enumerated in `docs/spec.md`, not defined by reference to the
internal `usage.py` dict, because those keys have already changed once (commit `2d29acf`).

**The whole payload sits under `data`.** No payload field can then shadow an envelope
field. This is not cosmetic: the existing usage events carry their own `kind` key (`llm`,
`exa_search`), so a flat `emit(kind, **payload)` would raise `TypeError` during argument
binding — outside the reach of the fail-soft handler inside `emit`.

**Every key is always present.** A value that is unknown or not applicable is `null`.
No payload key is optional-by-absence. This is what lets one test pin the exact key set of
each kind (§6.6). The tables below list every key.

**`topic_id` and `wave` travel together.** Every payload that names a topic carries both.
`wave` is the integer the emitter parses from the `t{wave}_{i}` topic id with one helper;
the topic id grammar is not a contract in `docs/spec.md`, so a consumer must not parse it.
`wave` is `null` when `topic_id` is `null` or `"scout"`. `topic_id` is `"scout"` on every line
the scout node produces — its `tool` lines and the `usage` lines of its chunk —
and `null` on the lines of every other non-research node.

**Kinds (v1 — all required)**

| Kind | `data` keys |
| :--- | :--- |
| `run_start` | `query`, `verbose` (bool), `resume` (bool), `settings` (below). No `trace` key: a `run_start` exists only when tracing is on |
| `run_end` | `outcome`, `dangling` (int, `null` unless `finished`), `dropped` (int), `error` (string or `null`) |
| `decision` | `stage` = `clarify`: `stage`, `needed` (bool). `stage` = `reflect`: `stage`, `continue` (bool), `followups`, `uncovered`. One kind, two pinned key sets, discriminated by `stage`. `reflect` omits `followups` from its chunk on the done and cap-exit paths; the line then carries `[]`, not `null`, because “none” is known |
| `brief` | `intent`, `must_cover`, `question` |
| `plan` | `wave` (the chunk's `iteration`, as `status._plan` reads it), `topics` — a list of `{id, query, focus}`; an empty list is still one line |
| `tool` | `name`, `outcome`, `topic_id`, `wave`, `query`, `url`, `hit_count`, `sources`, `error` |
| `finding` | `topic_id`, `wave`, `claims` (int count), `source_ids`, `gaps` |
| `report_refs` | `cited`, `uncited` — both sorted unique lists of `src_*` ids |
| `usage` | The `docs/spec.md` §7b event fields — `kind`, `node`, `role`, `model`, `input_tokens`, `output_tokens`, `cache_read`, `cache_creation`, `calls` — plus `topic_id`, `wave`. One line per event. A vendor tool event carries only `kind`, `node` and `calls`, so its `role`, `model` and four token keys are `null`, not `0`; a consumer that sums tokens filters on `kind == "llm"`. Counts and tokens only; no USD in the file |

The payloads of `brief`, `plan`, `decision` and `finding` mirror state channels that
`docs/spec.md` already contracts, so they are stable. The three new shapes — `tool`,
`run_start` / `run_end`, `report_refs` — are marked **provisional** in the spec until the
§1 questions are answered against a real trace. The envelope is not provisional. There is
no `agent` kind: a `usage` line whose `kind` is `llm` already carries `node`, `role`,
`model`, `topic_id` and `wave`, so an `agent` line would repeat it (§11.11).

**`tool` payload detail.** `query` is set for a search, `url` for a highlights read; the
other one is `null`. `hit_count` is `len(found)` on `ok`, and `null` on `refused` and
`error`. A highlights read counts its content rows under the same rule; a consumer that
sums hits per topic filters on `name`. `sources` is the crumb list, empty on `refused` and
`error`. `error` is `str(exc)` cut to 500 characters on `error`, else `null`. That text is
the same text the `errors` channel already carries and stdout already prints under
`## Errors`; the redaction rule below covers `Settings` fields, not vendor messages.

**Crumb.** `{id, title, url, doi}`. `url` may be `null`: a publication hit can carry a DOI
and no URL (`Source.url` is `str | None`). The crumb therefore carries `doi` too, and the
join invariant of §9 reads “a URL or a DOI”.

**`decision` detail.** The sink writes one `clarify` decision per `decide_clarify` chunk and
one `reflect` decision per `reflect` chunk. `ask_user` writes no `decision` line, although
its chunk also carries `clarify_needed`: the sink keys on the node name, never on a field.
`audit_citations` writes no line at all; its dangling count reaches the trace through
`run_end.dangling`.

**`report_refs` detail.** `cited` is `sorted(set(audit.cited_ids(result["final_report"])))`;
`uncited` is the sorted set of `sources[*].id` not in `cited`. The report the CLI holds is
the one `audit_citations` already rewrote with an `## Audit` block. That block only repeats
ids the body already cites, so after the set operation it adds nothing. A dangling id is
therefore present in `cited` and absent from `sources`; a consumer derives the dangling set
as `cited − sources`, and `run_end.dangling` gives the count. The join invariant of §9
excludes a dangling id by construction: it names no source, so no crumb can hold it.

**`run_start.settings` snapshot.** Two groups, both required:

- The eight keys of `effort_snapshot(settings, snap.values or seed)` — the same call that
  feeds the `effort=` echo line, so thread-scoped caps come from the checkpoint on a
  resume and process-scoped caps from the current `Settings`.
- `models` (per role: `router`, `research`, `compress`, `write`, each the resolved id),
  `max_tokens` (per role), `temperature`, `reasoning_effort`, `thinking_budget`. These
  are the **configured** `Settings` values, not the effective request kwargs:
  `chat_kwargs` rewrites `temperature` and `max_tokens` when thinking is on, and
  `thinking_budget` in the same snapshot tells the reader that it did. Question 2 of §1
  asks about settings deltas, so the configured value is the right one.

Without it, two traces that differ only by `EXACT_THINKING_BUDGET` are indistinguishable
and question 2 of §1 has no answer. **Redaction rule:** never write an API key or any
`Settings` field whose name ends in `_api_key`. State the rule in the spec beside the
summary-only rule. `resume` is `bool(snap.next)`.

**`run_end` outcome** is one of `finished` / `interrupted` / `rejected` / `error`. §6.3
gives the mapping. A dangling-citation run exits `1` but its outcome is `finished`; the
`dangling` count says why. A line with no `run_end` for its `run_id` means the process died
or the tracer went dark — state that reading in the spec, because a truncated run otherwise
scores as a complete one. `report_refs` precedes `run_end`; `run_end` is the last line of
its run.

**Hard rule:** never write full snippets, highlights bodies, or vendor JSON blobs into the
sidecar. An id, a title, a URL and a DOI are crumbs, not bodies.

**The crumb carries the `src_*` id, because the id is the join key.** `finding.source_ids`
and `report_refs` hold `src_*` ids, and those ids resolve to a URL only through the
`sources` channel inside the disposable `exact.sqlite`. A crumb list of titles and URLs
alone therefore leaves both kinds unresolvable once the checkpoint DB is deleted or moved.
`_Bag.ingest` mints the id (`src_{topic_id}_{i}`) in the same call that the `tool` event
reports, so the id is free at that seam.

**`Finding.source_ids` holds minted ids only.** `Finding.source_ids` is LLM output.
Today `_prune` overwrites `topic_id` on the parsed `Finding` and nothing else, so a
compress model can return an id that no crumb minted, and the join invariant of §9 would
fail on a real run while the fake (which hardcodes a matching id) passes. `_prune` now
also drops every `source_ids` entry that is not an id in `collected`, in the same place it
sets `topic_id`. This is a node behaviour change outside the trace scope, decided on
2026-09-18 because the invariant is worthless without it; `docs/spec.md` §7 records it on
the `research_agent` row (§6.5).

**One crumb per minted source — no cap below `max_hits`.** A cap truncates the crumb list
while `finding.source_ids` keeps every id, which breaks the join for the tail. `max_hits`
already bounds an attempt (5 by default, 8 under the `max` profile), so the crumb list is
short without a second limit. A hit that the prior-title dedupe drops mints no id and gets
no crumb; `hit_count` still records it.

**`hit_count` means the raw hit count of the attempt, before prior-title dedupe.** Define
it that way in the spec. The deduplicated count is the length of `sources`.

---

## 5. Roles

```text
stream updates  --sink-->    tracer  --append-->  traces/{thread_id}.jsonl
                --format-->  status.py  --print-->  CLI stdout
_Bag / scout    --emit-->    Runtime.tracer  --append-->  same file (under lock)
CLI wires flags / path, validates, opens and closes the tracer.
```

| Role | Owns |
| :--- | :--- |
| Tracer | Only sidecar writer; no-op when trace off; lock; `run_id`; `seq`; flush |
| CLI sink | Derives `decision`, `brief`, `plan`, `finding`, `usage` from the chunks the status loop already reads. The CLI emits `run_start`, `run_end`, `report_refs` outside the loop |
| `_Bag` / scout | Emit `tool` summaries; never put raw tool I/O on parent state |
| `status.py` | Human lines only; verbose adds the §6.4 detail lines; never writes the sidecar |
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
  The field is `tracer` with `default_factory=NullTracer`, so `fakes.runtime()` and every
  direct `Runtime(...)` construction keep working unchanged.
- Close the tracer in a `finally`, and emit `run_end` from that same `finally`.
- Fail soft after the startup validation of §3. The handler inside `emit` catches
  `Exception` around **both** the serialization and the write: a `TypeError` from an
  unserializable value and an `OSError` from the disk are the same dropped emit. The first
  drop of a run prints one stderr warning
  (`warning: trace write failed: <exc>; later failures are counted in run_end`); later
  drops only count. The count goes into `run_end.dropped`. A `run_end` that drops takes the
  count with it; a missing `run_end` already reads as “the process died”, so that loss is
  accepted.
- The lock is process-local. Two processes on one path can interleave lines. One process
  per thread is already the SqliteSaver assumption, so no file lock is added.

Files: new `src/exact/trace.py`; wire in [`src/exact/config.py`](../../src/exact/config.py).
`config.py` imports `trace.py` for the `default_factory`, so `trace.py` imports nothing
from `exact`; `make imports-check` fails on a cycle. The tracer is pure stdlib: `json`,
`threading`, `uuid`, `datetime`, `pathlib`.

### 6.2 Emitters

**CLI sink (every kind except `tool`).** The `stream_mode=updates` loop in
[`cli.py`](../../src/exact/cli.py) already yields the state deltas that
[`status.py`](../../src/exact/status.py) formats. One sink beside `format_update` derives
the stage kinds from the same chunks. This needs no new node bindings — no `Runtime` on
`ask_user` or `audit_citations` — and no edits to the non-retrieval node files.
`research.py` and `scout.py` are still edited, for `tool`.

The sink does two jobs on every chunk `{node: update}`:

- **Node-keyed kinds.** `decide_clarify` → `decision(stage=clarify)`; `generate_brief` →
  `brief`; `plan_topics` → `plan`; `research_agent` → `finding`; `reflect` →
  `decision(stage=reflect)`. `scout`, `ask_user`, `write_report` and `audit_citations` map
  to no stage kind. A node whose name starts with `__` (such as `__interrupt__`) is skipped,
  exactly as `format_update` skips it; the clarify pause is visible through
  `run_end.outcome=interrupted`.
- **Node-agnostic `usage`.** Every chunk that carries a `usage` list yields one `usage`
  line per event in that list. `research_agent` returns loop, bag and prune usage in one
  chunk, so one chunk can yield many lines. `run_end` never dumps totals: the parent append channel
  re-accumulates the same events, so a second emit would double-count.

Notes on the derivations:

- `finding` comes from the chunk itself, so the zero-source branch is covered for free:
  `research.py` returns `_empty_finding` before `_prune` runs when `bag.collected` is
  empty, and that return still puts one `Finding` on `findings`. Retrieval failure is a
  graph invariant, so this branch is a real path, not an edge case. `covered` is not
  written; the four keys of §4 are enough for both §1 questions.
- `topic_id` for a `research_agent` chunk is `findings[0]["topic_id"]`, as `status._research`
  already reads it. `updates` yields **one chunk per `Send` worker**, in arbitrary order,
  each with exactly one finding. A throwaway probe on a three-topic fake run showed this
  on 2026-09-18; no committed test shows it yet, and the §6.6 per-worker test is what makes
  it permanent. For the scout node `topic_id` is `"scout"`; for every other node it is
  `null`.
- The sink lives in `_stream`, which both the fresh-run path and the clarify-resume path
  call. A sink placed only on the fresh-run path would lose every resumed turn.
- A **failed** LLM call returns no usage event: `decide_clarify`, `generate_brief`,
  `plan_topics` and `reflect` all fall back without one when the structured call raises.
  The sink therefore writes no `usage` line for that call — the run most worth tracing. v1 accepts this and states it in the spec. To close it, those fallbacks
  must return a usage event, which is a node change and is out of this scope.
- No line carries a tool-round index. No return value has one, and the `max_tool_rounds`
  budget consumed is not on state.
- `report_refs` is emitted from the CLI after `_run` returns with outcome `finished`, from
  `audit.cited_ids(result["final_report"])` against `result["sources"]` (§4 gives the set
  rule). A second extraction path inside an emitter would drift from the audit whose
  `dangling:` entries drive the exit code. No other outcome has a `final_report` to read.
- `run_start` is emitted after every startup refusal has passed: the §3 validation, the
  first `app.get_state(config)` (its `resume` flag is not knowable before that call), and
  `_guard_effort`. An `effort mismatch` exit therefore writes no line. The one refusal that
  comes **after** `run_start` is `thread already finished`, which maps to `rejected`.

The sink reads what the nodes return on state. A node that stops returning a field loses
its event silently, so the key-set test of §6.6 guards the shapes.

**`Runtime` tracer (`tool` only).** `research_agent` and `scout` are already bound to
`Runtime`, so no new **node** binding is needed. `_Bag` and `_Tools` do gain a tracer
argument.

- **Research** ([`nodes/research.py`](../../src/exact/nodes/research.py)): no single
  existing method sees a whole attempt, so the emit needs two places and one new return
  value:
  - **`_Bag.call`** owns the label and the `try` / `except`, so it owns the `ok` and
    `error` events. It needs two inputs it does not have today. First, the args: `call`
    receives only `label` and `fetch`, and only `note` sees the `{"query": …}` or
    `{"url": …}` dict, so `call` gains the same `args` parameter and fills `tool.query` /
    `tool.url` from it. Second, the result: `ingest` must hand it the raw hit count
    (`len(found)`, before the prior-title dedupe) and the minted sources' ids, titles,
    URLs and DOIs; today `ingest` returns only a compacted string, so it gains a structured
    return beside it.
  - **`_prune`** drops every `source_ids` entry the compress model returned that is not an
    id in `collected` (§4). One filter, beside the `topic_id` overwrite.
  - **`_Tools.exa_highlights`** owns the one attempt that never reaches `call`: it returns
    its refusal before `note` when the URL is not a retrieved source. It emits the
    `refused` event itself. `exa_publication_search` has no early return: it calls `note`
    then `call` like every search, and `_Tools.as_list` gives a topic only the search tool
    of its lane.

  A pre/post pair around `note` / `call` would both invent and drop events here, and the
  obvious post-hook would write snippet bodies. `_Bag.ingest` alone cannot carry the event:
  it receives only the source list — no tool name, no args, no outcome — and `call` reaches
  it only after `fetch()` returns, so it is unreachable on two of the three outcomes.
  `_Bag` and `_Tools` therefore take the tracer as a new constructor argument.

  Two divergences are intended and go in the spec. First, `_Bag.call` appends a usage event
  only on success, so a failed attempt has a `tool` line and no `usage` line: `usage`
  meters billable calls, `tool` records attempts. Second, `_run_agent` catches a
  loop-level exception and writes `research loop: …` to `errors` with no tool attempt; that
  topic then has a `finding` with `lane <focus>: retrieval failed` and **no** `tool` line,
  and that absence is the reading: the loop died before any attempt.
- **Scout** ([`nodes/scout.py`](../../src/exact/nodes/scout.py)): one `tool` event per Exa
  leg that ran — `exa_search` always, `exa_publication_search` when `academic_signal` is
  true. There is no Elicit leg. The `src_scout_*` ids are minted after `_interleave`, so the
  node emits **after** the id loop; the leg's hit dicts are mutated in place, so each leg
  still knows its own rows. `topic_id` is the literal `"scout"`, `wave` is `null`,
  `hit_count` is `len(leg.hits)` (the scout has no prior-title dedupe). A failed leg emits
  `error` with the message `_leg` already builds.

Do **not** route tool detail through `stream_mode=updates` or parent state.

### 6.3 CLI

File: [`src/exact/cli.py`](../../src/exact/cli.py).

- Add `--trace` / `--no-trace`, `--verbose` / `--no-verbose` (both
  `BooleanOptionalAction`, `default=None`) and `--trace-path`.
- Resolve the three knobs: flag, else `runtime.settings` field, else default (§3).
- Pass a verbose flag into `format_update` as a keyword-only parameter with a default:
  `format_update(node, update, *, verbose=False)`. The positional callers in
  `tests/test_status.py` keep working. Keep the updates loop.
- Wrap the run in `try` / `except` / `finally`. A `finally` cannot see why the block ended,
  so the `except` clauses classify and re-raise, and the `finally` emits `run_end` and
  closes the tracer.

**Startup order.** The order below is the contract; §3 and §4 depend on it.

1. Parse args. Resolve settings and the runtime as today.
2. Resolve `trace`, `verbose`, `trace_path`. Derive `thread_id`.
3. If tracing is on: resolve the path against the CWD; when the path is derived, refuse
   an explicit `--thread-id` that cannot be a file name (§3); refuse a path equal to the
   resolved `EXACT_DB`; record `existed = path.exists()`; read the first line for W3 when
   it exists; create the parent directory; open in append mode. Any failure is a
   `SystemExit` before any stdout line. If tracing is off: only record whether the
   resolved path exists, for W1.
4. `build_graph(replace(runtime, tracer=tracer), …)`. `app.get_state(config)`.
5. Print `thread_id=…`, then `trace=…` when tracing is on.
6. Print W1, W2 or W3 to stderr when its condition holds (W2 needs `existed` and `snap`).
7. `_guard_effort` (a `SystemExit` here writes no trace line).
8. Print the `effort=` echo line. Emit `run_start`.
9. **Open the `try` here, after `run_start`.** A `try` that starts earlier would write a
   `run_end` with no `run_start` on an effort mismatch. Run, classify, emit `report_refs`
   on `finished`, print the report, emit `run_end`, close.

`main` today is one function of sixteen lines. These nine steps do not fit under the
complexity budget as one unit, and `make complexity-pre` denies the write before disk.
Split the startup into named units first — for example one that resolves and opens the
trace, one that prints the start lines and warnings, one that classifies the outcome —
each with its own reason to exist (AGENTS.md, repair order step 3).

**Outcome mapping** (step 9):

`_run` returns `snap.values`, not the snapshot, so the first two rows need one more
`app.get_state(config)` after `_run` returns. That call is cheap and keeps `_run` as it
is.

| How `main` ends | `outcome` | `error` |
| :--- | :--- | :--- |
| `_run` returns and `app.get_state(config).next` is empty | `finished` | `null` |
| `_run` returns and `.next` is set (the clarify pause returns normally) | `interrupted` | `null` |
| `KeyboardInterrupt` (a `BaseException`; a bare `except Exception` never sees it) | `interrupted` | `null` |
| `SystemExit` after `run_start` — only `thread already finished` can reach here | `rejected` | the exit message |
| Any other exception | `error` | `f"{type(exc).__name__}: {exc}"` cut to 500 characters |

`dangling` is the count of `uncovered` items that start with `dangling:` on `finished`
(the same test `_qa_exit` runs), else `null`.

### 6.4 Status (verbose)

File: [`src/exact/status.py`](../../src/exact/status.py).

**What verbose adds.** Every item the original plan called “verbose” is already in the
default output: `format_plan` prints the wave header and the topic lines, `_research`
prints the topic id, `_decide_clarify`, `_reflect` with its followups and `_brief` with
its question line all print today. One constraint bounds what verbose can add:
`format_update` sees only what a node returns on state, and §6.2 forbids edits to the
non-retrieval node files. `PlanDecision.reason`, `ClarifyDecision.rationale` and any
reflect reasoning never reach state, so verbose cannot print them in v1. Verbose therefore
prints what the chunks carry and the default lines fold into a count. It adds **detail
lines** under four default lines, each indented two spaces, one item per line, in the
order the state list holds them (decided 2026-09-18):

| After the default line | Detail lines | Source |
| :--- | :--- | :--- |
| `[brief] intent=…  must_cover=N` and its question line | `- {item}` per `must_cover` item | `brief.must_cover` |
| `[research tN] …` | `gap: {gap}` per gap, then `error: {error}` per distinct error, first occurrence order | `findings[0].gaps`, `errors` through `dict.fromkeys` |
| `[reflect] continue` / `write` and its followups | `uncovered: {item}` per item | `uncovered` |
| `[audit] …` | `dangling: {id}` per dangling id, in `uncovered` order, the `dangling:` prefix stripped | `uncovered` items that start with `dangling:` |

`[scout]`, `[clarify]`, `[plan]` and `[write]` have no verbose delta. The wave is already
the `t{wave}_` prefix of every research line, so “wave and topic id on every research
line” adds nothing.

Shape: `format_update(node, update, *, verbose=False)` runs the default handler, then,
when verbose, appends the lines of a second per-node table of detail functions. The
default handlers do not change, so the default output stays **bit-identical** to today’s
lines (golden tests), and each detail function has its own reason to exist.

No live `[tool …]` stdout lines in v1.

### 6.5 Docs (same change)

- [`docs/spec.md`](../spec.md): flags, the three `Settings` fields, path and its
  validation, the start-line order sentence in §8 (now with `trace=`), envelope, kinds and
  their key sets, which payloads are provisional, the version rule, the summary-only and
  redaction rules, the two intended `tool` / `usage` divergences, isolation, resume append
  and `(run_id, seq)` order; on the §7 `research_agent` row, that `Finding.source_ids`
  holds minted ids only; the four verbose detail line groups of §6.4.
- [`docs/architecture.md`](../architecture.md): tracer role, CLI sink vs `Runtime` tracer,
  status vs sidecar.
- [`.env.example`](../../.env.example): `EXACT_TRACE=0`, `EXACT_VERBOSE=0`, optional
  `EXACT_TRACE_PATH`.
- [`.gitignore`](../../.gitignore): `traces/`.
- Short README note if the README already documents CLI flags.
- `Makefile`: no change.

Use ASD-STE100 in plan/spec prose.

### 6.6 Tests

- **Env isolation first.** [`tests/fakes.py`](../../tests/fakes.py) already builds
  `Settings(_env_file=None, **settings)`, so `.env` cannot reach a fake runtime. The
  **process** environment can: a developer who exports `EXACT_TRACE=1` for daily use would
  fail the golden status tests and have fake runs write `traces/` into the repo, where
  `.gitignore` hides them. `tests/test_cli.py` already deletes `_KNOB_ENV_NAMES` from the
  environment in a module-level autouse fixture; add `EXACT_TRACE`, `EXACT_VERBOSE` and
  `EXACT_TRACE_PATH` to that tuple, and give every CLI trace test an explicit
  `--trace-path` under `tmp_path`. That one module is enough because of an invariant
  the implementation must keep: **only `cli.main` reads `exact_trace`, `exact_verbose`
  and `exact_trace_path`.** `Runtime.tracer` never derives from `Settings`, and
  `format_update` gets `verbose` as an argument, so a fake runtime built in
  `test_status.py` or `test_graph.py` under a shell export still traces nothing and
  prints the default lines. Without this, `make check` is machine-dependent.
- Tracer: no-op when off; append; `seq` monotonic within one `run_id`; a second open starts
  a new `run_id`; concurrent emits do not corrupt the JSONL; an unserializable payload is
  one dropped emit, one stderr warning, and a `run_end.dropped` of 1.
- Key-set per kind: one test pins the exact `data` key set of each kind — and of each
  `decision.stage` — so a node that stops returning a field turns the test red instead of
  silently shrinking the trace.
- **Per-worker chunks.** A fake run with two topics in one wave writes one `finding` line
  and one `[research tN]` status line per topic. `updates` yielding one chunk per `Send`
  worker is verified today; this test keeps it verified.
- Tool emit: summary fields present; no snippet substring reaches the sidecar; one event
  per attempt for each outcome (`ok` / `refused` / `error`); a scout run with an academic
  query writes two scout `tool` lines with `src_scout_*` crumbs.
- Join: every `src_*` id in a `finding` and in `report_refs` appears in a `tool` crumb of
  the same file, with a URL or a DOI.
- `run_end`: written for a finished run, for the clarify-interrupt exit, and for the
  `thread already finished` exit, each with the right outcome; a dangling-citation run is
  `finished` with `dangling` ≥ 1; an `effort mismatch` exit writes no line; a
  `read_reply` that raises `KeyboardInterrupt` gives `interrupted`; a write-role fake that
  raises gives `error` with the class name in `error` (`write_report` has no `try`, so a
  vendor exception there unwinds `main`).
- A fake run whose Exa client raises still writes one `finding` line carrying the gap text,
  and one `tool` line with outcome `error`.
- An invalid `EXACT_TRACE` value exits `1` with the misuse message, not a traceback.
- Path validation: a `--thread-id` holding a separator and a `--trace-path` equal to
  `EXACT_DB` are both refused before the graph runs, with exit `1` and nothing on stdout;
  the same thread id with an explicit `--trace-path` is accepted.
- Warnings: the first run of a new `--thread-id` under `--trace` prints no W2; a resume
  from a directory where the file is absent prints W2; a path whose first line names
  another thread prints W3.
- Status: default vs verbose golden lines for brief / research / reflect / audit, and a
  check that scout / clarify / plan / write print the same lines under both.
- `_prune`: a compress fake that returns one minted id and one unminted id yields a
  `Finding` with the minted id only.
- CLI: flag precedence, including `--no-trace` over `EXACT_TRACE=1`; path derivation from
  the `EXACT_DB` directory, including the bare default whose dirname is empty; resume
  appends the same file; the flags reach an injected `Runtime`.
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
   envelope; mark the three new payloads provisional.
2. `trace.py` + `Runtime.tracer` + run-scoped `Runtime` copy + CLI flags / path validation
   / `run_start` / `run_end` in a `finally`.
3. Add the three env names to the CLI test fixture's tuple, before any test can read a
   developer's shell.
4. CLI sink for the stage kinds; `tool` emits from `_Bag.call`, `_Tools.exa_highlights`,
   and the scout legs; the `_prune` filter on `source_ids`.
5. `status.py` verbose detail lines (§6.4); keep default golden.
6. Tests for tracer, sink, tool emits, key sets, status, CLI path/resume/warnings.
7. Run: `make check`.

---

## 9. Done when

- Default run (no flags) matches today’s CLI status and writes no sidecar.
- `--verbose` alone adds the four §6.4 detail line groups; no sidecar.
- `--trace` alone writes JSONL with all §4 kinds (on a full happy-path fake run) and prints
  the absolute `trace=…` after a successful open.
- A fake run whose Exa client raises still writes one `finding` line with the gap text, and
  one `tool` line with an error outcome.
- A fake run with two topics in one wave writes one `finding` line per topic.
- Every terminated run writes exactly one `run_end` per `run_id`, with the right outcome —
  including the clarify pause and the `thread already finished` exit.
- A `--trace-path` equal to `EXACT_DB` is refused before the graph runs.
- The first run of a new `--thread-id` under `--trace` prints no warning.
- Both §1 eval questions are answerable from one trace file, with no checkpoint DB present.
- Every `src_*` id in a `finding` or in `report_refs` resolves to a URL or a DOI inside the
  same trace file, except a dangling id (in `cited`, not in `sources`), which names no
  source by definition.
- Parent state / updates still hold no raw tool I/O.
- Same `--thread-id` resume appends the existing JSONL under a new `run_id`.
- `make check` is clean on a machine whose shell exports `EXACT_TRACE=1`.
- Spec and architecture describe the contract.

---

## 10. Open points closed in this plan

| Topic | Decision |
| :--- | :--- |
| Primary job | Structured eval trace |
| CLI job | Opt-in detail lines under brief, research, reflect and audit |
| Persistence | Sidecar JSONL beside `EXACT_DB`, validated at startup |
| Tool detail | Summaries at `_Bag.call` + the `_Tools.exa_highlights` refusal; one per attempt, with an outcome (`ok` / `refused` / `error`) |
| Tool crumbs | `src_*` id plus title, URL and DOI, one per minted source, so a trace outlives its checkpoint DB |
| Isolation | Kept |
| Knobs | Independent `--trace` and `--verbose`; `Settings` fields; CLI-scoped, so they reach an injected `Runtime` |
| Emitters | CLI sink for stage kinds, keyed on the node name; `Runtime` tracer for `tool` |
| `report_refs` | From the CLI after a `finished` run; sorted unique sets; `audit_citations` stays pure |
| Event kinds | The nine of §4 in v1, no `agent`; three payloads provisional; every key always present, `null` when unknown |
| `finding.source_ids` | Minted ids only; `_prune` filters against `collected` |
| `decision` | One kind, `stage` discriminator, two pinned key sets |
| Ordering | `(run_id, seq)`; `ts` never breaks ties; runs by first appearance; `run_end` last |
| Versioning | Integer `v`; additive keeps it, rename or removal raises it |
| Parallelism | Locked append for `tool` emits; interleaved; `topic_id` + `wave` together |
| Resume | Append same file; new `run_id`; flags must be repeated; W2 needs the thread in the checkpoint |
| Completeness | `run_end` from a `finally`, with an outcome and a dropped-emit count; `except` clauses classify |
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
7. **A `disabled` tool outcome.** Dropped: no code path produces it. `_Tools.as_list` gives
   a topic only the search tool of its lane, so a non-academic topic never sees
   `exa_publication_search`, and that tool has no early return.
8. **UUID7 for `run_id`, so runs sort by time.** Rejected: `uuid.uuid7` arrives in Python
   3.14 and the project pins 3.12+. Runs are ordered by first appearance in the file.
9. **Letting the consumer parse the wave from the topic id.** Rejected: the `t{wave}_{i}`
   grammar is not a contract in `docs/spec.md`. The emitter stamps `wave` beside every
   `topic_id` with one helper.
10. **Two `decision` kinds.** Rejected in favour of one kind with a `stage` field, so a
    consumer filter on `kind` still finds every decision.
11. **An `agent` kind.** Dropped on 2026-09-18, before any consumer exists. Once `usage`
    lines carry `topic_id` and `wave`, an `agent` line (`node`, `role`, `model`,
    `topic_id`, `wave`) is a strict subset of every `llm` usage line. Its proposed `round`
    key also had no source: no return value carries a tool-round index.
12. **Leaving `Finding.source_ids` unvalidated.** Rejected: the §9 join invariant would
    hold for the fake and fail on a real run. `_prune` filters against `collected`.
13. **Dropping `--verbose` from v1.** Rejected: the chunks carry four lists that the
    default lines fold into counts, and printing them is the light enrichment §2.2 asks
    for.
