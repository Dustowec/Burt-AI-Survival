"""Dialog anti-loop guard: the 3rd identical action ends the talk."""
from __future__ import annotations

import pytest

from burt.loop import Action, DIALOG_SPAM_TEXT, execute_action
from burt.npc import DialogueEngine, load_replicas


ROLES = ("merchant", "elder", "veteran", "guard")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(step=5):
    return {
        "meta": {"life": 1, "day": 1, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [], "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
        },
        "hidden": {
            "step": step, "day": 1,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [], "npcs_by_node": {},
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [], "quests_issued_today": {},
            "role_quest_block": {}, "rep_applied": {},
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0}, "price_modifier": 1.0,
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "has_staff": False, "teacher_found": False,
            "trained_by": [], "skills_raw": [],
            "pending_encounter": None, "encounter_revealed": False,
            "last_action": None, "same_action_count": 0,
            "combat": None, "dialog_state": None,
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": None, "east": None,
                                    "south": None, "west": None}},
            },
        },
    }


def open_dialog(st, role, engine):
    st["hidden"]["npcs_here"] = [role]
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=_rng_seq(4, 4), dialogue_engine=engine,
    )


class TestDialogRepeatGuard:
    def test_third_identical_action_breaks_dialog(self, engine):
        st = make_state()
        open_dialog(st, "merchant", engine)
        act = Action("dialog_polite", "Polite")

        execute_action(act, st, rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(act, st, rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert st["hidden"]["current_mode"] == "dialog"
        assert st["visible"]["hp"] == 10

        result = execute_action(
            act, st, rng=_rng_seq(4, 4), dialogue_engine=engine,
        )
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["dialog_state"] is None
        assert st["visible"]["hp"] == 9
        assert st["hidden"]["hp_raw"] == 9
        assert DIALOG_SPAM_TEXT in result.events[0]
        assert result.inject == DIALOG_SPAM_TEXT

    def test_different_action_resets_streak(self, engine):
        st = make_state()
        open_dialog(st, "merchant", engine)
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_truth", "Truth"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert st["hidden"]["current_mode"] == "dialog"
        assert st["hidden"]["dialog_state"]["dialog_same_count"] == 1

    def test_exit_attempts_do_not_bypass_anger_lock(self, engine):
        st = make_state()
        open_dialog(st, "elder", engine)
        execute_action(Action("dialog_truth", "Truth"), st,
                       rng=_rng_seq(1, 1), dialogue_engine=engine)
        assert st["hidden"]["dialog_state"]["is_angry"] is True
        hp_after_insult = st["visible"]["hp"]

        for _ in range(3):
            result = execute_action(
                Action("dialog_exit", "Leave"), st, dialogue_engine=engine,
            )
            assert result.events[0].startswith("Error:")
            assert st["hidden"]["current_mode"] == "dialog"
            assert st["visible"]["hp"] == hp_after_insult
