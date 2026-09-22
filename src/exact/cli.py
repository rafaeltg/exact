from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from exact.audit import cited_ids
from exact.config import (
    ROLES,
    Runtime,
    Settings,
    effort_snapshot,
    resolve_prefs,
    role_max_tokens,
    role_model_id,
)
from exact.graph import build_graph
from exact.nodes.write import format_references
from exact.prefs import (
    PREF_BY_FIELD,
    PREF_FIELDS,
    PrefField,
    legacy_prefs,
    pref_mismatches,
)
from exact.sink import emit_chunk
from exact.status import format_effort, format_prefs, format_update
from exact.trace import JsonlTracer, NullTracer, Tracer, clip_error
from exact.usage import format_usage

# A stream consumer that sees each ``(node, update)`` pair beside the status loop.
type Sink = Callable[[str, Any], None]

# The environment names of the boolean knobs, by ``Settings`` field.
_BOOL_KNOB_ENV = {"exact_trace": "EXACT_TRACE", "exact_verbose": "EXACT_VERBOSE"}

# The rank key of the ``--skip-clarify`` conflict, which no ``Settings`` field owns.
_CLARIFY_CONFLICT = "--skip-clarify"

# When several knobs fail, the first key in this order is the one reported.
_FAILURE_ORDER = (
    "exact_effort",
    *(pref.field for pref in PREF_FIELDS),
    _CLARIFY_CONFLICT,
    *_BOOL_KNOB_ENV,
)

# No ``choices`` on an enum flag: an unknown value must fail with the same
# message the env path produces, not with argparse's own.
_FLAG_SHAPE: dict[str, dict[str, Any]] = {
    "enum": {},
    "hosts": {"action": "append"},
    "bool": {"action": argparse.BooleanOptionalAction},
}


def _print_interrupt(payload: dict) -> None:
    print()
    print(payload.get("question") or "Clarify:")
    preview = payload.get("scout_preview") or []
    if preview:
        print("Scout:")
        for title in preview:
            print(f"  - {title}")
    options = payload.get("options") or []
    for i, opt in enumerate(options, start=1):
        label = opt.get("label") or opt.get("id")
        desc = opt.get("description") or ""
        extra = f" — {desc}" if desc else ""
        print(f"  [{i}] {label}{extra}")
    print("  [skip] proceed without more detail")
    print()


def _payload_from_state(snapshot) -> dict | None:
    for task in snapshot.tasks or ():
        for item in getattr(task, "interrupts", None) or ():
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                return value
            return {"question": str(value), "options": []}
    return None


def _stream(app, payload, config, *, sink: Sink, verbose: bool) -> None:
    for chunk in app.stream(payload, config, stream_mode="updates"):
        if not isinstance(chunk, dict):
            continue
        for node, update in chunk.items():
            for line in format_update(node, update, verbose=verbose):
                print(line, flush=True)
            sink(node, update)


def _seed(args, settings: Settings, prefs: dict[str, Any]) -> dict:
    return {
        "initial_query": " ".join(args.query),
        "prefs": prefs,
        "effort": settings.exact_effort,
        "max_iterations": settings.max_iterations,
        "max_clarify_turns": settings.max_clarify_turns,
        "max_topics_first_wave": settings.max_topics_first_wave,
        "max_topics_followup": settings.max_topics_followup,
        "clarify_turns": 0,
        "iteration": 0,
        "messages": [],
        "sources": [],
        "findings": [],
        "errors": [],
        "usage": [],
        "prior_titles": [],
        "prior_queries": [],
        "followups": [],
        "uncovered": [],
        "topics": [],
        "scout_hits": [],
    }


def _read_reply() -> str:
    try:
        return input("> ").strip() or "skip"
    except EOFError:
        return "skip"


def _clarify_loop(
    app, config, read_reply: Callable[[], str], *, sink: Sink, verbose: bool
) -> dict:
    while True:
        snap = app.get_state(config)
        if not snap.next:
            return snap.values or {}
        _print_interrupt(_payload_from_state(snap) or {})
        _stream(app, Command(resume=read_reply()), config, sink=sink, verbose=verbose)


def _print_errors(errors: list[str]) -> None:
    """Report each distinct run error once; waves repeat a failure verbatim."""
    if not errors:
        return
    print("\n## Errors")
    for err in dict.fromkeys(errors):
        print(f"- {err}")


