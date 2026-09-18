from __future__ import annotations

import sqlite3

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from exact.cli import main, thread_config
from exact.graph import build_graph
from exact.models import ClarificationOption, ClarifyDecision
from tests.fakes import FakeLLM, graph_seed, runtime


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
