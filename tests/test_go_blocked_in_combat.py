"""Tests for blocking movement actions during combat (HANDOFF-12 #5).

A hallucinated go_north during combat must not move Burt or advance
the step counter. Only movement actions (go_* prefix) are blocked here;
other non-combat actions are out of scope for this fix.
"""

import pytest

from burt import world
from burt.loop import Action, execute_action
from burt.combat import start_combat


def _state(mode="combat"):
    cs = start_combat(["wolf"], "burt")
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [],
            "wallet": {"gold": 0, "silver": 5, "copper": 0},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": mode,
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 5, "day": 1,
            "combat": cs.to_dict() if mode == "combat" else None,
        },
    }


# ─── Blocked in combat ─────────────────────────────────────


class TestGoBlockedInCombat:
    @pytest.mark.parametrize("key", [
        "go_north", "go_east", "go_south", "go_west",
        "go_back", "go_forward",
    ])
    def test_go_action_returns_error(self, key):
        st = _state("combat")
        result = execute_action(Action(key, key), st, rng=lambda: 4)
        assert any("error" in e.lower() for e in result.events)

    def test_go_north_does_not_move(self):
        st = _state("combat")
        node_before = st["hidden"]["current_node_id"]
        execute_action(Action("go_north", "Go"), st, rng=lambda: 4)
        assert st["hidden"]["current_node_id"] == node_before

    def test_go_north_does_not_advance_step(self):
        st = _state("combat")
        step_before = st["hidden"]["step"]
        execute_action(Action("go_north", "Go"), st, rng=lambda: 4)
        assert st["hidden"]["step"] == step_before

    def test_go_north_does_not_touch_last_action(self):
        st = _state("combat")
        st["hidden"]["last_action"] = "attack_wolf_1"
        st["hidden"]["same_action_count"] = 1
        execute_action(Action("go_north", "Go"), st, rng=lambda: 4)
        assert st["hidden"]["last_action"] == "attack_wolf_1"
        assert st["hidden"]["same_action_count"] == 1


# ─── Regression: still works outside combat ────────────────


class TestGoStillWorksInExploring:
    def test_go_north_moves_in_exploring(self):
        st = _state("exploring")
        node_before = st["hidden"]["current_node_id"]
        execute_action(Action("go_north", "Go"), st, rng=lambda: 4)
        assert st["hidden"]["current_node_id"] != node_before

    def test_go_north_advances_step_in_exploring(self):
        st = _state("exploring")
        step_before = st["hidden"]["step"]
        execute_action(Action("go_north", "Go"), st, rng=lambda: 4)
        assert st["hidden"]["step"] == step_before + 1


# ─── Regression: combat actions still work ─────────────────


class TestCombatActionsStillWork:
    def test_attack_in_combat_does_not_error(self):
        st = _state("combat")
        cs_enemy_id = st["hidden"]["combat"]["enemies"][0]["id"]
        result = execute_action(
            Action(f"attack_{cs_enemy_id}", "Attack",
                   target_id=cs_enemy_id),
            st, rng=lambda: 4,
        )
        assert not any("cannot go_" in e.lower() for e in result.events)
