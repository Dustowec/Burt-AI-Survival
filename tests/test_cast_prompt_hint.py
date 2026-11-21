"""Spec 9/23: the cast hint in the system prompt follows the real menu.

Cast is a gated choice (staff + spell + teacher). The static system prompt
never names it; the hint appears only when the menu of the current turn
really offers `cast`, so the text and the option always appear together.
"""
from __future__ import annotations

import main
from burt import loop, world
from burt.combat import start_combat
from burt.loop import Action

HINT = "Your magic is ready: cast is in the menu."


def _state() -> dict:
    return {
        "meta": {"life": 1},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "location": {"name": "Forest", "exits": ["north"]},
            "inventory": [],
        },
        "hidden": {"current_mode": "combat"},
    }


def _combat_state(spells_ready: bool) -> dict:
    cs = start_combat(["wolf"], "burt")
    return {
        "meta": {"life": 1},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": False, "sleep_counter": 0, "date": "1 day",
            "effects": [],
            "location": {"name": "Forest", "exits": ["north"]},
            "inventory": [],
            "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": "combat",
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": 3,
            "spells": {
                "element": "fire" if spells_ready else None,
                "alignment": None,
            },
            "has_staff": spells_ready,
            "teacher_found": spells_ready,
            "step": 0, "day": 1,
            "combat": cs.to_dict(),
        },
    }


class TestCastHintFollowsMenu:
    def test_no_menu_means_no_hint(self):
        assert HINT not in main._build_system_prompt(_state())

    def test_menu_without_cast_has_no_hint(self):
        menu = [
            Action(key="attack_wolf_1", label="Attack wolf"),
            Action(key="block", label="Block"),
        ]
        assert HINT not in main._build_system_prompt(_state(), menu)

    def test_menu_with_cast_adds_hint(self):
        menu = [
            Action(key="attack_wolf_1", label="Attack wolf"),
            Action(key="cast", label="Cast"),
        ]
        assert HINT in main._build_system_prompt(_state(), menu)

    def test_base_prompt_is_kept(self):
        menu = [Action(key="cast", label="Cast")]
        prompt = main._build_system_prompt(_state(), menu)
        assert prompt.startswith("You are Burt.")


class TestMenuAndPromptAgree:
    def test_cast_in_menu_implies_hint(self):
        st = _combat_state(spells_ready=True)
        menu = loop.build_menu(st["visible"], st)
        assert any(a.key == "cast" for a in menu)
        assert HINT in main._build_system_prompt(st, menu)

    def test_no_cast_in_menu_implies_no_hint(self):
        st = _combat_state(spells_ready=False)
        menu = loop.build_menu(st["visible"], st)
        assert not any(a.key == "cast" for a in menu)
        assert HINT not in main._build_system_prompt(st, menu)
