"""Sleep availability — spec §5 (known_issues #13 / P2-13).

`sleep.is_sleep_available` is now the gate of the "sleep" menu entry:
a bedroll in the inventory or a paid tavern room, and never in combat.
"""
from __future__ import annotations

import pytest

from burt import loop, sleep as sleep_mod
from burt.loop import Action, build_menu, execute_action


def make_state(step=19, mode="exploring", hp=10, inventory=None, **hidden_over):
    st = {
        "meta": {"life": 1, "day": 1, "step": step},
        "visible": {
            "hp": hp, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [],
            "inventory": list(inventory or []),
            "wallet": {"coin": 50},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
        },
        "hidden": {
            "step": step, "day": 1,
            "current_mode": mode,
            "current_node_id": "start",
            "npcs_here": [],
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0},
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "pending_encounter": None,
            "encounter_revealed": False,
            "last_action": None,
            "same_action_count": 0,
            "combat": None,
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": None, "east": None,
                                    "south": None, "west": None}},
            },
        },
    }
    st["hidden"].update(hidden_over)
    return st


def keys(st):
    return [a.key for a in build_menu(st["visible"], st)]


# ---------------------------------------------------------------------
# The core gate
# ---------------------------------------------------------------------

class TestSleepAvailableCore:
    def test_bedroll_allows_sleep_from_step_19(self):
        assert sleep_mod.is_sleep_available(19, False, True, False) is True

    def test_bedroll_does_not_allow_early_sleep(self):
        assert sleep_mod.is_sleep_available(5, False, True, False) is False

    def test_room_allows_sleep(self):
        assert sleep_mod.is_sleep_available(19, False, False, True) is True

    def test_nothing_means_no_sleep(self):
        assert sleep_mod.is_sleep_available(19, False, False, False) is False

    def test_combat_blocks_sleep(self):
        assert sleep_mod.is_sleep_available(20, True, True, True) is False


# ---------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------

class TestSleepMenu:
    def test_no_sleep_without_bedroll_or_room(self):
        st = make_state(step=19)
        assert "sleep" not in keys(st)
        assert "write_diary_and_go_sleep" not in keys(st)

    def test_sleep_with_bedroll(self):
        st = make_state(step=19, inventory=[{"name": "bedroll", "count": 1}])
        assert "sleep" in keys(st)
        assert "write_diary_and_go_sleep" in keys(st)

    def test_sleep_with_paid_room(self):
        st = make_state(step=19, has_room_tonight=True)
        assert "sleep" in keys(st)

    def test_no_sleep_before_step_19_even_with_bedroll(self):
        st = make_state(step=5, inventory=[{"name": "bedroll", "count": 1}])
        assert "sleep" not in keys(st)
        assert "write_diary_and_go_sleep" not in keys(st)

    def test_critical_hp_keeps_the_safety_valve(self):
        # documented deviation: a dying Burt may sleep without a bed
        st = make_state(step=5, hp=2)
        assert "sleep" in keys(st)
        assert "write_diary_and_go_sleep" not in keys(st)

    def test_combat_menu_has_no_sleep(self):
        st = make_state(step=20, mode="combat",
                        inventory=[{"name": "bedroll", "count": 1}])
        st["hidden"]["combat"] = None
        assert "sleep" not in keys(st)


# ---------------------------------------------------------------------
# The room is good for one night (§5 + §35)
# ---------------------------------------------------------------------

class TestRoomExpiry:
    def test_room_is_consumed_by_sleep(self):
        st = make_state(step=19, has_room_tonight=True)
        execute_action(Action("sleep", "Sleep"), st)
        assert st["hidden"]["has_room_tonight"] is False

    def test_bedroll_survives_sleep(self):
        st = make_state(step=19, inventory=[{"name": "bedroll", "count": 1}])
        execute_action(Action("sleep", "Sleep"), st)
        assert {"name": "bedroll", "count": 1} in st["visible"]["inventory"]

    def test_no_bedroll_no_room_after_room_night(self):
        st = make_state(step=19, has_room_tonight=True)
        execute_action(Action("sleep", "Sleep"), st)
        st["hidden"]["step"] = 19
        assert "sleep" not in keys(st)

    def test_forced_sleep_does_not_need_a_bed(self):
        # §5: at step 20 the day ends regardless (main.run_turn).
        assert sleep_mod.is_forced_sleep(20, chose_sleep=False) is True
        assert sleep_mod.is_forced_sleep(19, chose_sleep=False) is False