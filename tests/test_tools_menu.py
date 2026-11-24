"""Full tools menu — spec §26.

Contract:
- free tools: quest_log / inventory / status / diary;
- offered in exploring, dialog and combat menus;
- NOT offered in a micro-location and NOT in the revealed-encounter menu;
- a tool never advances the step, never changes mode, HP, wallet or combat;
- each tool returns plain text with a stable header.
"""
from __future__ import annotations

import pytest

from burt import combat, faith
from burt.loop import (
    Action, TOOL_KEYS, build_menu, execute_action, parse_choice,
)
from burt.npc import DialogueEngine, load_replicas


TOOLS = ("quest_log", "inventory", "status", "diary", "map")
# The map is for travelling: not offered in a fight or a talk.
TOOLS_NO_MAP = tuple(k for k in TOOLS if k != "map")
ROLES = ("merchant", "guard", "peasant", "peasant_woman", "elder",
         "tavernkeeper", "blacksmith", "fisherman", "child", "veteran",
         "cleric", "necromancer", "mage")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(mode: str = "exploring", step: int = 5, **hidden_over) -> dict:
    st = {
        "meta": {"life": 1, "day": 1, "step": step,
                 "memory": "I saw the dark."},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [], "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
            "faith": faith.STATUS_NEUTRAL,
        },
        "hidden": {
            "step": step, "day": 1,
            "current_mode": mode,
            "current_node_id": "start",
            "npcs_here": [], "npcs_by_node": {}, "events_here": [],
            "effects_detail": [],
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
            "combat": None, "combat_npc_role": None,
            "dialog_state": None, "faith": faith.new_state(),
            "diary": None, "day_log": [],
            "diary_written_today": False, "diary_skipped_today": False,
            "injected_day": 0,
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": "n1", "east": None,
                                    "south": None, "west": None}},
                "n1": {"type": "village", "entered": True,
                       "exits": {"south": "start", "north": None,
                                 "east": None, "west": None}},
            },
        },
    }
    st["hidden"].update(hidden_over)
    return st


def menu_map(st: dict, engine=None) -> dict:
    return {a.key: a for a in build_menu(
        st["visible"], st, dialogue_engine=engine,
    )}


# ---------------------------------------------------------------------
# Menu presence
# ---------------------------------------------------------------------

