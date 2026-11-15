"""Tests for search fix — HANDOFF-9.2 + TZ-3.

Covered:
- search increments step exactly once per call (with deterministic rng).
- search uses rng() instead of dice.roll_d6() directly.
- search returns stable search_result field.
- search adds loot to inventory.
- search counter works correctly.
- DoT applied on fail_penalty.

All docstrings/comments in English. No Cyrillic literals.
"""

import pytest

from burt.loop import Action, execute_action, build_menu as loop_build_menu


# ─── Helpers ───────────────────────────────────────────────

def make_state_no_location_types():
    """State without hidden['location_types'] — simulates current state.py."""
    from burt import world
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": "exploring",
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "combat": None,
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 0, "day": 1,
            "dot_effects": [],
            "same_action_count": 0,
        },
    }


def make_state_with_location_types():
    """State with hidden['location_types'] — should be ignored by search."""
    from burt import world
    st = make_state_no_location_types()
    st["hidden"]["location_types"] = {"start": "river"}
    return st


# ─── TestSearchFix ─────────────────────────────────────────

class TestSearchFix:
    """Verify HANDOFF-9.2 search fixes."""

    def test_search_increments_step_once(self):
        """One search call with rng → step increases by exactly 1."""
        st = make_state_no_location_types()
        st["hidden"]["step"] = 5
        execute_action(Action("search", "Search"), st, rng=lambda: 4)
        assert st["hidden"]["step"] == 6

    def test_search_uses_rng_not_random(self):
        """Deterministic rng produces deterministic search_result."""
        st = make_state_no_location_types()
        r1 = execute_action(Action("search", "Search"), st, rng=lambda: 4)
        r2 = execute_action(Action("search", "Search"), st, rng=lambda: 4)
        assert r1.search_result == r2.search_result

    def test_search_does_not_reference_location_types(self):
        """Search returns stable result without hidden['location_types']."""
        st = make_state_no_location_types()
        assert "location_types" not in st["hidden"]
        result = execute_action(
            Action("search", "Search"), st, rng=lambda: 4,
        )
        assert result.search_result == "fail"  # crossroads roll=4 -> fail
        assert len(result.events) >= 2  # search_result + sensory report

    def test_search_uses_forest_table_regardless_of_location_type(self):
        """Even with location_types present, search uses correct table."""
        st = make_state_with_location_types()
        result = execute_action(
            Action("search", "Search"), st, rng=lambda: 4,
        )
        # roll=4 -> "fail" from crossroads table
        assert result.search_result == "fail"


# ─── TestSearchLoot ────────────────────────────────────────

