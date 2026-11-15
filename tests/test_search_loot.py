"""Tests for burt.search - search loot module."""
import pytest
from burt.search import (
    resolve_search, apply_dot, tick_dot, sync_poisoned_effect,
    increment_search_counter, check_search_penalty,
    SEARCH_AVAILABLE, SEARCH_POOLS,
)
from burt.dice import SearchResult as SearchRollResult


def _state(**overrides):
    st = {
        "visible": {"hp": 10, "hp_max": 10, "effects": []},
        "hidden": {"dot_effects": [], "same_action_count": 0},
    }
    st["visible"].update(overrides.get("visible", {}))
    st["hidden"].update(overrides.get("hidden", {}))
    return st


class TestResolveSearch:
    def test_roll_1_fail_penalty(self):
        result, items, coin = resolve_search(1, "forest", lambda: 4)
        assert result.result == "fail_penalty"
        assert items == []
        assert coin == 0

    def test_roll_2_fail(self):
        result, items, coin = resolve_search(2, "forest", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_3_partial_forest(self):
        result, items, coin = resolve_search(3, "forest", lambda: 2)
        assert result.result == "partial"
        assert len(items) == 1
        assert items[0] in ("mushrooms", "berries")

    def test_roll_5_success_forest(self):
        result, items, coin = resolve_search(5, "forest", lambda: 2)
        assert result.result == "success"
        assert len(items) == 2

    def test_roll_6_crit_forest(self):
        result, items, coin = resolve_search(6, "forest", lambda: 2)
        assert result.result == "crit"
        assert len(items) == 2
        assert coin > 0


class TestCrossroadsSearch:
    def test_roll_1_fail_penalty(self):
        result, items, coin = resolve_search(1, "crossroads", lambda: 4)
        assert result.result == "fail_penalty"
        assert items == []

    def test_roll_2_empty(self):
        result, items, coin = resolve_search(2, "crossroads", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_3_empty(self):
        result, items, coin = resolve_search(3, "crossroads", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_4_empty(self):
        result, items, coin = resolve_search(4, "crossroads", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_5_empty(self):
        result, items, coin = resolve_search(5, "crossroads", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_6_coins(self):
        rng_vals = [2, 4]
        idx = [0]
        def rng():
            val = rng_vals[idx[0]]
            idx[0] += 1
            return val
        result, items, coin = resolve_search(6, "crossroads", rng)
        assert result.result == "crit"
        assert items == []
        assert coin == 4

    def test_roll_6_club(self):
        rng_vals = [5]
        idx = [0]
        def rng():
            val = rng_vals[idx[0]]
            idx[0] += 1
            return val
        result, items, coin = resolve_search(6, "crossroads", rng)
        assert result.result == "crit"
        assert items == ["club"]
        assert coin == 0


class TestRoadSearch:
    def test_roll_1_fail_penalty(self):
        result, items, coin = resolve_search(1, "road", lambda: 4)
        assert result.result == "fail_penalty"

    def test_roll_2_empty(self):
        result, items, coin = resolve_search(2, "road", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_3_empty(self):
        result, items, coin = resolve_search(3, "road", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_4_empty(self):
        result, items, coin = resolve_search(4, "road", lambda: 4)
        assert result.result == "fail"
        assert items == []
        assert coin == 0

    def test_roll_5_success_coin(self):
        result, items, coin = resolve_search(5, "road", lambda: 4)
        assert result.result == "success"
        assert items == []
        assert coin == 4

    def test_roll_6_no_coins(self):
        rng_vals = [1]
        idx = [0]
        def rng():
            val = rng_vals[idx[0]]
            idx[0] += 1
            return val
        result, items, coin = resolve_search(6, "road", rng)
        assert result.result == "crit"
        assert items == ["club"]
        assert coin == 0


class TestFoodLocation:
    def test_forest_success_always_2(self):
        rng_vals = [1, 1]
        idx = [0]
        def rng():
            val = rng_vals[idx[0]]
            idx[0] += 1
            return val
        result, items, coin = resolve_search(5, "forest", rng)
        assert result.result == "success"
        assert items == ["mushrooms", "mushrooms"]
        assert coin == 0

    def test_forest_crit_2_items_and_coin(self):
        rng_vals = [1, 2, 5]
        idx = [0]
        def rng():
            val = rng_vals[idx[0]]
            idx[0] += 1
            return val
        result, items, coin = resolve_search(6, "forest", rng)
        assert result.result == "crit"
        assert items == ["mushrooms", "berries"]
        assert coin == 5


class TestDoT:
    def test_apply_dot_creates_effect(self):
        st = _state()
        apply_dot(st)
        assert st["hidden"]["dot_effects"] == [{"ticks_left": 2}]
        assert st["visible"]["hp"] == 9

    def test_apply_dot_does_not_stack(self):
        st = _state()
        apply_dot(st)
        apply_dot(st)
        assert len(st["hidden"]["dot_effects"]) == 1
        assert st["visible"]["hp"] == 8

    def test_tick_dot_decrements(self):
        st = _state()
        st["hidden"]["dot_effects"] = [{"ticks_left": 2}]
        hp_lost, game_over = tick_dot(st)
        assert hp_lost == 1
        assert not game_over
        assert st["hidden"]["dot_effects"] == [{"ticks_left": 1}]
        assert st["visible"]["hp"] == 9

    def test_tick_dot_expires(self):
        st = _state()
        st["hidden"]["dot_effects"] = [{"ticks_left": 1}]
        hp_lost, game_over = tick_dot(st)
        assert hp_lost == 1
        assert st["hidden"]["dot_effects"] == []

    def test_tick_dot_death(self):
        st = _state(visible={"hp": 1})
        st["hidden"]["dot_effects"] = [{"ticks_left": 2}]
        hp_lost, game_over = tick_dot(st)
        assert hp_lost == 1
        assert game_over


class TestSearchCounter:
    def test_increment(self):
        st = _state()
        assert increment_search_counter(st) == 1
        assert increment_search_counter(st) == 2

    def test_check_3rd_penalty(self):
        """3rd search (count=2 before increment): penalty applied."""
        st = _state()
        increment_search_counter(st)  # count = 1
        increment_search_counter(st)  # count = 2
        has_pen, msg = check_search_penalty(st)
        assert has_pen
        assert "Divine spit" in msg
        has_pen, msg = check_search_penalty(st)
        assert has_pen
        assert "Divine spit" in msg


class TestSyncPoisoned:
    def test_add_poisoned(self):
        st = _state()
        st["hidden"]["dot_effects"] = [{"ticks_left": 2}]
        sync_poisoned_effect(st)
        assert "poisoned" in st["visible"]["effects"]

    def test_remove_poisoned(self):
        st = _state(visible={"effects": ["poisoned"]})
        st["hidden"]["dot_effects"] = []
        sync_poisoned_effect(st)
        assert "poisoned" not in st["visible"]["effects"]
