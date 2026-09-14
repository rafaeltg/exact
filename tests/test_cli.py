from __future__ import annotations

import sqlite3

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from exact.cli import main, thread_config
from exact.models import ClarificationOption, ClarifyDecision
from tests.fakes import FakeLLM, runtime


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


def test_thread_config_sets_max_concurrency_to_3():
    assert thread_config("t") == {
        "configurable": {"thread_id": "t", "max_concurrency": 3}
    }


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


def test_dangling_citations_fail_qa(capsys):
    code = main(
        ["What is X?", "--skip-clarify"],
        runtime=runtime(llm=FakeLLM(report="Claim [src_missing].")),
        checkpointer=InMemorySaver(),
    )
    assert code == 1
    assert "## Audit" in capsys.readouterr().out