class TestSearchLoot:
    """Verify TZ-3 search loot features."""

    def test_roll_3_partial_adds_item(self):
        """roll=3 partial -> 1 item added to inventory."""
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        st["hidden"]["same_action_count"] = 0
        # rng called: roll + pool index + value check = 3 calls
        idx = [0]
        vals = [3, 1, 4]  # roll=3, pool[1]=(4,6,"berries"), value=4
        def rng():
            val = vals[idx[0]]
            idx[0] += 1
            return val
        result = execute_action(Action("search", "Search"), st, rng=rng)
        assert result.search_result == "partial"
        assert len(st["visible"]["inventory"]) == 1

    def test_roll_6_crit_adds_item_and_coin(self):
        """roll=6 crit -> items + coin."""
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        st["hidden"]["same_action_count"] = 0
        # rng calls: roll + 2 picks + coin = 4 calls
        idx = [0]
        vals = [6, 1, 4, 1]
        def rng():
            val = vals[idx[0]]
            idx[0] += 1
            return val
        result = execute_action(Action("search", "Search"), st, rng=rng)
        assert result.search_result == "crit"
        assert len(st["visible"]["inventory"]) >= 1
        assert st["visible"]["wallet"]["coin"] > 50

    def test_roll_1_fail_penalty_applies_dot(self):
        """roll=1 fail_penalty -> DoT applied."""
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        st["hidden"]["same_action_count"] = 0
        result = execute_action(Action("search", "Search"), st, rng=lambda: 1)
        assert result.search_result == "fail_penalty"
        assert len(st["hidden"]["dot_effects"]) == 1
        assert st["hidden"]["dot_effects"][0]["ticks_left"] == 2
        assert st["visible"]["hp"] == 9

    def test_starting_bread_is_food(self):
        """Starting inventory has bread -> eat_food in menu."""
        st = make_state_no_location_types()
        st["visible"]["inventory"] = [{"name": "bread", "count": 2}]
        actions = loop_build_menu(st["visible"], st)
        keys = [a.key for a in actions]
        assert "eat_food" in keys

    def test_search_blocked_in_combat(self):
        """search in combat mode -> error_result."""
        st = make_state_no_location_types()
        st["hidden"]["current_mode"] = "combat"
        result = execute_action(Action("search", "Search"), st, rng=lambda: 4)
        assert result.search_result is None
        assert any("cannot search" in e for e in result.events)

    def test_search_counter_resets_on_other_action(self):
        """search, go_north, search -> second search counter == 1, no warning."""
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        # First search
        execute_action(Action("search", "Search"), st, rng=lambda: 3)
        assert st["hidden"]["same_action_count"] == 1
        # go_north resets counter
        execute_action(Action("go_north", "Go north"), st, rng=lambda: 4)
        assert st["hidden"]["same_action_count"] == 1
        # Second search - counter starts fresh
        execute_action(Action("search", "Search"), st, rng=lambda: 3)
        assert st["hidden"]["same_action_count"] == 1

    def test_3rd_search_penalty_no_dice(self):
        """Three searches in a row: on 3rd, rng not called (penalty before roll)."""
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        call_count = [0]
        def counting_rng():
            call_count[0] += 1
            return 3  # partial
        # 1st search
        execute_action(Action("search", "Search"), st, rng=counting_rng)
        # 2nd search
        execute_action(Action("search", "Search"), st, rng=counting_rng)
        count_before_3rd = call_count[0]
        # 3rd search - should trigger penalty WITHOUT calling rng
        execute_action(Action("search", "Search"), st, rng=counting_rng)
        assert call_count[0] == count_before_3rd, "rng should not be called on 3rd search"

    def test_3rd_search_penalty_no_loot(self):
        """On 3rd search, inventory and wallet don't change (vs after 2nd)."""
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        st["visible"]["inventory"] = []
        st["visible"]["wallet"] = {"coin": 50}
        # First search - gets loot
        execute_action(Action("search", "Search"), st, rng=lambda: 3)
        # Second search - gets loot
        execute_action(Action("search", "Search"), st, rng=lambda: 3)
        inv_before_3rd = len(st["visible"]["inventory"])
        wallet_before_3rd = st["visible"]["wallet"]["coin"]
        # Third search - penalty, NO loot
        execute_action(Action("search", "Search"), st, rng=lambda: 3)
        assert len(st["visible"]["inventory"]) == inv_before_3rd
        assert st["visible"]["wallet"]["coin"] == wallet_before_3rd

    def test_full_dot_lifecycle_3_ticks(self):
        """roll=1 -> -1 HP now, then 2 more ticks -> total 3 HP, expires."""
        from burt import search as search_mod
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        hp0 = st["visible"]["hp"]  # 10
        execute_action(Action("search", "Search"), st, rng=lambda: 1)
        # After fail_penalty: -1 HP, ticks_left=2
        assert st["visible"]["hp"] == hp0 - 1
        assert st["hidden"]["dot_effects"] == [{"ticks_left": 2}]
        # Tick 1
        hp_lost, over = search_mod.tick_dot(st)
        assert hp_lost == 1 and not over
        assert st["visible"]["hp"] == hp0 - 2
        assert st["hidden"]["dot_effects"] == [{"ticks_left": 1}]
        # Tick 2 (last)
        hp_lost, over = search_mod.tick_dot(st)
        assert hp_lost == 1 and not over
        assert st["visible"]["hp"] == hp0 - 3
        assert st["hidden"]["dot_effects"] == []
        # No more ticks
        hp_lost, over = search_mod.tick_dot(st)
        assert hp_lost == 0
        assert st["visible"]["hp"] == hp0 - 3

    def test_repeat_roll_1_no_stack(self):
        """Second roll=1 while poisoned: -1 HP now, existing DoT continues."""
        from burt import search as search_mod
        st = make_state_no_location_types()
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        st["visible"]["location"]["name"] = "Forest"
        hp0 = st["visible"]["hp"]
        # First roll=1
        execute_action(Action("search", "Search"), st, rng=lambda: 1)
        assert st["visible"]["hp"] == hp0 - 1
        assert st["hidden"]["dot_effects"] == [{"ticks_left": 2}]
        # Second roll=1 immediately
        execute_action(Action("search", "Search"), st, rng=lambda: 1)
        assert st["visible"]["hp"] == hp0 - 2
        # DoT not stacked, still one effect with ticks_left=2
        assert st["hidden"]["dot_effects"] == [{"ticks_left": 2}]

