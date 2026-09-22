from __future__ import annotations

import io
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from exact.cli import main, thread_config
from exact.graph import build_graph
from exact.models import (
    ClarificationOption,
    ClarifyDecision,
    Finding,
    PlanDecision,
    ReflectDecision,
)
from tests.fakes import (
    SEED_INSTANT,
    FakeExa,
    FakeLLM,
    graph_seed,
    read_trace,
    runtime,
    seed_prefs,
    source,
)


def test_skip_clarify_writes_a_cited_report(capsys):
    code = main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert code == 0
    assert "X is Y [src_t0_1_1]." in capsys.readouterr().out


def test_thread_id_flag_is_printed(capsys):
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-fixed"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert "thread_id=t-fixed" in capsys.readouterr().out


def test_generated_thread_id_uses_injected_factory(capsys):
    main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
        new_id=lambda: "t-gen",
    )
    assert "thread_id=t-gen" in capsys.readouterr().out


def test_same_thread_id_continues_after_interrupt(tmp_path, capsys):
    conn = sqlite3.connect(tmp_path / "exact.sqlite", check_same_thread=False)
    saver = SqliteSaver(conn)
    llm = FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus on mechanisms?",
            options=[ClarificationOption(id="opt_1", label="Mechanisms")],
        )
    )
    rt = runtime(llm=llm)

    def unused() -> str:
        raise AssertionError("read_reply should not run on the first call")

    first = main(
        ["What is X?", "--thread-id", "t-resume"],
        runtime=rt,
        checkpointer=saver,
        read_reply=unused,
    )
    first_out = capsys.readouterr().out
    assert first == 0
    assert "Scout found Source A" in first_out
    assert "X is Y [src_t0_1_1]." not in first_out

    second = main(
        ["What is X?", "--thread-id", "t-resume"],
        runtime=rt,
        checkpointer=saver,
        read_reply=lambda: "skip",
    )
    second_out = capsys.readouterr().out
    assert second == 0
    assert "X is Y [src_t0_1_1]." in second_out


def test_rerunning_a_finished_thread_is_refused(capsys):
    saver = InMemorySaver()
    rt = runtime()
    first = main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-done"],
        runtime=rt,
        checkpointer=saver,
    )
    assert first == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--skip-clarify", "--thread-id", "t-done"],
            runtime=rt,
            checkpointer=saver,
        )
    assert "already finished" in str(exc.value)


def test_dangling_citations_fail_qa(capsys):
    code = main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(llm=FakeLLM(report="Claim [src_missing].")),
        checkpointer=InMemorySaver(),
    )
    assert code == 1
    assert "## Audit" in capsys.readouterr().out


_KNOB_ENV_NAMES = (
    "EXACT_EFFORT",
    "MAX_ITERATIONS",
    "MAX_CLARIFY_TURNS",
    "MAX_TOOL_ROUNDS",
    "MAX_HITS",
)


