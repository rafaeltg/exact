from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from exact.cli import main, thread_config
from exact.graph import build_graph
from exact.models import (
    ClarificationOption,
    ClarifyDecision,
    Finding,
    PlanDecision,
    ReflectDecision,
)
from tests.fakes import FakeExa, FakeLLM, graph_seed, read_trace, runtime, source


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
    seed = graph_seed(skip_clarify=False)
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
    """The lines between the echo line and the report."""
    lines = out.splitlines()
    return lines[2 : lines.index("")]


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