class TestMenuPresence:
    def test_exploring_has_all_tools(self):
        st = make_state()
        actions = menu_map(st)
        for key in TOOLS:
            assert key in actions, key
            assert actions[key].cost_free is True, key

    def test_dialog_has_all_tools(self, engine):
        st = make_state(npcs_here=["merchant"])
        execute_action(Action("talk_to_merchant", "Talk"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        actions = menu_map(st, engine)
        for key in TOOLS_NO_MAP:
            assert key in actions, key
        assert "map" not in actions
        assert "eat_food" not in actions

    def test_combat_has_all_tools(self):
        st = make_state()
        cs = combat.start_combat(["wolf"], "burt")
        cs.free_strike_done = True
        st["hidden"]["combat"] = cs.to_dict()
        st["hidden"]["current_mode"] = "combat"
        actions = menu_map(st)
        for key in TOOLS_NO_MAP:
            assert key in actions, key
            assert actions[key].cost_free is True, key
        assert "map" not in actions
        assert "osmotret" not in actions

    def test_micro_location_has_only_exits(self):
        st = make_state()
        st["hidden"]["micro_location"] = {
            "active": True, "source_node": "start",
            "target_node": "n1", "direction": "north",
            "event_type": "stone", "damage": 1,
        }
        assert list(menu_map(st)) == ["go_back", "go_forward"]

    def test_revealed_encounter_has_no_tools(self):
        st = make_state()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["hidden"]["pending_encounter"] = {
            "node_id": "start", "enemy_keys": ["wolf"],
        }
        st["hidden"]["encounter_revealed"] = True
        keys = list(menu_map(st))
        assert all(k.startswith("attack_") or k.startswith("go_away_to_")
                   for k in keys)
        for key in TOOLS:
            assert key not in keys

    def test_labels(self):
        actions = menu_map(make_state())
        assert actions["quest_log"].label == "Quest log"
        assert actions["inventory"].label == "Inventory"
        assert actions["status"].label == "Status"
        assert actions["diary"].label == "Diary"
        assert actions["map"].label == "Map"

    def test_tool_keys_constant(self):
        assert TOOL_KEYS == frozenset(TOOLS)

    def test_remember_is_not_a_tool(self):
        # §28: memory of past lives is a one-time inject, not a menu entry.
        actions = menu_map(make_state())
        assert "remember" not in actions
        assert "remember" not in TOOL_KEYS



# ---------------------------------------------------------------------
# Tool output
# ---------------------------------------------------------------------

class TestToolOutput:
    def test_inventory_lists_items(self):
        st = make_state()
        st["visible"]["inventory"] = [
            {"name": "bread", "count": 2},
            {"name": "water", "count": 1},
        ]
        result = execute_action(Action("inventory", "Inventory"), st)
        text = "\n".join(result.events)
        assert "[INVENTORY]" in text
        assert "Bread — 2pcs" in text
        assert "Water — 1pcs" in text

    def test_inventory_empty(self):
        st = make_state()
        text = "\n".join(execute_action(
            Action("inventory", "Inventory"), st,
        ).events)
        assert "[INVENTORY]" in text
        assert "empty" in text

    def test_status(self):
        st = make_state()
        st["visible"].update({
            "hp": 7, "mp": 2, "eat": False, "sleep_counter": 5,
            "effects": ["blessed"],
        })
        text = "\n".join(execute_action(
            Action("status", "Status"), st,
        ).events)
        assert "[STATUS]" in text
        assert "HP: 7/10 | MP: 2/3" in text
        assert "Fed: no (hungry)" in text
        assert "Sleep: 5/20" in text
        assert "Effects: blessed" in text
        effects_line = next(
            line for line in text.splitlines() if line.startswith("Effects:")
        )
        assert "3" not in effects_line

    def test_status_no_effects(self):
        st = make_state()
        text = "\n".join(execute_action(
            Action("status", "Status"), st,
        ).events)
        assert "Effects: none" in text

    def test_diary(self):
        st = make_state()
        st["hidden"]["diary"] = "Day one was cold."
        text = "\n".join(execute_action(
            Action("diary", "Diary"), st,
        ).events)
        assert "[DIARY]" in text
        assert "Day one was cold." in text

    def test_diary_empty(self):
        st = make_state()
        text = "\n".join(execute_action(
            Action("diary", "Diary"), st,
        ).events)
        assert "You have no diary entry." in text

    def test_quest_log_still_works(self):
        st = make_state()
        text = "\n".join(execute_action(
            Action("quest_log", "Quest log"), st,
        ).events)
        assert "[QUESTS]" in text
        assert "No open quests" in text

    def test_map_tool(self):
        st = make_state()
        text = "\n".join(execute_action(
            Action("map", "Map"), st,
        ).events)
        assert "[MAP]" in text
        assert "<" in text and ">" in text   # the current node marker



# ---------------------------------------------------------------------
# Tools are free and mode-safe
# ---------------------------------------------------------------------

class TestToolsAreFree:
    @pytest.mark.parametrize("key", TOOLS)
    def test_exploring_does_not_change_state(self, key):
        st = make_state()
        before = (
            st["hidden"]["step"], st["hidden"]["current_mode"],
            st["visible"]["hp"], dict(st["visible"]["wallet"]),
            [dict(i) for i in st["visible"]["inventory"]],
        )
        execute_action(Action(key, key), st)
        after = (
            st["hidden"]["step"], st["hidden"]["current_mode"],
            st["visible"]["hp"], dict(st["visible"]["wallet"]),
            [dict(i) for i in st["visible"]["inventory"]],
        )
        assert after == before

    def test_tool_in_dialog_keeps_mode(self, engine):
        st = make_state(npcs_here=["merchant"])
        execute_action(Action("talk_to_merchant", "Talk"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        step = st["hidden"]["step"]
        result = execute_action(Action("inventory", "Inventory"), st,
                                dialogue_engine=engine)
        assert any("[INVENTORY]" in ev for ev in result.events)
        assert st["hidden"]["current_mode"] == "dialog"
        assert st["hidden"]["step"] == step
        assert st["hidden"]["dialog_state"]["role_key"] == "merchant"

    def test_tool_in_combat_keeps_mode(self):
        st = make_state()
        cs = combat.start_combat(["wolf"], "burt")
        cs.free_strike_done = True
        st["hidden"]["combat"] = cs.to_dict()
        st["hidden"]["current_mode"] = "combat"
        step = st["hidden"]["step"]
        result = execute_action(Action("status", "Status"), st)
        assert any("[STATUS]" in ev for ev in result.events)
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["step"] == step
        assert st["hidden"]["combat"] is not None


# ---------------------------------------------------------------------
# CHOICE parsing
# ---------------------------------------------------------------------

class TestToolChoiceParsing:
    @pytest.mark.parametrize("key", TOOLS)
    def test_by_key(self, key):
        st = make_state()
        menu = build_menu(st["visible"], st)
        action = parse_choice(f"CHOICE: {key}", menu)
        assert action.key == key

    def test_by_prose_inventory(self):
        st = make_state()
        menu = build_menu(st["visible"], st)
        assert parse_choice("I check my inventory.", menu).key == "inventory"

    def test_by_prose_status(self):
        st = make_state()
        menu = build_menu(st["visible"], st)
        assert parse_choice("How do I feel? Check status.", menu).key == "status"

    def test_by_prose_diary(self):
        st = make_state()
        menu = build_menu(st["visible"], st)
        assert parse_choice("I open my diary.", menu).key == "diary"

