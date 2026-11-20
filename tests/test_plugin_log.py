"""Tests for burt/plugin_log.py — spec §38, §39.

Covers: ring buffer, 12h rotation file naming, JSONL record shape, level
filtering, DEBUG payload policy, session summary, crash reports, sync and
async write paths, queue overflow.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

import config
from burt.plugin_log import (
    LEVEL_DEBUG, LEVEL_ERROR, LEVEL_INFO, LEVEL_WARN,
    PluginLogger, RingBuffer, preview_payload,
)
from burt.trace import Trace


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

FIXED = datetime(2026, 10, 11, 21, 40, 0, 123000)


def make_logger(tmp_path: Path, **kwargs) -> PluginLogger:
    params = dict(
        log_dir=tmp_path / "logs",
        crash_dir=tmp_path / "crashes",
        trace=Trace(session_uuid="test-session"),
        clock=lambda: FIXED,
    )
    params.update(kwargs)
    lg = PluginLogger(**params)
    lg.start()
    return lg


def read_lines(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def only_log_file(tmp_path: Path) -> Path:
    files = sorted((tmp_path / "logs").glob("plugin_*.jsonl"))
    assert len(files) == 1, files
    return files[0]


# ---------------------------------------------------------------------
# RingBuffer
# ---------------------------------------------------------------------

class TestRingBuffer:
    def test_holds_maxlen(self):
        ring = RingBuffer(3)
        for i in range(5):
            ring.append(str(i))
        assert len(ring) == 3
        assert ring.dump() == ["2", "3", "4"]

    def test_default_from_config(self):
        assert RingBuffer(config.RING_BUFFER_SIZE).maxlen == 20

    def test_clear(self):
        ring = RingBuffer(5)
        ring.append("x")
        ring.clear()
        assert ring.dump() == []

    def test_invalid_maxlen(self):
        with pytest.raises(ValueError):
            RingBuffer(0)


# ---------------------------------------------------------------------
# File naming and rotation (§39)
# ---------------------------------------------------------------------

class TestRotation:
    def test_file_name_format(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "ping")
        assert only_log_file(tmp_path).name == "plugin_2026-10-11_12.jsonl"

    @pytest.mark.parametrize("hour, bucket", [
        (0, "00"), (11, "00"),
        (12, "12"), (23, "12"),
    ])
    def test_bucket_boundaries(self, tmp_path, hour, bucket):
        moment = datetime(2026, 10, 11, hour, 30, 0)
        lg = make_logger(tmp_path, clock=lambda: moment)
        lg.event(LEVEL_INFO, "ping")
        assert only_log_file(tmp_path).name == f"plugin_2026-10-11_{bucket}.jsonl"

    def test_two_buckets_two_files(self, tmp_path):
        # Clock returns the same moment for a whole batch, then moves on:
        # session_start + "before" land in the 00 bucket, "after" in the 12 one.
        moments = iter([
            datetime(2026, 10, 11, 11, 59),
            datetime(2026, 10, 11, 12, 0),
        ])
        current = {"v": next(moments)}
        lg = make_logger(tmp_path, clock=lambda: current["v"])
        lg.event(LEVEL_INFO, "before")
        current["v"] = next(moments)
        lg.event(LEVEL_INFO, "after")
        lg.close()
        names = sorted(p.name for p in (tmp_path / "logs").glob("plugin_*.jsonl"))
        assert names == [
            "plugin_2026-10-11_00.jsonl",
            "plugin_2026-10-11_12.jsonl",
        ]
        # First file holds session_start + "before", second only "after".
        first = read_lines(tmp_path / "logs" / "plugin_2026-10-11_00.jsonl")
        second = read_lines(tmp_path / "logs" / "plugin_2026-10-11_12.jsonl")
        assert [r["event"] for r in first] == ["session_start", "before"]
        # The summary belongs to the bucket that was active at shutdown.
        assert [r["event"] for r in second] == ["after", "session_summary"]

    def test_old_file_kept(self, tmp_path):
        # §39: old files are never deleted, they just stop receiving lines.
        lg = make_logger(tmp_path, clock=lambda: datetime(2026, 10, 11, 1))
        lg.event(LEVEL_INFO, "first")
        lg.close()
        assert (tmp_path / "logs" / "plugin_2026-10-11_00.jsonl").exists()

    def test_invalid_rotate_hours(self, tmp_path):
        with pytest.raises(ValueError):
            PluginLogger(log_dir=tmp_path, rotate_hours=5)

    def test_rotate_hours_must_divide_day(self, tmp_path):
        assert PluginLogger(log_dir=tmp_path, rotate_hours=8)._rotate_hours == 8



# ---------------------------------------------------------------------
# Record shape (§38)
# ---------------------------------------------------------------------

class TestRecordShape:
    def test_required_fields(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "hello", {"k": 1})
        record = read_lines(only_log_file(tmp_path))[-1]
        for field in (
            "seq", "ts", "level", "session_uuid", "turn_uuid",
            "call_uuid", "floor", "layer", "event", "data",
        ):
            assert field in record
        assert record["event"] == "hello"
        assert record["data"] == {"k": 1}

    def test_ts_has_milliseconds(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "hello")
        assert read_lines(only_log_file(tmp_path))[-1]["ts"] == "2026-10-11T21:40:00.123"

    def test_seq_monotonic_in_file(self, tmp_path):
        lg = make_logger(tmp_path)
        for i in range(4):
            lg.event(LEVEL_INFO, f"e{i}")
        seqs = [r["seq"] for r in read_lines(only_log_file(tmp_path))]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)

    def test_uuids_from_trace(self, tmp_path):
        trace = Trace(session_uuid="s-1")
        lg = make_logger(tmp_path, trace=trace)
        trace.new_turn()
        lg.event(LEVEL_INFO, "in-turn")
        record = read_lines(only_log_file(tmp_path))[-1]
        assert record["session_uuid"] == "s-1"
        assert record["turn_uuid"] == trace.current_turn.turn_uuid
        assert record["floor"] == 1

    def test_no_turn_before_first_floor(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "before-turn")
        record = read_lines(only_log_file(tmp_path))[-1]
        assert record["turn_uuid"] is None
        assert record["floor"] == 0

    def test_call_uuid_passed_through(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "call", call_uuid="call-42")
        assert read_lines(only_log_file(tmp_path))[-1]["call_uuid"] == "call-42"

    def test_layer_validation(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "react-ev", layer="react")
        assert read_lines(only_log_file(tmp_path))[-1]["layer"] == "react"
        with pytest.raises(ValueError):
            lg.event(LEVEL_INFO, "bad", layer="nope")

    def test_one_line_per_event(self, tmp_path):
        lg = make_logger(tmp_path)
        before = len(read_lines(only_log_file(tmp_path)))  # session_start
        for i in range(3):
            lg.event(LEVEL_INFO, f"e{i}")
        assert len(read_lines(only_log_file(tmp_path))) == before + 3

    def test_layer_helpers(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.react("llm_request", {"prompt": "p"})
        lg.tool("tool_call", {"key": "go_north"})
        lg.interaction("parse_ok", {"index": 0})
        layers = [r["layer"] for r in read_lines(only_log_file(tmp_path))]
        assert {"react", "tool", "interaction"} <= set(layers)


# ---------------------------------------------------------------------
# Levels (§39)
# ---------------------------------------------------------------------

class TestLevels:
    def test_debug_hidden_when_debug_false(self, tmp_path):
        lg = make_logger(tmp_path, debug=False, level=0)
        lg.event(LEVEL_DEBUG, "secret")
        lg.event(LEVEL_INFO, "visible")
        events = [r["event"] for r in read_lines(only_log_file(tmp_path))]
        assert "secret" not in events
        assert "visible" in events

    def test_debug_written_when_debug_true(self, tmp_path):
        lg = make_logger(tmp_path, debug=True, level=0)
        lg.event(LEVEL_DEBUG, "secret")
        assert "secret" in [r["event"] for r in read_lines(only_log_file(tmp_path))]

    def test_level_floor_filters_info(self, tmp_path):
        lg = make_logger(tmp_path, level=LEVEL_WARN)
        lg.event(LEVEL_INFO, "info")
        lg.event(LEVEL_WARN, "warn")
        events = [r["event"] for r in read_lines(only_log_file(tmp_path))]
        assert "info" not in events
        assert "warn" in events

    def test_warn_always_written(self, tmp_path):
        lg = make_logger(tmp_path, level=LEVEL_WARN)
        lg.event(LEVEL_WARN, "w")
        assert "w" in [r["event"] for r in read_lines(only_log_file(tmp_path))]

    def test_error_always_written(self, tmp_path):
        lg = make_logger(tmp_path, level=LEVEL_ERROR)
        lg.event(LEVEL_ERROR, "boom", {"message": "boom"})
        assert "boom" in [r["event"] for r in read_lines(only_log_file(tmp_path))]

    def test_invalid_level(self, tmp_path):
        lg = make_logger(tmp_path)
        with pytest.raises(ValueError):
            lg.event(7, "bad")

    def test_counts(self, tmp_path):
        lg = make_logger(tmp_path, level=LEVEL_INFO)
        lg.event(LEVEL_WARN, "w1")
        lg.event(LEVEL_WARN, "w2")
        lg.event(LEVEL_ERROR, "e1", {"message": "e1"})
        counts = lg.counters
        assert counts["warn_count"] == 2


# ---------------------------------------------------------------------
# DEBUG payload policy (§38)
# ---------------------------------------------------------------------

class TestPreviewPayload:
    def test_debug_false_stores_preview(self):
        prompt = "S" * 200
        data = preview_payload(prompt=prompt, response="R" * 5, chars=80, debug=False)
        assert data["prompt_chars"] == 200
        assert data["prompt_preview"] == "S" * 80
        assert data["prompt_hash"] == hashlib.sha256(prompt.encode()).hexdigest()
        assert data["response_chars"] == 5
        assert "prompt" not in data

    def test_debug_true_stores_full(self):
        data = preview_payload(prompt="abc", response="def", debug=True)
        assert data == {"prompt": "abc", "response": "def"}

    def test_empty_prompt(self):
        data = preview_payload(prompt="", debug=False)
        assert data["prompt_chars"] == 0
        assert data["prompt_preview"] == ""

    def test_preview_chars_from_config(self):
        assert config.LOG_PREVIEW_CHARS == 80

    def test_react_layer_level_info_without_debug(self, tmp_path):
        lg = make_logger(tmp_path, debug=False, level=0)
        lg.react("llm_request", preview_payload(prompt="x" * 10, debug=False))
        record = read_lines(only_log_file(tmp_path))[-1]
        assert record["level"] == LEVEL_INFO
        assert record["layer"] == "react"

    def test_react_layer_level_debug_with_debug(self, tmp_path):
        lg = make_logger(tmp_path, debug=True, level=0)
        lg.react("llm_request", preview_payload(prompt="x", debug=True))
        record = read_lines(only_log_file(tmp_path))[-1]
        assert record["level"] == LEVEL_DEBUG
        assert record["data"]["prompt"] == "x"


# ---------------------------------------------------------------------
# Ring buffer contents (§39)
# ---------------------------------------------------------------------

class TestRingContents:
    def test_ring_holds_last_lines(self, tmp_path):
        lg = make_logger(tmp_path, ring_size=3)
        for i in range(6):
            lg.event(LEVEL_INFO, f"e{i}")
        dumped = lg.ring.dump()
        assert len(dumped) == 3
        assert [json.loads(line)["event"] for line in dumped] == ["e3", "e4", "e5"]

    def test_ring_lines_are_json(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "x", {"a": 1})
        assert json.loads(lg.ring.dump()[-1])["data"] == {"a": 1}

    def test_ring_default_size(self, tmp_path):
        assert make_logger(tmp_path).ring.maxlen == config.RING_BUFFER_SIZE


# ---------------------------------------------------------------------
# Crash reports (§39)
# ---------------------------------------------------------------------

class TestCrash:
    def test_crash_file_created(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.die("bad state")
        assert len(list((tmp_path / "crashes").glob("crash_*.log"))) == 1

    def test_crash_file_name_has_turn_uuid(self, tmp_path):
        trace = Trace(session_uuid="s")
        lg = make_logger(tmp_path, trace=trace)
        turn = trace.new_turn()
        lg.die("m")
        name = next((tmp_path / "crashes").glob("crash_*.log")).name
        assert name.endswith(f"_{turn.turn_uuid}.log")

    def test_crash_header(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.die("bad state")
        text = next((tmp_path / "crashes").glob("crash_*.log")).read_text(encoding="utf-8")
        assert text.startswith("=== BURT PLUGIN CRASH ===")
        assert "time:" in text
        assert "version:  v0.7.0" in text
        assert "session:  test-session" in text
        assert "event:    crash" in text
        assert "message:  bad state" in text
        assert text.rstrip().endswith("=== END ===")

    def test_crash_dumps_ring(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "before-crash")
        lg.die("m")
        text = next((tmp_path / "crashes").glob("crash_*.log")).read_text(encoding="utf-8")
        assert "--- last 20 lines (ring buffer) ---" in text
        assert "before-crash" in text

    def test_explicit_crash_with_exception(self, tmp_path):
        lg = make_logger(tmp_path)
        try:
            raise RuntimeError("kaboom")
        except RuntimeError as exc:
            lg.die("kaboom", exc)
        text = next((tmp_path / "crashes").glob("crash_*.log")).read_text(encoding="utf-8")
        assert "--- traceback ---" in text
        assert "RuntimeError: kaboom" in text

    def test_error_event_counts_and_level(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_ERROR, "x", {"message": "x"})
        record = read_lines(only_log_file(tmp_path))[-1]
        assert record["level"] == LEVEL_ERROR
        assert lg.counters["error_count"] == 1

    def test_die_counts_error(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.die("boom")
        assert lg.counters["error_count"] == 1


# ---------------------------------------------------------------------
# Session summary (§39)
# ---------------------------------------------------------------------

class TestSummary:
    def test_summary_is_last_line(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.trace.new_turn()
        lg.event(LEVEL_INFO, "work")
        lg.close()
        assert read_lines(only_log_file(tmp_path))[-1]["event"] == "session_summary"

    def test_summary_payload(self, tmp_path):
        trace = Trace(session_uuid="sess")
        lg = make_logger(tmp_path, trace=trace)
        trace.new_turn()
        trace.new_turn()
        lg.event(LEVEL_WARN, "w")
        lg.close()
        data = read_lines(only_log_file(tmp_path))[-1]["data"]
        assert data["warn_count"] == 1
        assert data["error_count"] == 0
        assert data["floors_total"] == 2
        assert data["session_uuid"] == "sess"

    def test_close_is_idempotent(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.close()
        lg.close()
        summaries = [r for r in read_lines(only_log_file(tmp_path))
                     if r["event"] == "session_summary"]
        assert len(summaries) == 1

    def test_events_after_close_ignored(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.close()
        lg.event(LEVEL_INFO, "late")
        assert "late" not in [r["event"] for r in read_lines(only_log_file(tmp_path))]


# ---------------------------------------------------------------------
# Async mode (§39)
# ---------------------------------------------------------------------

class TestAsync:
    @pytest.mark.asyncio
    async def test_async_writes(self, tmp_path):
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "async-1")
        await asyncio.sleep(0)
        lg.event(LEVEL_INFO, "async-2")
        await asyncio.sleep(0)
        await lg.stop()
        events = [r["event"] for r in read_lines(only_log_file(tmp_path))]
        assert "async-1" in events and "async-2" in events

    @pytest.mark.asyncio
    async def test_stop_flushes_pending(self, tmp_path):
        lg = make_logger(tmp_path)
        for i in range(5):
            lg.event(LEVEL_INFO, f"q{i}")
        await lg.stop()
        events = [r["event"] for r in read_lines(only_log_file(tmp_path))]
        for i in range(5):
            assert f"q{i}" in events

    @pytest.mark.asyncio
    async def test_seq_order_preserved(self, tmp_path):
        lg = make_logger(tmp_path)
        for i in range(10):
            lg.event(LEVEL_INFO, f"e{i}")
        await lg.stop()
        seqs = [r["seq"] for r in read_lines(only_log_file(tmp_path))]
        assert seqs == sorted(seqs)

    def test_sync_mode_without_loop(self, tmp_path):
        # No running loop: every line goes straight to the file.
        lg = make_logger(tmp_path)
        lg.event(LEVEL_INFO, "sync")
        assert "sync" in [r["event"] for r in read_lines(only_log_file(tmp_path))]

    @pytest.mark.asyncio
    async def test_queue_overflow_falls_back_to_sync(self, tmp_path):
        lg = make_logger(tmp_path, queue_maxsize=1)
        for i in range(5):
            lg.event(LEVEL_INFO, f"o{i}")
        await lg.stop()
        events = [r["event"] for r in read_lines(only_log_file(tmp_path))]
        for i in range(5):
            assert f"o{i}" in events
        assert "log_queue_full" in events