@pytest.fixture(autouse=True)
def _no_inherited_knobs(monkeypatch):
    """A shell export of any knob must not steer an assertion in this file."""
    for name in _KNOB_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """A run that reads neither the repo `.env` nor an inherited knob."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("exact.cli.load_dotenv", lambda: None)


def _record_settings(monkeypatch) -> list:
    """Capture the settings the CLI resolves instead of building a live runtime."""
    seen: list = []

    def from_env(settings=None):
        seen.append(settings)
        return runtime()

    monkeypatch.setattr("exact.cli.Runtime.from_env", from_env)
    return seen


def test_the_effort_flag_reaches_the_runtime(isolated_env, monkeypatch):
    seen = _record_settings(monkeypatch)
    main(
        ["What is X?", "--skip-clarify", "--effort", "max"],
        checkpointer=InMemorySaver(),
    )
    assert seen[0].exact_effort == "max"


def test_the_effort_env_reaches_the_runtime(isolated_env, monkeypatch):
    monkeypatch.setenv("EXACT_EFFORT", "max")
    seen = _record_settings(monkeypatch)
    main(["What is X?", "--skip-clarify"], checkpointer=InMemorySaver())
    assert seen[0].exact_effort == "max"


def test_the_effort_flag_wins_over_the_effort_env(isolated_env, monkeypatch):
    monkeypatch.setenv("EXACT_EFFORT", "max")
    seen = _record_settings(monkeypatch)
    main(
        ["What is X?", "--skip-clarify", "--effort", "normal"],
        checkpointer=InMemorySaver(),
    )
    assert seen[0].exact_effort == "normal"


def test_an_unknown_effort_flag_exits_with_the_two_levels(isolated_env, monkeypatch):
    _record_settings(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--skip-clarify", "--effort", "bogus"],
            checkpointer=InMemorySaver(),
        )
    assert "'normal'" in str(exc.value)
    assert "'max'" in str(exc.value)


def test_an_unknown_effort_env_exits_with_the_two_levels(isolated_env, monkeypatch):
    monkeypatch.setenv("EXACT_EFFORT", "bogus")
    _record_settings(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main(["What is X?", "--skip-clarify"], checkpointer=InMemorySaver())
    assert "'normal'" in str(exc.value)
    assert "'max'" in str(exc.value)


def test_an_injected_runtime_ignores_the_effort_flag(isolated_env):
    code = main(
        ["What is X?", "--skip-clarify", "--effort", "bogus"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert code == 0


def test_the_echo_line_follows_the_thread_id_line(capsys):
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-echo"],
        runtime=runtime(exact_effort="max"),
        checkpointer=InMemorySaver(),
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "thread_id=t-echo"
    assert lines[1] == (
        "effort=max waves=4 topics=4/3 rounds=6 hits=8 clarify=3 concurrency=4"
    )


def test_the_echo_line_reports_the_injected_runtime_not_the_flag(isolated_env, capsys):
    main(
        ["What is X?", "--skip-clarify", "--effort", "max"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert "effort=normal" in capsys.readouterr().out


def test_the_usage_heading_names_the_run_effort(capsys):
    main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert "## Usage (effort=normal)" in capsys.readouterr().out


def _parking_llm() -> FakeLLM:
    return FakeLLM(
        clarify=ClarifyDecision(
            needed=True,
            question="Scout found Source A. Focus?",
            options=[ClarificationOption(id="opt_1", label="A")],
        )
    )


def test_resuming_a_parked_thread_under_another_effort_is_refused(capsys):
    saver = InMemorySaver()
    llm = _parking_llm()
    main(
        ["What is X?", "--thread-id", "t-park"],
        runtime=runtime(llm=llm),
        checkpointer=saver,
        read_reply=lambda: "skip",
    )
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--thread-id", "t-park"],
            runtime=runtime(llm=llm, exact_effort="max"),
            checkpointer=saver,
            read_reply=lambda: "skip",
        )
    assert "effort mismatch" in str(exc.value)


def test_a_finished_thread_reports_the_mismatch_before_the_finished_check(capsys):
    saver = InMemorySaver()
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-fin"],
        runtime=runtime(),
        checkpointer=saver,
    )
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--skip-clarify", "--thread-id", "t-fin"],
            runtime=runtime(exact_effort="max"),
            checkpointer=saver,
        )
    assert "effort mismatch" in str(exc.value)
    assert "already finished" not in str(exc.value)


def test_a_fresh_thread_id_starts_under_the_resolved_effort(capsys):
    code = main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-new"],
        runtime=runtime(exact_effort="max"),
        checkpointer=InMemorySaver(),
    )
    assert code == 0
    assert "effort=max" in capsys.readouterr().out


def test_a_checkpoint_without_the_effort_channel_resumes_as_normal(capsys):
    saver = InMemorySaver()
    rt = runtime(llm=_parking_llm())
    seed = graph_seed(prefs=seed_prefs())
    for key in ("effort", "max_topics_first_wave", "max_topics_followup"):
        del seed[key]
    build_graph(rt, checkpointer=saver).invoke(
        seed, thread_config("t-old", max_concurrency=3)
    )
    capsys.readouterr()
    code = main(
        ["What is X?", "--thread-id", "t-old"],
        runtime=rt,
        checkpointer=saver,
        read_reply=lambda: "skip",
    )
    assert code == 0
    assert "effort=normal" in capsys.readouterr().out


# ─── Trace sidecar ──────────────────────────────────────────────────────


def _traced(
    path: Path,
    thread: str = "t-tr",
    *extra: str,
    rt=None,
    saver=None,
    read_reply=None,
    skip_clarify: bool = True,
) -> int:
    argv = ["What is X?", "--thread-id", thread, "--trace", "--trace-path", str(path)]
    if skip_clarify:
        argv.append("--skip-clarify")
    return main(
        [*argv, *extra],
        runtime=rt or runtime(),
        checkpointer=saver or InMemorySaver(),
        read_reply=read_reply,
    )


def _kinds(path: Path) -> list[str]:
    return [line["kind"] for line in read_trace(path)]


def _one(path: Path, kind: str) -> dict:
    (data,) = [line["data"] for line in read_trace(path) if line["kind"] == kind]
    return data


def test_the_trace_flag_writes_a_sidecar(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path)
    assert _kinds(path)[0] == "run_start"


def test_the_no_trace_flag_writes_no_sidecar(tmp_path):
    path = tmp_path / "run.jsonl"
    main(
        ["What is X?", "--skip-clarify", "--no-trace", "--trace-path", str(path)],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert not path.exists()


def test_the_no_trace_flag_overrides_the_trace_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXACT_TRACE", "1")
    path = tmp_path / "run.jsonl"
    main(
        ["What is X?", "--skip-clarify", "--no-trace", "--trace-path", str(path)],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert not path.exists()


def test_a_bare_run_under_the_trace_env_traces_to_the_derived_path(
    isolated_env, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("EXACT_TRACE", "1")
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-env"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    derived = (tmp_path / "traces" / "t-env.jsonl").resolve()
    assert f"trace={derived}" in capsys.readouterr().out.splitlines()
    assert _kinds(derived)[-1] == "run_end"


@pytest.mark.parametrize("name", ["EXACT_TRACE", "EXACT_VERBOSE"])
def test_an_invalid_boolean_knob_env_exits_with_the_misuse_message(
    isolated_env, monkeypatch, name: str
):
    monkeypatch.setenv(name, "maybe")
    with pytest.raises(SystemExit) as exc:
        main(["What is X?", "--skip-clarify"], checkpointer=InMemorySaver())
    assert str(exc.value) == f"{name} must be a boolean such as 0 or 1; got 'maybe'"


def test_an_invalid_effort_env_wins_over_an_invalid_trace_env(
    isolated_env, monkeypatch
):
    monkeypatch.setenv("EXACT_EFFORT", "bogus")
    monkeypatch.setenv("EXACT_TRACE", "maybe")
    with pytest.raises(SystemExit) as exc:
        main(["What is X?", "--skip-clarify"], checkpointer=InMemorySaver())
    assert str(exc.value).startswith("effort must be 'normal' or 'max'")


def test_the_derived_path_of_a_bare_exact_db_is_under_the_working_directory(
    isolated_env, tmp_path, capsys
):
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-bare", "--trace"],
        runtime=runtime(exact_db="exact.sqlite"),
        checkpointer=InMemorySaver(),
    )
    derived = (tmp_path / "traces" / "t-bare.jsonl").resolve()
    assert f"trace={derived}" in capsys.readouterr().out.splitlines()


def test_the_derived_path_of_an_absolute_exact_db_is_beside_that_file(tmp_path, capsys):
    db = tmp_path / "data" / "x.sqlite"
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-abs", "--trace"],
        runtime=runtime(exact_db=str(db)),
        checkpointer=InMemorySaver(),
    )
    derived = (tmp_path / "data" / "traces" / "t-abs.jsonl").resolve()
    assert f"trace={derived}" in capsys.readouterr().out.splitlines()
    assert derived.exists()


def test_an_explicit_trace_path_is_printed_as_given(tmp_path, capsys):
    path = tmp_path / "run.jsonl"
    _traced(path)
    assert f"trace={path.resolve()}" in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize("thread", ["a/b", "a\\b", ".", ".."])
def test_a_thread_id_that_is_no_file_name_is_refused_under_a_derived_path(
    isolated_env, capsys, thread: str
):
    exa = FakeExa()
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--skip-clarify", "--thread-id", thread, "--trace"],
            runtime=runtime(exa=exa),
            checkpointer=InMemorySaver(),
        )
    assert str(exc.value) == (
        f"trace: --thread-id {thread} cannot be a file name; pass --trace-path"
    )
    assert capsys.readouterr().out == ""
    assert exa.search_nums == []


def test_a_thread_id_with_a_separator_is_accepted_with_an_explicit_path(tmp_path):
    assert _traced(tmp_path / "run.jsonl", "a/b") == 0


def test_a_thread_id_with_a_separator_is_accepted_with_tracing_off(isolated_env):
    code = main(
        ["What is X?", "--skip-clarify", "--thread-id", "a/b"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert code == 0


def test_a_trace_path_equal_to_exact_db_is_refused_before_the_graph_runs(
    tmp_path, capsys
):
    db = tmp_path / "exact.sqlite"
    exa = FakeExa()
    with pytest.raises(SystemExit) as exc:
        _traced(db, rt=runtime(exa=exa, exact_db=str(db)))
    assert str(exc.value) == (
        f"trace: {db.resolve()} is the checkpoint database; "
        "pass a different --trace-path"
    )
    assert capsys.readouterr().out == ""
    assert exa.search_nums == []
    assert not db.exists()


def test_an_unwritable_trace_directory_is_refused(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    path = blocker / "run.jsonl"
    with pytest.raises(SystemExit) as exc:
        _traced(path)
    assert str(exc.value).startswith(f"trace: cannot write {path.resolve()}: ")
    assert capsys.readouterr().out == ""


def test_the_trace_line_follows_the_thread_id_line_and_precedes_the_echo(
    tmp_path, capsys
):
    path = tmp_path / "run.jsonl"
    _traced(path, "t-order")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "thread_id=t-order"
    assert lines[1] == f"trace={path.resolve()}"
    assert lines[2].startswith("effort=")


def test_the_first_run_of_a_new_thread_id_under_trace_prints_no_warning(
    tmp_path, capsys
):
    _traced(tmp_path / "run.jsonl", "t-new")
    assert capsys.readouterr().err == ""


def test_a_trace_off_run_creates_no_file_and_no_traces_directory(
    isolated_env, tmp_path
):
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-off"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert not (tmp_path / "traces").exists()


def test_a_trace_off_resume_whose_file_exists_warns_and_keeps_stdout(
    isolated_env, tmp_path, capsys
):
    argv = ["What is X?", "--skip-clarify", "--thread-id", "t-w1"]
    main(argv, runtime=runtime(), checkpointer=InMemorySaver())
    baseline = capsys.readouterr().out
    derived = tmp_path / "traces" / "t-w1.jsonl"
    derived.parent.mkdir()
    derived.write_text("")
    main(argv, runtime=runtime(), checkpointer=InMemorySaver())
    captured = capsys.readouterr()
    assert captured.out == baseline
    assert captured.err == (
        f"warning: trace off; {derived.resolve()} holds earlier turns of this thread\n"
    )


def test_a_resume_whose_trace_path_is_absent_warns(tmp_path, capsys):
    saver = InMemorySaver()
    llm = _parking_llm()
    _traced(
        tmp_path / "first.jsonl",
        "t-w2",
        rt=runtime(llm=llm),
        saver=saver,
        skip_clarify=False,
    )
    capsys.readouterr()
    second = tmp_path / "second.jsonl"
    _traced(
        second,
        "t-w2",
        rt=runtime(llm=llm),
        saver=saver,
        read_reply=lambda: "skip",
        skip_clarify=False,
    )
    assert capsys.readouterr().err == (
        f"warning: thread t-w2 resumes, but {second.resolve()} did not exist; "
        "pass the same --trace-path as the first run\n"
    )


def test_a_resume_with_the_same_trace_path_prints_no_warning(tmp_path, capsys):
    path = tmp_path / "run.jsonl"
    saver = InMemorySaver()
    rt = runtime(llm=_parking_llm())
    _traced(path, "t-same", rt=rt, saver=saver, skip_clarify=False)
    capsys.readouterr()
    _traced(
        path,
        "t-same",
        rt=rt,
        saver=saver,
        read_reply=lambda: "skip",
        skip_clarify=False,
    )
    assert capsys.readouterr().err == ""


def test_a_trace_off_named_thread_with_no_file_prints_no_warning(isolated_env, capsys):
    main(
        ["What is X?", "--skip-clarify", "--thread-id", "t-quiet"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert capsys.readouterr().err == ""


def test_a_trace_path_holding_another_thread_warns(tmp_path, capsys):
    path = tmp_path / "run.jsonl"
    path.write_text('{"thread_id": "t-other"}\n')
    _traced(path, "t-w3")
    assert capsys.readouterr().err == (
        f"warning: {path.resolve()} holds lines for thread t-other; "
        "this run is thread t-w3\n"
    )


def test_a_first_line_that_is_not_json_prints_no_warning(tmp_path, capsys):
    path = tmp_path / "run.jsonl"
    path.write_text("not json\n")
    _traced(path, "t-w3")
    assert capsys.readouterr().err == ""


def test_a_finished_run_writes_one_run_start_and_one_finished_run_end(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path)
    kinds = _kinds(path)
    assert kinds.count("run_start") == 1
    assert kinds[-1] == "run_end"
    assert _one(path, "run_end") == {
        "outcome": "finished",
        "dangling": 0,
        "dropped": 0,
        "error": None,
    }


def test_the_run_start_line_records_the_query_and_the_run_shape(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path)
    start = _one(path, "run_start")
    assert set(start) == {"query", "verbose", "resume", "settings"}
    assert (start["query"], start["verbose"], start["resume"]) == (
        "What is X?",
        False,
        False,
    )


def test_the_clarify_pause_ends_the_run_interrupted(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path, rt=runtime(llm=_parking_llm()), skip_clarify=False)
    assert _one(path, "run_end")["outcome"] == "interrupted"


def test_a_resume_appends_the_same_file_under_a_new_run_id(tmp_path):
    path = tmp_path / "run.jsonl"
    saver = InMemorySaver()
    rt = runtime(llm=_parking_llm())
    _traced(path, "t-app", rt=rt, saver=saver, skip_clarify=False)
    _traced(
        path,
        "t-app",
        rt=rt,
        saver=saver,
        read_reply=lambda: "skip",
        skip_clarify=False,
    )
    lines = read_trace(path)
    starts = [line for line in lines if line["kind"] == "run_start"]
    assert len(starts) == 2
    assert starts[0]["run_id"] != starts[1]["run_id"]
    assert starts[1]["data"]["resume"] is True
    assert [line["data"]["outcome"] for line in lines if line["kind"] == "run_end"] == [
        "interrupted",
        "finished",
    ]


def test_a_second_run_of_a_finished_thread_ends_rejected(tmp_path):
    path = tmp_path / "run.jsonl"
    saver = InMemorySaver()
    _traced(tmp_path / "first.jsonl", "t-rej", saver=saver)
    with pytest.raises(SystemExit):
        _traced(path, "t-rej", saver=saver)
    assert _one(path, "run_end") == {
        "outcome": "rejected",
        "dangling": None,
        "dropped": 0,
        "error": "thread already finished; use a new --thread-id",
    }


def test_a_keyboard_interrupt_at_the_prompt_ends_the_run_interrupted(tmp_path):
    path = tmp_path / "run.jsonl"
    saver = InMemorySaver()
    rt = runtime(llm=_parking_llm())
    _traced(tmp_path / "first.jsonl", "t-kbd", rt=rt, saver=saver, skip_clarify=False)

    def interrupt() -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _traced(
            path, "t-kbd", rt=rt, saver=saver, read_reply=interrupt, skip_clarify=False
        )
    assert _one(path, "run_end")["outcome"] == "interrupted"


class _FailingWriter(FakeLLM):
    """A write-role model whose vendor call fails."""

    def invoke(self, messages, **_kwargs):
        raise RuntimeError("write model down")


def test_a_failing_write_model_ends_the_run_with_error(tmp_path):
    path = tmp_path / "run.jsonl"
    with pytest.raises(RuntimeError):
        _traced(path, rt=runtime(llms={"write": _FailingWriter()}))
    assert _one(path, "run_end") == {
        "outcome": "error",
        "dangling": None,
        "dropped": 0,
        "error": "RuntimeError: write model down",
    }


def test_a_dangling_citation_run_is_finished_with_a_dangling_count(tmp_path):
    path = tmp_path / "run.jsonl"
    code = _traced(path, rt=runtime(llm=FakeLLM(report="Claim [src_missing].")))
    assert code == 1
    end = _one(path, "run_end")
    assert end["outcome"] == "finished"
    assert end["dangling"] == 1


def test_an_effort_mismatch_exit_writes_no_line(tmp_path):
    path = tmp_path / "run.jsonl"
    saver = InMemorySaver()
    llm = _parking_llm()
    _traced(path, "t-mis", rt=runtime(llm=llm), saver=saver, skip_clarify=False)
    before = path.read_bytes()
    with pytest.raises(SystemExit) as exc:
        _traced(
            path,
            "t-mis",
            rt=runtime(llm=llm, exact_effort="max"),
            saver=saver,
            read_reply=lambda: "skip",
            skip_clarify=False,
        )
    assert "effort mismatch" in str(exc.value)
    assert path.read_bytes() == before


class _BrokenReportPipe(io.StringIO):
    """A stdout whose reader goes away once the report starts."""

    def write(self, text: str) -> int:
        if "## References" in text:
            raise BrokenPipeError("reader closed")
        return super().write(text)


def test_a_failure_while_printing_the_report_ends_the_run_with_error(
    tmp_path, monkeypatch
):
    path = tmp_path / "run.jsonl"
    monkeypatch.setattr(sys, "stdout", _BrokenReportPipe())
    with pytest.raises(BrokenPipeError):
        _traced(path)
    assert _kinds(path)[-1] == "run_end"
    assert _one(path, "run_end")["outcome"] == "error"
    assert _one(path, "run_end")["error"].startswith("BrokenPipeError")


_EFFORT_KEYS = {
    "effort",
    "max_iterations",
    "max_clarify_turns",
    "max_topics_first_wave",
    "max_topics_followup",
    "max_tool_rounds",
    "max_hits",
    "max_concurrency",
}


def test_the_settings_snapshot_holds_the_caps_and_the_model_settings(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(
        path,
        rt=runtime(
            exact_model="anthropic:m-default",
            exact_model_write="anthropic:m-write",
            exact_thinking_budget=2048,
        ),
    )
    settings = _one(path, "run_start")["settings"]
    assert set(settings) == _EFFORT_KEYS | {
        "prefs",
        "models",
        "max_tokens",
        "temperature",
        "thinking_budget",
    }
    assert settings["models"] == {
        "router": "anthropic:m-default",
        "research": "anthropic:m-default",
        "compress": "anthropic:m-default",
        "write": "anthropic:m-write",
    }
    # The configured values, not the rewrite thinking applies to a request.
    assert settings["max_tokens"] == {
        "router": 1024,
        "research": 1024,
        "compress": 2048,
        "write": 8192,
    }
    assert (settings["temperature"], settings["thinking_budget"]) == (0.0, 2048)


def test_the_settings_snapshot_holds_no_api_key(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path)
    text = path.read_text()
    assert not any(k.endswith("_api_key") for k in _one(path, "run_start")["settings"])
    assert "api_key" not in text


def _two_topic_llm(**kwargs) -> FakeLLM:
    return FakeLLM(plan=PlanDecision(topics=["alpha", "beta"], reason="two"), **kwargs)


def test_a_two_topic_wave_writes_one_finding_and_one_status_line_per_topic(
    tmp_path, capsys
):
    path = tmp_path / "run.jsonl"
    _traced(path, rt=runtime(llm=_two_topic_llm()))
    findings = [line["data"] for line in read_trace(path) if line["kind"] == "finding"]
    assert sorted(f["topic_id"] for f in findings) == ["t0_1", "t0_2"]
    out = capsys.readouterr().out.splitlines()
    assert sum(line.startswith("[research t0_1]") for line in out) == 1
    assert sum(line.startswith("[research t0_2]") for line in out) == 1


def test_a_full_run_writes_every_sink_kind(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path)
    kinds = set(_kinds(path))
    assert {"brief", "plan", "decision", "finding", "usage", "report_refs"} <= kinds


def test_a_finished_run_writes_one_report_refs_line_before_run_end(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path)
    kinds = _kinds(path)
    assert kinds.count("report_refs") == 1
    assert kinds[-2:] == ["report_refs", "run_end"]
    assert set(_one(path, "report_refs")) == {"cited", "uncited", "dangling"}


def test_an_unminted_citation_is_dangling_and_an_unused_source_is_uncited(tmp_path):
    path = tmp_path / "run.jsonl"
    llm = FakeLLM(report="A [src_t0_1_1]. B [src_missing].")
    exa = FakeExa(hits=[source(title="A"), source(title="B")])
    _traced(path, rt=runtime(llm=llm, exa=exa))
    assert _one(path, "report_refs") == {
        "cited": ["src_missing", "src_t0_1_1"],
        "uncited": ["src_t0_1_2"],
        "dangling": ["src_missing"],
    }


def test_an_interrupted_run_writes_no_report_refs_line(tmp_path):
    path = tmp_path / "run.jsonl"
    _traced(path, rt=runtime(llm=_parking_llm()), skip_clarify=False)
    assert "report_refs" not in _kinds(path)


# ─── Verbose ────────────────────────────────────────────────────────────


def _detail_llm() -> FakeLLM:
    return FakeLLM(
        finding=Finding(
            topic_id="t0_1",
            claims=["X is Y"],
            source_ids=["src_t0_1_1"],
            gaps=["no safety data"],
            covered=["define X"],
        ),
        reflect=ReflectDecision(done=True, followups=[], uncovered=["dose"]),
        report="X is Y [src_t0_1_1]. Z [src_missing].",
    )


# The status lines of ``_detail_llm`` before verbose existed, byte for byte.
_DEFAULT_STATUS = [
    "[scout] 1 web · 0 papers",
    "[clarify] skip",
    "[brief] intent=web  must_cover=1",
    "  What is X?",
    "[plan] wave 0 — 1 topic",
    "  t0_1 [web]  define X",
    "[research t0_1] 1 source  · 1 exa_search",
    "[reflect] write",
    "[write]",
    "[audit] 1 unresolved citation",
]

_VERBOSE_STATUS = [
    "[scout] 1 web · 0 papers",
    "[clarify] skip",
    "[brief] intent=web  must_cover=1",
    "  What is X?",
    "  - define X",
    "[plan] wave 0 — 1 topic",
    "  t0_1 [web]  define X",
    "[research t0_1] 1 source  · 1 exa_search",
    "  gap: no safety data",
    "[reflect] write",
    "  uncovered: dose",
    "[write]",
    "[audit] 1 unresolved citation",
    "  dangling: src_missing",
]


def _status_lines(out: str) -> list[str]:
    """The lines between the two echo lines and the report."""
    lines = out.splitlines()
    return lines[3 : lines.index("")]


def test_a_default_run_prints_the_status_lines_byte_for_byte(capsys):
    main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(llm=_detail_llm()),
        checkpointer=InMemorySaver(),
    )
    assert _status_lines(capsys.readouterr().out) == _DEFAULT_STATUS


def test_the_verbose_flag_prints_the_four_detail_groups(capsys):
    main(
        ["What is X?", "--skip-clarify", "--verbose"],
        runtime=runtime(llm=_detail_llm()),
        checkpointer=InMemorySaver(),
    )
    assert _status_lines(capsys.readouterr().out) == _VERBOSE_STATUS


def test_the_no_verbose_flag_overrides_the_verbose_env(monkeypatch, capsys):
    monkeypatch.setenv("EXACT_VERBOSE", "1")
    main(
        ["What is X?", "--skip-clarify", "--no-verbose"],
        runtime=runtime(llm=_detail_llm()),
        checkpointer=InMemorySaver(),
    )
    assert _status_lines(capsys.readouterr().out) == _DEFAULT_STATUS


def test_the_clarify_resume_prints_the_detail_lines(capsys):
    saver = InMemorySaver()
    llm = _detail_llm()
    llm.clarify = _parking_llm().clarify
    argv = ["What is X?", "--thread-id", "t-vres", "--verbose"]
    main(argv, runtime=runtime(llm=llm), checkpointer=saver)
    capsys.readouterr()
    main(argv, runtime=runtime(llm=llm), checkpointer=saver, read_reply=lambda: "skip")
    out = capsys.readouterr().out.splitlines()
    for detail in ("  - define X", "  gap: no safety data", "  uncovered: dose"):
        assert detail in out
    assert "  dangling: src_missing" in out


def test_the_verbose_flag_alone_writes_no_sidecar(isolated_env, tmp_path):
    main(
        ["What is X?", "--skip-clarify", "--verbose"],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
    )
    assert not (tmp_path / "traces").exists()


@pytest.mark.parametrize(
    "flags, env, expected",
    [
        ([], None, False),
        (["--verbose"], None, True),
        ([], "1", True),
        (["--no-verbose"], "1", False),
    ],
)
def test_run_start_records_the_resolved_verbose_flag(
    tmp_path, monkeypatch, flags: list[str], env: str | None, expected: bool
):
    if env is not None:
        monkeypatch.setenv("EXACT_VERBOSE", env)
    path = tmp_path / "run.jsonl"
    _traced(path, "t-v", *flags)
    assert _one(path, "run_start")["verbose"] is expected


# ─── User preferences ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "flags, name, raw, field, expected",
    [
        (["--lang", "es"], "EXACT_LANGUAGE", "pt", "exact_language", "es"),
        (["--tone", "plain"], "EXACT_TONE", "academic", "exact_tone", "plain"),
        (["--length", "short"], "EXACT_LENGTH", "long", "exact_length", "short"),
        (
            ["--structure", "memo"],
            "EXACT_STRUCTURE",
            "bullets",
            "exact_structure",
            "memo",
        ),
        (
            ["--sources", "web"],
            "EXACT_SOURCE_MIX",
            "academic",
            "exact_source_mix",
            "web",
        ),
        (
            ["--include-domain", "a.com"],
            "EXACT_INCLUDE_DOMAINS",
            "b.com",
            "exact_include_domains",
            ["a.com"],
        ),
        (
            ["--exclude-domain", "a.com"],
            "EXACT_EXCLUDE_DOMAINS",
            "b.com",
            "exact_exclude_domains",
            ["a.com"],
        ),
        (["--denylist", "seo"], "EXACT_DENYLIST", "social", "exact_denylist", "seo"),
        (["--since", "week"], "EXACT_RECENCY", "year", "exact_recency", "week"),
        (
            ["--prefer-primary"],
            "EXACT_PREFER_PRIMARY",
            "0",
            "exact_prefer_primary",
            True,
        ),
        (["--news"], "EXACT_NEWS_BIAS", "0", "exact_news_bias", True),
        (
            ["--clarify", "prefer"],
            "EXACT_CLARIFY_MODE",
            "skip",
            "exact_clarify_mode",
            "prefer",
        ),
    ],
)
def test_a_preference_flag_wins_over_its_env(
    isolated_env, monkeypatch, flags: list[str], name: str, raw: str, field, expected
):
    monkeypatch.setenv(name, raw)
    seen = _record_settings(monkeypatch)
    main(["What is X?", *flags], checkpointer=InMemorySaver())
    assert getattr(seen[0], field) == expected


def test_a_preference_no_news_flag_overrides_the_news_env(isolated_env, monkeypatch):
    monkeypatch.setenv("EXACT_NEWS_BIAS", "1")
    seen = _record_settings(monkeypatch)
    main(["What is X?", "--skip-clarify", "--no-news"], checkpointer=InMemorySaver())
    assert seen[0].exact_news_bias is False


def test_a_preference_exclude_domain_flag_replaces_the_env_list(
    isolated_env, monkeypatch
):
    monkeypatch.setenv("EXACT_EXCLUDE_DOMAINS", "a.com, b.com")
    seen = _record_settings(monkeypatch)
    main(["What is X?", "--skip-clarify"], checkpointer=InMemorySaver())
    main(
        ["What is X?", "--skip-clarify", "--exclude-domain", "c.com"],
        checkpointer=InMemorySaver(),
    )
    assert seen[0].exact_exclude_domains == ["a.com", "b.com"]
    assert seen[1].exact_exclude_domains == ["c.com"]


def test_a_preference_skip_clarify_flag_resolves_clarify_mode_skip(
    isolated_env, monkeypatch
):
    seen = _record_settings(monkeypatch)
    main(["What is X?"], checkpointer=InMemorySaver())
    main(["What is X?", "--skip-clarify"], checkpointer=InMemorySaver())
    assert [s.exact_clarify_mode for s in seen] == ["auto", "skip"]


_EXCLUDE_SOURCE = "(--exclude-domain or EXACT_EXCLUDE_DOMAINS)"
_INCLUDE_CONFLICT = (
    "include domains cannot combine with exclude domains or a denylist "
    "(--include-domain, --exclude-domain, --denylist)"
)


def _many_hosts(n: int) -> list[str]:
    return [arg for i in range(n) for arg in ("--exclude-domain", f"h{i}.com")]


@pytest.mark.parametrize(
    "flags, message",
    [
        (
            ["--tone", "Executive"],
            "tone must be one of 'neutral', 'academic', 'executive', 'plain'; "
            "got 'Executive' (--tone or EXACT_TONE)",
        ),
        (
            ["--lang", "fr"],
            "language must be one of 'auto', 'en', 'es', 'pt'; "
            "got 'fr' (--lang or EXACT_LANGUAGE)",
        ),
        (
            _many_hosts(21),
            f"exclude_domains holds 21 hosts; at most 20 {_EXCLUDE_SOURCE}",
        ),
        *(
            (
                ["--exclude-domain", entry],
                f"exclude_domains: {entry!r} is not a host name {_EXCLUDE_SOURCE}",
            )
            for entry in (
                "https://a.com",
                "*.a.com",
                "a.com/blog",
                "localhost",
                "a.com.",
                "münchen.de",
            )
        ),
        (["--include-domain", "a.com", "--exclude-domain", "b.com"], _INCLUDE_CONFLICT),
        (["--include-domain", "a.com", "--denylist", "social"], _INCLUDE_CONFLICT),
        (
            ["--skip-clarify", "--clarify", "prefer"],
            "--skip-clarify cannot combine with --clarify prefer",
        ),
    ],
)
def test_an_invalid_preference_exits_with_its_message_before_the_key_check(
    isolated_env, monkeypatch, flags: list[str], message: str
):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["What is X?", *flags], checkpointer=InMemorySaver())
    assert str(exc.value) == message


def test_a_preference_list_of_20_hosts_and_a_punycode_host_are_valid(
    isolated_env, monkeypatch
):
    seen = _record_settings(monkeypatch)
    flags = [*_many_hosts(19), "--exclude-domain", "xn--mnchen-3ya.de"]
    main(["What is X?", "--skip-clarify", *flags], checkpointer=InMemorySaver())
    hosts = seen[0].exact_exclude_domains
    assert len(hosts) == 20
    assert hosts[-1] == "xn--mnchen-3ya.de"


def test_an_invalid_effort_beside_an_invalid_preference_reports_the_effort(
    isolated_env, monkeypatch
):
    _record_settings(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--effort", "bogus", "--tone", "Executive"],
            checkpointer=InMemorySaver(),
        )
    assert str(exc.value).startswith("effort must be 'normal' or 'max'")


def test_an_invalid_preference_beside_an_invalid_trace_env_reports_the_preference(
    isolated_env, monkeypatch
):
    monkeypatch.setenv("EXACT_TRACE", "maybe")
    _record_settings(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main(["What is X?", "--tone", "Executive"], checkpointer=InMemorySaver())
    assert str(exc.value).startswith("tone must be one of")


def test_an_invalid_preference_flag_with_an_injected_runtime_exits(isolated_env):
    with pytest.raises(SystemExit) as exc:
        main(
            ["What is X?", "--tone", "Executive"],
            runtime=runtime(),
            checkpointer=InMemorySaver(),
        )
    assert str(exc.value).startswith("tone must be one of")


def test_preference_flags_reach_an_injected_runtime_but_effort_does_not(capsys):
    saver = InMemorySaver()
    rt = runtime()
    main(
        ["What is X?", "--tone", "plain", "--skip-clarify", "--effort", "max"],
        runtime=rt,
        checkpointer=saver,
        new_id=lambda: "t-inject",
    )
    assert "effort=normal" in capsys.readouterr().out
    config = thread_config("t-inject", max_concurrency=3)
    prefs = build_graph(rt, checkpointer=saver).get_state(config).values["prefs"]
    assert (prefs["tone"], prefs["clarify_mode"]) == ("plain", "skip")


# ─── Preference resume guard and echo ───────────────────────────────────


def _park(saver, thread: str, *flags: str, rt=None) -> None:
    """Start a thread that stops at the clarify question."""
    main(
        ["What is X?", "--thread-id", thread, *flags],
        runtime=rt or runtime(llm=_parking_llm()),
        checkpointer=saver,
    )


def _resume(saver, thread: str, *flags: str, rt=None) -> int:
    return main(
        ["What is X?", "--thread-id", thread, *flags],
        runtime=rt or runtime(llm=_parking_llm()),
        checkpointer=saver,
        read_reply=lambda: "skip",
    )


_MISMATCH_TAIL = "rerun with the same preferences or use a new --thread-id"


def test_a_resume_with_another_preference_exits_with_the_mismatch_message(
    tmp_path, capsys
):
    path = tmp_path / "run.jsonl"
    saver = InMemorySaver()
    rt = runtime(llm=_parking_llm())
    _traced(path, "t-pm", rt=rt, saver=saver, skip_clarify=False)
    before = path.read_bytes()
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        _traced(
            path,
            "t-pm",
            "--tone",
            "plain",
            "--since",
            "week",
            rt=rt,
            saver=saver,
            skip_clarify=False,
        )
    assert str(exc.value) == (
        "preference mismatch: tone thread=neutral run=plain; "
        f"recency thread=any run=week; {_MISMATCH_TAIL}"
    )
    assert path.read_bytes() == before
    assert "effort=" not in capsys.readouterr().out


def test_a_resume_with_the_same_hosts_in_another_order_continues(capsys):
    saver = InMemorySaver()
    _park(saver, "t-hosts", "--exclude-domain", "b.com", "--exclude-domain", "a.com")
    code = _resume(
        saver, "t-hosts", "--exclude-domain", "a.com", "--exclude-domain", "b.com"
    )
    assert code == 0
    assert "X is Y [src_t0_1_1]." in capsys.readouterr().out


def test_a_resume_with_skip_clarify_of_an_auto_thread_exits(capsys):
    saver = InMemorySaver()
    _park(saver, "t-auto")
    with pytest.raises(SystemExit) as exc:
        _resume(saver, "t-auto", "--skip-clarify")
    assert str(exc.value) == (
        f"preference mismatch: clarify_mode thread=auto run=skip; {_MISMATCH_TAIL}"
    )


def test_a_resume_of_a_thread_without_prefs_uses_default_preferences(capsys):
    saver = InMemorySaver()
    rt = runtime(llm=_parking_llm())
    seed = graph_seed()
    del seed["prefs"]
    build_graph(rt, checkpointer=saver).invoke(
        seed, thread_config("t-noprefs", max_concurrency=3)
    )
    capsys.readouterr()
    assert _resume(saver, "t-noprefs", rt=rt) == 0
    assert "prefs=default" in capsys.readouterr().out.splitlines()


class _LegacyState(TypedDict):
    initial_query: str
    effort: str
    skip_clarify: bool


def _write_legacy_thread(saver, thread: str) -> None:
    """A finished checkpoint whose state still holds the ``skip_clarify`` channel."""
    graph = StateGraph(_LegacyState)
    graph.add_node("old", lambda state: {"effort": state["effort"]})
    graph.add_edge(START, "old")
    graph.add_edge("old", END)
    graph.compile(checkpointer=saver).invoke(
        {"initial_query": "What is X?", "effort": "normal", "skip_clarify": True},
        thread_config(thread, max_concurrency=3),
    )


def test_a_resume_of_a_legacy_skip_clarify_thread_needs_skip_clarify(capsys):
    saver = InMemorySaver()
    _write_legacy_thread(saver, "t-legacy")
    with pytest.raises(SystemExit) as finished:
        _resume(saver, "t-legacy", "--skip-clarify")
    with pytest.raises(SystemExit) as mismatch:
        _resume(saver, "t-legacy")
    assert "thread already finished" in str(finished.value)
    assert str(mismatch.value) == (
        f"preference mismatch: clarify_mode thread=skip run=auto; {_MISMATCH_TAIL}"
    )


def test_a_resume_with_other_effort_and_preference_reports_the_effort(capsys):
    saver = InMemorySaver()
    _park(saver, "t-both")
    with pytest.raises(SystemExit) as exc:
        _resume(
            saver,
            "t-both",
            "--tone",
            "plain",
            rt=runtime(llm=_parking_llm(), exact_effort="max"),
        )
    assert str(exc.value).startswith("effort mismatch")


_NORMAL_ECHO = (
    "effort=normal waves=3 topics=3/2 rounds=4 hits=5 clarify=3 concurrency=3"
)


def _start_lines(capsys, *flags: str) -> list[str]:
    main(["What is X?", *flags], runtime=runtime(), checkpointer=InMemorySaver())
    return capsys.readouterr().out.splitlines()


def test_the_prefs_line_follows_the_effort_line(capsys):
    default = _start_lines(capsys)
    chosen = _start_lines(
        capsys,
        "--tone",
        "plain",
        "--exclude-domain",
        "b.com",
        "--exclude-domain",
        "a.com",
    )
    assert default[1:3] == [_NORMAL_ECHO, "prefs=default"]
    assert chosen[1:3] == [_NORMAL_ECHO, "prefs tone=plain exclude_domains=b.com,a.com"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--lang", "es"],
        ["--tone", "academic"],
        ["--length", "long"],
        ["--structure", "bullets"],
        ["--sources", "academic"],
        ["--include-domain", "a.com"],
        ["--exclude-domain", "a.com"],
        ["--denylist", "social"],
        ["--since", "year"],
        ["--prefer-primary"],
        ["--news"],
        ["--clarify", "skip"],
    ],
)
def test_every_preference_leaves_the_effort_line_unchanged(capsys, flags: list[str]):
    assert _start_lines(capsys)[1] == _NORMAL_ECHO
    assert _start_lines(capsys, *flags)[1] == _NORMAL_ECHO


def test_the_run_start_settings_hold_the_full_prefs_dict(tmp_path):
    path = tmp_path / "run.jsonl"
    main(
        [
            "What is X?",
            "--skip-clarify",
            "--since",
            "week",
            "--denylist",
            "social",
            "--trace",
            "--trace-path",
            str(path),
        ],
        runtime=runtime(),
        checkpointer=InMemorySaver(),
        now=lambda: SEED_INSTANT,
    )
    assert _one(path, "run_start")["settings"]["prefs"] == {
        "language": "auto",
        "tone": "neutral",
        "length": "standard",
        "structure": "report",
        "source_mix": "auto",
        "include_domains": [],
        "exclude_domains": [],
        "denylist": "social",
        "recency": "week",
        "prefer_primary": False,
        "news_bias": False,
        "clarify_mode": "skip",
        "start_published_date": "2026-09-14",
        "effective_exclude_domains": [
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "x.com",
            "twitter.com",
            "reddit.com",
            "pinterest.com",
            "linkedin.com",
        ],
    }


def test_a_resume_echoes_the_checkpoint_prefs_in_stored_order(capsys):
    saver = InMemorySaver()
    _park(saver, "t-echo", "--exclude-domain", "b.com", "--exclude-domain", "a.com")
    capsys.readouterr()
    _resume(saver, "t-echo", "--exclude-domain", "a.com", "--exclude-domain", "b.com")
    assert (
        capsys.readouterr().out.splitlines()[2] == "prefs exclude_domains=b.com,a.com"
    )


def test_a_resume_a_day_later_reuses_the_stored_start_date(capsys):
    saver = InMemorySaver()
    exa = FakeExa()
    rt = runtime(llm=_parking_llm(), exa=exa)
    day_one = SEED_INSTANT
    day_two = SEED_INSTANT + timedelta(days=1)
    main(
        ["What is X?", "--thread-id", "t-day", "--since", "week"],
        runtime=rt,
        checkpointer=saver,
        now=lambda: day_one,
    )
    main(
        ["What is X?", "--thread-id", "t-day", "--since", "week"],
        runtime=rt,
        checkpointer=saver,
        read_reply=lambda: "skip",
        now=lambda: day_two,
    )
    research = exa.search_filters[1:]
    assert research
    assert {f["start_published_date"] for f in research} == {"2026-09-14"}


@pytest.mark.parametrize(
    "name, message",
    [
        (
            "EXACT_PREFER_PRIMARY",
            "prefer_primary must be a boolean such as 0 or 1; got 'maybe' "
            "(--prefer-primary or EXACT_PREFER_PRIMARY)",
        ),
        (
            "EXACT_NEWS_BIAS",
            "news_bias must be a boolean such as 0 or 1; got 'maybe' "
            "(--news or EXACT_NEWS_BIAS)",
        ),
    ],
)
def test_an_invalid_boolean_preference_env_exits_with_its_message(
    isolated_env, monkeypatch, name: str, message: str
):
    monkeypatch.setenv(name, "maybe")
    with pytest.raises(SystemExit) as exc:
        main(["What is X?"], checkpointer=InMemorySaver())
    assert str(exc.value) == message
