"""Tests for burt/game_session.py — spec §2, §39.

Gameplay log: game_session.jsonl, append-only, one line per turn,
written synchronously. Lives next to state.json.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import config
from burt.game_session import GameSessionLog
from burt.trace import Trace

FIXED = datetime(2026, 10, 11, 21, 40, 0, 500000)


def make_log(tmp_path: Path, **kwargs) -> GameSessionLog:
    params = dict(trace=Trace(session_uuid="sess"), clock=lambda: FIXED)
    params.update(kwargs)
    return GameSessionLog(tmp_path / config.GAME_SESSION_PATH, **params)


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def turn(day=1, step=3, mode="exploring", location="Crossroads",
         prompt="SENSOR", response="I walk. CHOICE: 0",
         action_key="go_north", action_label="Go north",
         events=None, hp=10, hp_max=10, game_over=False) -> dict:
    return dict(
        day=day, step=step, mode=mode, location=location,
        prompt=prompt, response=response,
        action_key=action_key, action_label=action_label,
        events=events if events is not None else ["You go north."],
        hp=hp, hp_max=hp_max, game_over=game_over,
    )


# ---------------------------------------------------------------------
# Creation and path (§2)
# ---------------------------------------------------------------------

class TestCreation:
    def test_path_property(self, tmp_path):
        log = make_log(tmp_path)
        assert log.path == tmp_path / "game_session.jsonl"

    def test_default_name_from_config(self):
        assert config.GAME_SESSION_PATH == "game_session.jsonl"

    def test_parent_dirs_created(self, tmp_path):
        log = GameSessionLog(tmp_path / "nested" / "game_session.jsonl")
        log.append_turn(**turn())
        assert (tmp_path / "nested" / "game_session.jsonl").is_file()

    def test_no_network_or_llm_import(self):
        import burt.game_session as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "aiohttp" not in source
        assert "llm_client" not in source



# ---------------------------------------------------------------------
# append_turn (§39)
# ---------------------------------------------------------------------

class TestAppendTurn:
    def test_one_line_per_turn(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn())
        log.append_turn(**turn(step=4))
        assert len(read_lines(log.path)) == 2

    def test_append_only(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn(day=1, step=1))
        first_text = log.path.read_text(encoding="utf-8")
        log.append_turn(**turn(day=1, step=2))
        assert log.path.read_text(encoding="utf-8").startswith(first_text)

    def test_required_fields(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn())
        record = read_lines(log.path)[0]
        for field in (
            "ts", "session_uuid", "turn_uuid", "floor",
            "day", "step", "mode", "location",
            "prompt", "response", "action_key", "action_label",
            "events", "hp", "hp_max", "game_over",
        ):
            assert field in record, field

    def test_full_text_not_truncated(self, tmp_path):
        log = make_log(tmp_path)
        long_prompt = "P" * 5000
        long_response = "R" * 5000
        log.append_turn(**turn(prompt=long_prompt, response=long_response))
        record = read_lines(log.path)[0]
        assert record["prompt"] == long_prompt
        assert record["response"] == long_response

    def test_uuid_from_trace(self, tmp_path):
        trace = Trace(session_uuid="sess")
        log = make_log(tmp_path, trace=trace)
        t = trace.new_turn()
        log.append_turn(**turn())
        record = read_lines(log.path)[0]
        assert record["session_uuid"] == "sess"
        assert record["turn_uuid"] == t.turn_uuid
        assert record["floor"] == t.floor

    def test_ts_format(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn())
        assert read_lines(log.path)[0]["ts"] == "2026-10-11T21:40:00.500"

    def test_utf8_not_escaped(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn(response="\u0442\u044b \u0433\u043e\u043b\u043e\u0434\u0435\u043d"))
        raw = log.path.read_text(encoding="utf-8")
        assert "\u0433\u043e\u043b\u043e\u0434\u0435\u043d" in raw
        assert "\\u" not in raw

    def test_events_list_preserved(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn(events=["[COMBAT]", "You hit wolf."]))
        assert read_lines(log.path)[0]["events"] == ["[COMBAT]", "You hit wolf."]

    def test_game_over_flag(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn(game_over=True, hp=0))
        record = read_lines(log.path)[0]
        assert record["game_over"] is True


# ---------------------------------------------------------------------
# append_special (§29, §39)
# ---------------------------------------------------------------------

class TestAppendSpecial:
    def test_special_record(self, tmp_path):
        log = make_log(tmp_path)
        log.append_special(day=2, event="death", description="Burt died from hunger")
        record = read_lines(log.path)[0]
        assert record["event"] == "death"
        assert record["description"] == "Burt died from hunger"
        assert record["day"] == 2

    def test_special_extra_data(self, tmp_path):
        log = make_log(tmp_path)
        log.append_special(day=1, event="resurrection", description="roll=6",
                           data={"roll": 6})
        assert read_lines(log.path)[0]["data"] == {"roll": 6}


# ---------------------------------------------------------------------
# Sync behaviour (§2, §39)
# ---------------------------------------------------------------------

class TestSync:
    def test_visible_immediately(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn())
        # Already on disk, no explicit flush needed.
        assert len(read_lines(log.path)) == 1

    def test_survives_many_turns(self, tmp_path):
        log = make_log(tmp_path)
        for i in range(50):
            log.append_turn(**turn(step=i % 20))
        assert len(read_lines(log.path)) == 50

    def test_close_is_idempotent(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn())
        log.close()
        log.close()
        assert len(read_lines(log.path)) == 1

    def test_every_line_is_valid_json(self, tmp_path):
        log = make_log(tmp_path)
        log.append_turn(**turn())
        for line in log.path.read_text(encoding="utf-8").splitlines():
            json.loads(line)
