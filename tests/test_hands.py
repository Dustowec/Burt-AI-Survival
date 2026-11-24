"""Hand slots ([HANDS]) vs backpack ([INVENTORY])."""
from __future__ import annotations

from burt import hands, sensory
from burt.loop import Action, _build_burt_stats, execute_action


def make_state(inventory=None, hands_map=None, hp=10, eat=False):
    return {
        "meta": {"life": 1, "day": 1, "step": 4},
        "visible": {
            "hp": hp, "hp_max": 10, "mp": 3, "mp_max": 3,
            "level": 1, "xp": 0,
            "eat": eat, "sleep_counter": 4, "date": "1 day",
            "effects": [],
            "location": {"name": "Village", "exits": ["north"]},
            "inventory": list(inventory or []),
            "hands": dict(hands_map) if hands_map is not None else None,
            "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "step": 4, "day": 1,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [], "npcs_by_node": {},
            "reputation": {},
            "quests_raw": [],
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0},
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "has_staff": False, "teacher_found": False,
            "trained_by": [], "skills_raw": [],
            "pending_encounter": None, "encounter_revealed": False,
            "last_action": None, "same_action_count": 0,
            "combat": None, "dialog_state": None,
            "effects_detail": [], "faith": {},
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": None, "east": None,
                                    "south": None, "west": None}},
            },
        },
    }


class TestHandsCore:
    def test_migration_equips_best_weapon_and_food(self):
        v = {
            "inventory": [
                {"name": "club", "count": 1},
                {"name": "ordinary_sword", "count": 1},
                {"name": "bread", "count": 2},
            ],
        }
        h = hands.ensure_hands(v)
        assert h["weapon"] == "ordinary_sword"
        assert h["item"] == "bread"

    def test_sync_clears_missing_stack(self):
        v = {
            "inventory": [{"name": "bread", "count": 0}],
            "hands": {"weapon": None, "item": "bread"},
        }
        hands.sync(v)
        assert v["hands"]["item"] is None

    def test_equip_and_unequip(self):
        st = make_state(
            inventory=[{"name": "club", "count": 1},
                       {"name": "bread", "count": 1}],
            hands_map={"weapon": None, "item": None},
        )
        v = st["visible"]
        assert hands.equip(v, "club") is True
        assert v["hands"]["weapon"] == "club"
        assert hands.unequip(v, "weapon") is True
        assert v["hands"]["weapon"] is None

    def test_sensory_hands_has_at_most_two_items(self):
        st = make_state(
            inventory=[
                {"name": "sword", "count": 1},
                {"name": "bread", "count": 2},
                {"name": "mushrooms", "count": 5},
                {"name": "club", "count": 1},
            ],
            hands_map={"weapon": "sword", "item": "bread"},
        )
        out = sensory.format_sensory_report(st["visible"])
        chunk = out[out.index("[HANDS]"):].split("[WALLET]")[0]
        assert "[weapon] Sword — 1pcs" in chunk
        assert "[item] Bread — 2pcs" in chunk
        assert "Mushrooms" not in chunk
        assert "Club" not in chunk

    def test_inventory_tool_shows_backpack(self):
        st = make_state(
            inventory=[
                {"name": "sword", "count": 1},
                {"name": "mushrooms", "count": 5},
            ],
            hands_map={"weapon": "sword", "item": None},
        )
        out = sensory.format_inventory(st["visible"])
        assert "[INVENTORY]" in out
        assert "[BACKPACK]" in out
        assert "Mushrooms — 5pcs" in out


class TestHandsCombat:
    def test_backpack_weapon_is_not_used(self):
        st = make_state(
            inventory=[{"name": "ordinary_sword", "count": 1}],
            hands_map={"weapon": None, "item": None},
        )
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.weapon == "fists"

    def test_equipped_weapon_is_used(self):
        st = make_state(
            inventory=[{"name": "ordinary_sword", "count": 1}],
            hands_map={"weapon": "ordinary_sword", "item": None},
        )
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.weapon == "ordinary_sword"
        assert (burt.damage_min, burt.damage_max) == (2, 4)


class TestUseFromHands:
    def test_eat_takes_food_from_backpack(self):
        st = make_state(
            inventory=[{"name": "water", "count": 1},
                       {"name": "bread", "count": 2}],
            hands_map={"weapon": None, "item": "water"},
            hp=9, eat=False,
        )
        result = execute_action(Action("eat_food", "Eat food"), st)
        v = st["visible"]
        assert not result.events[0].startswith("Error:")
        assert v["hands"]["item"] == "bread"
        assert v["hp"] == 10
        assert v["eat"] is True
        bread = next(i for i in v["inventory"] if i["name"] == "bread")
        assert bread["count"] == 1

    def test_drink_takes_water_from_backpack(self):
        st = make_state(
            inventory=[{"name": "bread", "count": 1},
                       {"name": "water", "count": 2}],
            hands_map={"weapon": None, "item": "bread"},
        )
        result = execute_action(Action("drink_water", "Drink water"), st)
        v = st["visible"]
        assert not result.events[0].startswith("Error:")
        assert v["hands"]["item"] == "water"
        water = next(i for i in v["inventory"] if i["name"] == "water")
        assert water["count"] == 1

    def test_last_item_clears_hand_slot(self):
        st = make_state(
            inventory=[{"name": "bread", "count": 1}],
            hands_map={"weapon": None, "item": "bread"},
        )
        execute_action(Action("eat_food", "Eat food"), st)
        assert st["visible"]["hands"]["item"] is None
        assert st["visible"]["inventory"] == []

    def test_equip_action_is_free(self):
        st = make_state(
            inventory=[{"name": "club", "count": 1}],
            hands_map={"weapon": None, "item": None},
        )
        step_before = st["hidden"]["step"]
        result = execute_action(Action("equip_club", "Equip Club"), st)
        assert not result.events[0].startswith("Error:")
        assert st["hidden"]["step"] == step_before
        assert st["visible"]["hands"]["weapon"] == "club"

