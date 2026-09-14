from __future__ import annotations

import argparse
import sqlite3
import uuid
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from exact.config import Runtime, Settings
from exact.graph import build_graph
from exact.nodes.write import format_references
from exact.status import format_update
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
        "max_iterations": settings.max_iterations,
        "max_clarify_turns": settings.max_clarify_turns,
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


def _print_report(result: dict) -> None:
    report = result.get("final_report") or ""
    if report:
        print()
        print(report)
    for line in format_references(result.get("sources") or []):
        print(line)
    errors = result.get("errors") or []
    if errors:
        print("\n## Errors")
        for err in errors:
            print(f"- {err}")
    for line in format_usage(result.get("usage") or []):
        print(line)


def _parse_argv(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exact — Open Deep Research")
    parser.add_argument("query", nargs="+", help="Research question")
    parser.add_argument("--skip-clarify", action="store_true")
    parser.add_argument("--thread-id", default=None)
    return parser.parse_args(argv)


def _sqlite_saver(path: str) -> SqliteSaver:
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "max_concurrency": 3}}


def _qa_exit(result: dict) -> int:
    for item in result.get("uncovered") or []:
        if isinstance(item, str) and item.startswith("dangling:"):
            return 1
    return 0


def _run(app, seed, config, read_reply: Callable[[], str]) -> dict:
    snap = app.get_state(config)
    if snap.next:
        return _clarify_loop(app, config, read_reply)
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
    args = _parse_argv(argv)
    runtime = runtime or Runtime.from_env()
    saver = checkpointer or _sqlite_saver(runtime.settings.exact_db)
    app = build_graph(runtime, checkpointer=saver)
    thread_id = args.thread_id or str((new_id or uuid.uuid4)())
    print(f"thread_id={thread_id}", flush=True)
    result = _run(
        app,
        _seed(args, runtime.settings),
        thread_config(thread_id),
        read_reply or _read_reply,
    )
    _print_report(result)
    return _qa_exit(result)


if __name__ == "__main__":
    raise SystemExit(main())