def _print_report(result: dict) -> None:
    report = result.get("final_report") or ""
    if report:
        print()
        print(report)
    for line in format_references(result.get("sources") or []):
        print(line)
    _print_errors(result.get("errors") or [])
    for line in format_usage(
        result.get("usage") or [], effort=result.get("effort") or "normal"
    ):
        print(line)


def _parse_argv(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exact — Open Deep Research")
    parser.add_argument("query", nargs="+", help="Research question")
    parser.add_argument("--skip-clarify", action="store_true")
    parser.add_argument("--thread-id", default=None)
    # No ``choices``: an unknown value must fail with the same message the env
    # path produces, not with argparse's own.
    parser.add_argument(
        "--effort",
        default=None,
        help="Research depth: normal (default) or max. Overrides EXACT_EFFORT.",
    )
    # ``None`` means "fall to the Settings field", so --no-trace beats the env.
    parser.add_argument(
        "--trace",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write a JSONL run trace. Overrides EXACT_TRACE.",
    )
    parser.add_argument(
        "--trace-path",
        default=None,
        help="Trace file. Overrides EXACT_TRACE_PATH. Does not turn tracing on.",
    )
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Print detail lines under the status lines. Overrides EXACT_VERBOSE.",
    )
    _add_pref_flags(parser)
    return parser.parse_args(argv)


def _add_pref_flags(parser: argparse.ArgumentParser) -> None:
    """One flag per preference; ``None`` means "fall to the Settings field"."""
    for pref in PREF_FIELDS:
        parser.add_argument(
            pref.flag,
            dest=pref.name,
            default=None,
            help=f"Overrides {pref.env}.",
            **_FLAG_SHAPE[pref.kind],
        )


def _pref_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """The ``Settings`` fields the preference flags set, by field name."""
    overrides = {
        pref.field: getattr(args, pref.name)
        for pref in PREF_FIELDS
        if getattr(args, pref.name) is not None
    }
    if args.skip_clarify and args.clarify_mode is None:
        overrides["exact_clarify_mode"] = "skip"
    return overrides


def _clarify_conflict(args: argparse.Namespace) -> str | None:
    """The refusal of ``--skip-clarify`` beside another ``--clarify`` mode."""
    if args.skip_clarify and args.clarify_mode not in (None, "skip"):
        return f"--skip-clarify cannot combine with --clarify {args.clarify_mode}"
    return None


def _pref_message(err: Mapping[str, Any], pref: PrefField) -> str:
    """The user-facing message for one rejected preference."""
    source = f"({pref.flag} or {pref.env})"
    got = f"got {err['input']!r} {source}"
    match err["type"]:
        case "literal_error":
            values = ", ".join(repr(value) for value in pref.values)
            return f"{pref.name} must be one of {values}; {got}"
        case "bool_parsing":
            return f"{pref.name} must be a boolean such as 0 or 1; {got}"
        case "value_error":
            return str(err["ctx"]["error"])
        case _:
            return f"{pref.name}: {err['msg']}; {got}"


def _failure_text(err: Mapping[str, Any]) -> str | None:
    """The user-facing message for one rejected knob; ``None`` for other fields."""
    field = str(err["loc"][0]) if err["loc"] else ""
    if field == "exact_effort":
        return (
            f"effort must be 'normal' or 'max'; got {err['input']!r} "
            "(--effort or EXACT_EFFORT)"
        )
    if field in PREF_BY_FIELD:
        return _pref_message(err, PREF_BY_FIELD[field])
    if field in _BOOL_KNOB_ENV:
        name = _BOOL_KNOB_ENV[field]
        return f"{name} must be a boolean such as 0 or 1; got {err['input']!r}"
    return None


def _first_failure(exc: ValidationError | None, conflict: str | None) -> str | None:
    """The message of the failure that ranks first; ``None`` when none ranks."""
    found: dict[str, str] = {}
    if conflict is not None:
        found[_CLARIFY_CONFLICT] = conflict
    for err in exc.errors() if exc is not None else ():
        text = _failure_text(err)
        if text is not None:
            found.setdefault(str(err["loc"][0]), text)
    return next((found[key] for key in _FAILURE_ORDER if key in found), None)


