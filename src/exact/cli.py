from __future__ import annotations

import argparse
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from exact.config import Runtime, Settings, effort_snapshot
from exact.graph import build_graph
from exact.nodes.write import format_references
from exact.status import format_effort, format_update
from exact.usage import format_usage


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


def _stream(app, payload, config) -> None:
    for chunk in app.stream(payload, config, stream_mode="updates"):
        if not isinstance(chunk, dict):
            continue
        for node, update in chunk.items():
            for line in format_update(node, update):
                print(line, flush=True)


def _seed(args, settings: Settings) -> dict:
    return {
        "initial_query": " ".join(args.query),
        "skip_clarify": args.skip_clarify,
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


def _clarify_loop(app, config, read_reply: Callable[[], str]) -> dict:
    while True:
        snap = app.get_state(config)
        if not snap.next:
            return snap.values or {}
        _print_interrupt(_payload_from_state(snap) or {})
        _stream(app, Command(resume=read_reply()), config)


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
    return parser.parse_args(argv)


def _effort_error(exc: ValidationError) -> str | None:
    """The user-facing message for a rejected effort; ``None`` for anything else."""
    for err in exc.errors():
        if err["loc"] == ("exact_effort",):
            return (
                f"effort must be 'normal' or 'max'; got {err['input']!r} "
                "(--effort or EXACT_EFFORT)"
            )
    return None


def _resolve_settings(effort: str | None) -> Settings:
    """Build the run's settings, with the flag winning over the environment."""
    load_dotenv()
    try:
        return Settings(exact_effort=effort) if effort is not None else Settings()
    except ValidationError as exc:
        message = _effort_error(exc)
        if message is None:
            raise
        raise SystemExit(message) from exc


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


def _qa_exit(result: dict) -> int:
    for item in result.get("uncovered") or []:
        if isinstance(item, str) and item.startswith("dangling:"):
            return 1
    return 0


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


def _run(app, snap, seed, config, read_reply: Callable[[], str]) -> dict:
    if snap.next:
        return _clarify_loop(app, config, read_reply)
    if snap.values:
        # Append channels never reset, so a second run would merge the old
        # sources, findings and usage into the new report.
        raise SystemExit("thread already finished; use a new --thread-id")
    _stream(app, seed, config)
    snap = app.get_state(config)
    if not snap.next:
        return snap.values or {}
    _print_interrupt(_payload_from_state(snap) or {})
    return snap.values or {}


def main(
    argv: list[str] | None = None,
    *,
    runtime: Runtime | None = None,
    checkpointer: Any | None = None,
    read_reply: Callable[[], str] | None = None,
    new_id: Callable[[], str] | None = None,
) -> int:
    """Run one research query; return 1 when dangling citations remain."""
    args = _parse_argv(argv)
    runtime = runtime or Runtime.from_env(_resolve_settings(args.effort))
    saver = checkpointer or _sqlite_saver(runtime.settings.exact_db)
    app = build_graph(runtime, checkpointer=saver)
    thread_id = args.thread_id or str((new_id or uuid.uuid4)())
    config = thread_config(thread_id, max_concurrency=runtime.settings.max_concurrency)
    seed = _seed(args, runtime.settings)
    snap = app.get_state(config)
    print(f"thread_id={thread_id}", flush=True)
    _guard_effort(snap.values or {}, seed["effort"])
    print(
        format_effort(effort_snapshot(runtime.settings, snap.values or seed)),
        flush=True,
    )
    result = _run(app, snap, seed, config, read_reply or _read_reply)
    _print_report(result)
    return _qa_exit(result)


if __name__ == "__main__":
    raise SystemExit(main())
