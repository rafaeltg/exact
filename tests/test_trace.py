from __future__ import annotations

import threading

import pytest

from exact.trace import JsonlTracer, NullTracer, crumb, wave_of
from tests.fakes import read_trace

_ENVELOPE_KEYS = {"v", "ts", "run_id", "thread_id", "seq", "kind", "data"}


def test_a_null_tracer_writes_no_file(tmp_path):
    tracer = NullTracer()
    tracer.emit("run_start", {"query": "q"})
    tracer.close()
    assert list(tmp_path.iterdir()) == []
    assert tracer.dropped == 0


def test_a_jsonl_tracer_appends_one_flushed_line_per_emit(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = JsonlTracer(path, "t-1")
    tracer.emit("brief", {"intent": "web"})
    # Read before close: each line is on disk as soon as it is emitted.
    lines = read_trace(path)
    tracer.emit("plan", {"wave": 0})
    tracer.close()
    assert len(lines) == 1
    assert set(lines[0]) == _ENVELOPE_KEYS
    assert lines[0]["v"] == 1
    assert lines[0]["thread_id"] == "t-1"
    assert lines[0]["kind"] == "brief"
    assert lines[0]["data"] == {"intent": "web"}
    assert [line["kind"] for line in read_trace(path)] == ["brief", "plan"]


def test_seq_starts_at_one_and_rises_by_one(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = JsonlTracer(path, "t-1")
    for _ in range(3):
        tracer.emit("usage", {})
    tracer.close()
    assert [line["seq"] for line in read_trace(path)] == [1, 2, 3]


def test_a_second_open_of_one_path_takes_a_new_run_id(tmp_path):
    path = tmp_path / "t.jsonl"
    for _ in range(2):
        tracer = JsonlTracer(path, "t-1")
        tracer.emit("run_start", {})
        tracer.close()
    first, second = read_trace(path)
    assert first["run_id"] != second["run_id"]
    assert first["seq"] == second["seq"] == 1


def test_ten_threads_emitting_at_once_produce_ten_parsable_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    tracer = JsonlTracer(path, "t-1")
    threads = [
        threading.Thread(target=tracer.emit, args=("tool", {"i": i})) for i in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    tracer.close()
    lines = read_trace(path)
    assert sorted(line["data"]["i"] for line in lines) == list(range(10))
    assert sorted(line["seq"] for line in lines) == list(range(1, 11))


def test_an_unserializable_payload_is_one_drop_and_one_warning(tmp_path, capsys):
    path = tmp_path / "t.jsonl"
    tracer = JsonlTracer(path, "t-1")
    tracer.emit("tool", {"bad": object()})
    tracer.emit("tool", {"ok": True})
    tracer.close()
    assert tracer.dropped == 1
    assert capsys.readouterr().err.startswith("warning: trace write failed: ")
    assert [line["seq"] for line in read_trace(path)] == [1]


def test_a_second_drop_prints_no_second_warning(tmp_path, capsys):
    tracer = JsonlTracer(tmp_path / "t.jsonl", "t-1")
    tracer.emit("tool", {"bad": object()})
    tracer.emit("tool", {"bad": object()})
    tracer.close()
    err = capsys.readouterr().err
    assert tracer.dropped == 2
    assert err.count("warning: trace write failed") == 1
    assert "later failures are counted in run_end" in err


def test_an_emit_after_close_changes_nothing(tmp_path, capsys):
    path = tmp_path / "t.jsonl"
    tracer = JsonlTracer(path, "t-1")
    tracer.emit("run_end", {})
    tracer.close()
    before = path.read_bytes()
    tracer.emit("tool", {"late": True})
    assert path.read_bytes() == before
    assert tracer.dropped == 0
    assert capsys.readouterr().err == ""


def test_crumb_reads_the_four_keys_and_nothing_else():
    row = {
        "id": "src_t0_1_1",
        "title": "A",
        "url": "https://a.example",
        "doi": "10.1/x",
        "snippet": "body",
    }
    assert crumb(row) == {
        "id": "src_t0_1_1",
        "title": "A",
        "url": "https://a.example",
        "doi": "10.1/x",
    }


def test_crumb_writes_none_for_each_key_the_row_omits():
    assert crumb({"id": "src_scout_1"}) == {
        "id": "src_scout_1",
        "title": None,
        "url": None,
        "doi": None,
    }


@pytest.mark.parametrize("topic_id, wave", [("t0_1", 0), ("t2_3", 2), ("t12_1", 12)])
def test_wave_of_reads_the_wave_of_a_research_topic_id(topic_id: str, wave: int):
    assert wave_of(topic_id) == wave


@pytest.mark.parametrize("topic_id", [None, "scout", "t", "tx_1", "0_1"])
def test_wave_of_is_none_for_an_id_outside_the_grammar(topic_id: str | None):
    assert wave_of(topic_id) is None