def _build_settings(
    overrides: dict[str, Any], conflict: str | None, base: Settings | None
) -> Settings:
    """Build settings with ``overrides`` on top; exit on the first refusal.

    With a ``base``, its values stand in for the environment, so an injected
    runtime keeps everything but what a flag sets.
    """
    try:
        if base is None:
            settings = Settings(**overrides)
        else:
            settings = Settings(_env_file=None, **{**base.model_dump(), **overrides})
    except ValidationError as exc:
        message = _first_failure(exc, conflict)
        if message is None:
            raise
        raise SystemExit(message) from exc
    if conflict is not None:
        raise SystemExit(conflict)
    return settings


def _resolve_settings(args: argparse.Namespace) -> Settings:
    """Build the run's settings, with each flag winning over the environment."""
    load_dotenv()
    overrides = _pref_overrides(args)
    if args.effort is not None:
        overrides["exact_effort"] = args.effort
    return _build_settings(overrides, _clarify_conflict(args), None)


def _run_runtime(args: argparse.Namespace, runtime: Runtime | None) -> Runtime:
    """The live runtime, or the injected one with the preference flags applied.

    ``--effort`` never reaches an injected runtime: its settings fix the depth.
    """
    if runtime is None:
        return Runtime.from_env(_resolve_settings(args))
    settings = _build_settings(
        _pref_overrides(args), _clarify_conflict(args), runtime.settings
    )
    return replace(runtime, settings=settings)


def _sqlite_saver(path: str) -> SqliteSaver:
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)


def thread_config(thread_id: str, *, max_concurrency: int) -> dict[str, Any]:
    """LangGraph runnable config for a SQLite-backed CLI thread.

    ``max_concurrency`` is a top-level key: LangGraph never reads it from
    ``configurable``.
    """
    return {
        "configurable": {"thread_id": thread_id},
        "max_concurrency": max_concurrency,
    }


def _dangling_count(result: Mapping[str, Any]) -> int:
    return sum(
        1
        for item in result.get("uncovered") or []
        if isinstance(item, str) and item.startswith("dangling:")
    )


def _qa_exit(result: dict) -> int:
    return 1 if _dangling_count(result) else 0


def _guard_effort(values: Mapping[str, Any], effort: str) -> None:
    """Refuse a resume that would run a started thread at another depth."""
    if not values:
        return
    stored = values.get("effort") or "normal"
    if stored != effort:
        raise SystemExit(
            f"effort mismatch: thread ran with effort={stored}; "
            f"this run resolved effort={effort}; "
            f"rerun with --effort {stored} or use a new --thread-id"
        )


def _stored_prefs(
    saver: Any, config: dict[str, Any], values: Mapping[str, Any]
) -> dict[str, Any]:
    """The thread's ``prefs``, or the ones a pre-``prefs`` checkpoint implies.

    The old ``skip_clarify`` channel is no longer in the graph state, so only
    the raw checkpoint still shows it.
    """
    if values.get("prefs"):
        return values["prefs"]
    channels = saver.get_tuple(config).checkpoint["channel_values"]
    return legacy_prefs(bool(channels.get("skip_clarify")))


def _guard_prefs(stored: Mapping[str, Any], resolved: Mapping[str, Any]) -> None:
    """Refuse a resume whose preferences differ from the thread's."""
    parts = pref_mismatches(stored, resolved)
    if parts:
        raise SystemExit(
            f"preference mismatch: {'; '.join(parts)}; "
            "rerun with the same preferences or use a new --thread-id"
        )


def _guard_thread(
    saver: Any, config: dict[str, Any], values: Mapping[str, Any], seed: dict
) -> dict[str, Any]:
    """Refuse a resume that drifts from its thread; return the run's ``prefs``."""
    if not values:
        return seed["prefs"]
    _guard_effort(values, seed["effort"])
    stored = _stored_prefs(saver, config, values)
    _guard_prefs(stored, seed["prefs"])
    return stored


def _run(
    app, seed, config, read_reply: Callable[[], str], *, sink: Sink, verbose: bool
) -> dict:
    snap = app.get_state(config)
    if snap.next:
        return _clarify_loop(app, config, read_reply, sink=sink, verbose=verbose)
    if snap.values:
        # Append channels never reset, so a second run would merge the old
        # sources, findings and usage into the new report.
        raise SystemExit("thread already finished; use a new --thread-id")
    _stream(app, seed, config, sink=sink, verbose=verbose)
    snap = app.get_state(config)
    if not snap.next:
        return snap.values or {}
    _print_interrupt(_payload_from_state(snap) or {})
    return snap.values or {}


