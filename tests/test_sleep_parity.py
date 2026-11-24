"""Voluntary and forced sleep apply the same state changes (new_bug §7)."""
from __future__ import annotations

import copy

import main
from burt.loop import Action, execute_action


FIELDS_VISIBLE = ("hp", "hp_max", "mp", "mp_max", "eat", "sleep_counter", "date")
FIELDS_HIDDEN = (
    "day", "step", "has_room_tonight", "resurrection_used_today",
    "pending_encounter", "encounter_revealed", "day_log",
    "diary", "diary_skipped_today", "diary_written_today",
)


def _state() -> dict:
    st = main.make_new_state(life=1)
    st["visible"]["hp"] = 3
    st["visible"]["mp"] = 1
    st["visible"]["effects"] = ["blessed", "poisoned"]
    st["visible"]["eat"] = True
    st["visible"]["sleep_counter"] = 7
    st["visible"]["inventory"].append({"name": "bedroll", "count": 1})
    st["hidden"]["hp_raw"] = 3
    st["hidden"]["mp_raw"] = 1
    st["hidden"]["day"] = 4
    st["hidden"]["step"] = 19
    st["hidden"]["has_room_tonight"] = True
    st["hidden"]["resurrection_used_today"] = True
    st["hidden"]["pending_encounter"] = {
        "node_id": "start", "enemy_keys": ["wolf"],
    }
    st["hidden"]["encounter_revealed"] = True
    st["hidden"]["day_log"] = [{"step": 1}]
    st["hidden"]["diary"] = "old entry"
    st["hidden"]["diary_written_today"] = False
    st["hidden"]["diary_skipped_today"] = False
    return st


def _snapshot(st: dict) -> dict:
    return {
        "visible": {k: st["visible"][k] for k in FIELDS_VISIBLE},
        "hidden": {k: st["hidden"][k] for k in FIELDS_HIDDEN},
        "hp_raw": st["hidden"]["hp_raw"],
        "mp_raw": st["hidden"]["mp_raw"],
    }


class TestSleepParity:
    def test_voluntary_and_forced_sleep_are_identical(self):
        voluntary = _state()
        forced = copy.deepcopy(voluntary)

        execute_action(
            Action("write_diary_and_go_sleep", "Diary+sleep"),
            voluntary, rng=lambda: 4,
        )
        main._do_sleep(forced)

        assert _snapshot(voluntary) == _snapshot(forced)

    def test_common_effects(self):
        st = _state()
        execute_action(
            Action("write_diary_and_go_sleep", "Diary+sleep"), st, rng=lambda: 4,
        )

        assert st["visible"]["hp"] == st["visible"]["hp_max"]
        assert st["visible"]["mp"] == st["visible"]["mp_max"]
        assert st["visible"]["effects"] == []
        assert st["visible"]["eat"] is False
        assert st["visible"]["sleep_counter"] == 0
        assert st["hidden"]["has_room_tonight"] is False
        assert st["hidden"]["day"] == 5
        assert st["hidden"]["step"] == 0
        assert st["visible"]["date"] == "5 day"
        assert st["hidden"]["day_log"] == []
        assert st["hidden"]["diary"] is None
        assert st["hidden"]["diary_skipped_today"] is True
        assert st["hidden"]["diary_written_today"] is False

    def test_encounter_does_not_survive_sleep(self):
        st = _state()
        execute_action(
            Action("write_diary_and_go_sleep", "Diary+sleep"), st, rng=lambda: 4,
        )
        assert st["hidden"]["pending_encounter"] is None
        assert st["hidden"]["encounter_revealed"] is False

    def test_resurrection_mercy_renewed(self):
        st = _state()
        assert st["hidden"]["resurrection_used_today"] is True
        execute_action(
            Action("write_diary_and_go_sleep", "Diary+sleep"), st, rng=lambda: 4,
        )
        assert st["hidden"]["resurrection_used_today"] is False