def _trace_on(args: argparse.Namespace, settings: Settings) -> bool:
    return settings.exact_trace if args.trace is None else args.trace


def _verbose_on(args: argparse.Namespace, settings: Settings) -> bool:
    return settings.exact_verbose if args.verbose is None else args.verbose


def _trace_target(
    args: argparse.Namespace, settings: Settings, thread_id: str
) -> tuple[Path, bool]:
    """The absolute trace path, and whether it was derived from the thread id."""
    configured = args.trace_path or settings.exact_trace_path
    if configured:
        return Path(configured).resolve(strict=False), False
    # Join the parts: the default ``EXACT_DB`` has an empty dirname.
    derived = Path(settings.exact_db).parent / "traces" / f"{thread_id}.jsonl"
    return derived.resolve(strict=False), True


def _refuse_trace_target(path: Path, thread_id: str, derived: bool, db: Path) -> None:
    """Refuse a trace path that is not a safe file name or is the checkpoint DB."""
    unsafe = "/" in thread_id or "\\" in thread_id or thread_id in {".", ".."}
    if derived and unsafe:
        raise SystemExit(
            f"trace: --thread-id {thread_id} cannot be a file name; pass --trace-path"
        )
    # An append into the SqliteSaver file corrupts the checkpoint for good.
    if path == db.resolve(strict=False):
        raise SystemExit(
            f"trace: {path} is the checkpoint database; pass a different --trace-path"
        )


class _TraceOpen(NamedTuple):
    """The run's tracer, and the facts the startup warnings read."""

    tracer: Tracer
    path: Path
    is_tracing: bool
    existed: bool
    first_thread: str | None


def _first_thread(path: Path) -> str | None:
    """The ``thread_id`` of the first line in ``path``; ``None`` when unreadable."""
    with path.open(encoding="utf-8") as handle:
        try:
            first = json.loads(handle.readline())
        except ValueError:
            return None
    thread = first.get("thread_id") if isinstance(first, dict) else None
    return thread if isinstance(thread, str) else None


def _open_trace(
    args: argparse.Namespace, settings: Settings, thread_id: str, trace_on: bool
) -> _TraceOpen:
    """Validate and open the trace file before any output or model spend."""
    path, derived = _trace_target(args, settings, thread_id)
    existed = path.exists()
    if not trace_on:
        return _TraceOpen(NullTracer(), path, False, existed, None)
    _refuse_trace_target(path, thread_id, derived, Path(settings.exact_db))
    try:
        first_thread = _first_thread(path) if existed else None
        path.parent.mkdir(parents=True, exist_ok=True)
        tracer = JsonlTracer(path, thread_id)
    except OSError as exc:
        raise SystemExit(f"trace: cannot write {path}: {exc}") from exc
    return _TraceOpen(tracer, path, True, existed, first_thread)


def _trace_warnings(
    opened: _TraceOpen, args: argparse.Namespace, thread_id: str, snap
) -> list[str]:
    """The resume and reuse warnings that hold, in W1, W2, W3 order."""
    named = args.thread_id is not None
    path = opened.path
    if not opened.is_tracing:
        if named and opened.existed:
            return [f"warning: trace off; {path} holds earlier turns of this thread"]
        return []
    warnings = []
    if named and (snap.values or snap.next) and not opened.existed:
        warnings.append(
            f"warning: thread {thread_id} resumes, but {path} did not exist; "
            "pass the same --trace-path as the first run"
        )
    other = opened.first_thread
    if other is not None and other != thread_id:
        warnings.append(
            f"warning: {path} holds lines for thread {other}; "
            f"this run is thread {thread_id}"
        )
    return warnings


def _print_start(thread_id: str, opened: _TraceOpen, warnings: list[str]) -> None:
    print(f"thread_id={thread_id}", flush=True)
    if opened.is_tracing:
        print(f"trace={opened.path}", flush=True)
    for warning in warnings:
        print(warning, file=sys.stderr, flush=True)


def _settings_payload(
    settings: Settings, snapshot: Mapping[str, Any], prefs: Mapping[str, Any]
) -> dict:
    """The run's caps, model settings and full ``prefs``, with no key."""
    return {
        **snapshot,
        "prefs": dict(prefs),
        "models": {role: role_model_id(settings, role) for role in ROLES},
        "max_tokens": {role: role_max_tokens(settings, role) for role in ROLES},
        "temperature": settings.exact_temperature,
        "thinking_budget": settings.exact_thinking_budget,
    }


class _Started(NamedTuple):
    """What the run needs once its start lines are out."""

    app: Any
    config: dict[str, Any]
    seed: dict
    tracer: Tracer
    verbose: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _begin_run(
    args: argparse.Namespace,
    runtime: Runtime,
    checkpointer: Any | None,
    new_id: Callable[[], str] | None,
    now: Callable[[], datetime] | None,
) -> _Started:
    """Prepare one run and announce it; every startup refusal happens here."""
    settings = runtime.settings
    thread_id = args.thread_id or str((new_id or uuid.uuid4)())
    opened = _open_trace(args, settings, thread_id, _trace_on(args, settings))
    saver = checkpointer or _sqlite_saver(settings.exact_db)
    # A copy, never a mutation: every node closes over this one runtime.
    app = build_graph(replace(runtime, tracer=opened.tracer), checkpointer=saver)
    config = thread_config(thread_id, max_concurrency=settings.max_concurrency)
    seed = _seed(args, settings, resolve_prefs(settings, (now or _utc_now)()))
    snap = app.get_state(config)
    _print_start(thread_id, opened, _trace_warnings(opened, args, thread_id, snap))
    prefs = _guard_thread(saver, config, snap.values or {}, seed)
    snapshot = effort_snapshot(settings, snap.values or seed)
    print(format_effort(snapshot), flush=True)
    print(format_prefs(prefs), flush=True)
    verbose = _verbose_on(args, settings)
    opened.tracer.emit(
        "run_start",
        {
            "query": seed["initial_query"],
            "verbose": verbose,
            "resume": bool(snap.next),
            "settings": _settings_payload(settings, snapshot, prefs),
        },
    )
    return _Started(app, config, seed, opened.tracer, verbose)


def _run_outcome(exc: BaseException | None, snap) -> tuple[str, str | None]:
    """Classify how a run ended, for ``run_end``."""
    match exc:
        case KeyboardInterrupt():
            return "interrupted", None
        case SystemExit():
            return "rejected", str(exc)
        case None:
            return ("interrupted" if snap.next else "finished"), None
        case _:
            return "error", clip_error(f"{type(exc).__name__}: {exc}")


def _report_refs(result: Mapping[str, Any]) -> dict:
    """The sorted cited, uncited and dangling ``src_*`` ids of the final report."""
    cited = set(cited_ids(result.get("final_report")))
    minted = {s.get("id") for s in result.get("sources") or [] if s.get("id")}
    return {
        "cited": sorted(cited),
        "uncited": sorted(minted - cited),
        "dangling": sorted(cited - minted),
    }


def _finish_trace(
    tracer: Tracer, outcome: str, error: str | None, result: Mapping[str, Any]
) -> None:
    """Write the run's closing lines; ``run_end`` is always its last line."""
    finished = outcome == "finished"
    if finished:
        tracer.emit("report_refs", _report_refs(result))
    tracer.emit(
        "run_end",
        {
            "outcome": outcome,
            "dangling": _dangling_count(result) if finished else None,
            "dropped": tracer.dropped,
            "error": error,
        },
    )
    tracer.close()


def main(
    argv: list[str] | None = None,
    *,
    runtime: Runtime | None = None,
    checkpointer: Any | None = None,
    read_reply: Callable[[], str] | None = None,
    new_id: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Run one research query; return 1 when dangling citations remain."""
    args = _parse_argv(argv)
    runtime = _run_runtime(args, runtime)
    started = _begin_run(args, runtime, checkpointer, new_id, now)
    sink = partial(emit_chunk, started.tracer)
    result: dict = {}
    try:
        result = _run(
            started.app,
            started.seed,
            started.config,
            read_reply or _read_reply,
            sink=sink,
            verbose=started.verbose,
        )
        _print_report(result)
        outcome, error = _run_outcome(None, started.app.get_state(started.config))
    except BaseException as exc:
        # A ``finally`` cannot see why the block ended, so classify here.
        outcome, error = _run_outcome(exc, None)
        raise
    finally:
        _finish_trace(started.tracer, outcome, error, result)
    return _qa_exit(result)


if __name__ == "__main__":
    raise SystemExit(main())
