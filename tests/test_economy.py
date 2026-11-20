"""Economy core — spec §19, §35, §16.

Inventory stacks, price composition (location x reputation x trade bonus)
and the one-roll-per-node location modifier.
"""
from __future__ import annotations

import pytest

from burt import economy, trade


def _visible(*pairs):
    return {"inventory": [{"name": n, "count": c} for n, c in pairs]}


# ---------------------------------------------------------------------
# Inventory stacks (§19)
# ---------------------------------------------------------------------

class TestInventory:
    def test_count_sums_stacks(self):
        v = _visible(("bread", 2), ("bread", 1))
        assert economy.item_count(v, "bread") == 3

    def test_count_is_case_insensitive(self):
        v = _visible(("Bread", 1))
        assert economy.item_count(v, "bread") == 1

    def test_count_missing_is_zero(self):
        assert economy.item_count(_visible(("bread", 1)), "pelt") == 0

    def test_has_item(self):
        v = _visible(("bedroll", 1))
        assert economy.has_item(v, "bedroll") is True
        assert economy.has_item(v, "staff") is False

    def test_add_item_merges_stack(self):
        v = _visible(("bread", 2))
        economy.add_item(v, "bread")
        assert v["inventory"] == [{"name": "bread", "count": 3}]

    def test_add_item_creates_stack(self):
        v = _visible()
        economy.add_item(v, "pelt", 2)
        assert v["inventory"] == [{"name": "pelt", "count": 2}]

    def test_add_item_rejects_zero(self):
        with pytest.raises(ValueError):
            economy.add_item(_visible(), "bread", 0)

    def test_remove_item_decrements(self):
        v = _visible(("bread", 2))
        assert economy.remove_item(v, "bread") is True
        assert v["inventory"] == [{"name": "bread", "count": 1}]

    def test_remove_last_drops_stack(self):
        v = _visible(("bandage", 1), ("pelt", 1))
        assert economy.remove_item(v, "bandage") is True
        assert v["inventory"] == [{"name": "pelt", "count": 1}]

    def test_remove_too_many_changes_nothing(self):
        v = _visible(("bread", 1))
        assert economy.remove_item(v, "bread", 2) is False
        assert v["inventory"] == [{"name": "bread", "count": 1}]

    def test_remove_missing_item(self):
        v = _visible(("bread", 1))
        assert economy.remove_item(v, "pelt") is False


# ---------------------------------------------------------------------
# What can be sold (§22 loot, §35 base goods)
# ---------------------------------------------------------------------

class TestSellability:
    def test_base_goods_are_sellable(self):
        assert economy.is_sellable("bread") is True

    def test_loot_is_sellable(self):
        assert economy.is_sellable("dragon_scale") is True

    def test_search_junk_is_not_sellable(self):
        assert economy.is_sellable("berries") is False

    def test_sellable_items_skips_unpriced(self):
        v = _visible(("berries", 1), ("pelt", 1), ("bread", 2))
        assert economy.sellable_items(v) == ["bread", "pelt"]

    def test_sellable_items_skips_empty_stacks(self):
        v = _visible(("pelt", 0))
        assert economy.sellable_items(v) == []
# ---------------------------------------------------------------------
# Composition (§35 rounding + §16 + trade bonus)
# ---------------------------------------------------------------------

class TestComposition:
    def test_neutral_modifiers_keep_base(self):
        assert economy.buy_price("bread") == trade.BASE_PRICES["bread"]

    def test_location_125_rounds_down(self):
        # bread is 2 -> 2 * 1.25 = 2.5 -> 2
        assert economy.buy_price("bread", location=1.25) == 2
        assert economy.buy_price("staff", location=1.25) == 125

    def test_location_075(self):
        assert economy.buy_price("staff", location=0.75) == 75

    def test_reputation_high_is_cheaper(self):
        assert economy.buy_price("staff", reputation=0.9) == 90

    def test_reputation_low_is_dearer(self):
        assert economy.buy_price("staff", reputation=1.1) == 110

    def test_trade_bonus_20_percent(self):
        assert economy.buy_price("staff", trade_bonus=0.8) == 80

    def test_all_three_compose_exactly(self):
        # 100 * 1.25 * 0.9 * 0.8 = 90 exactly (no float noise)
        assert economy.buy_price(
            "staff", location=1.25, reputation=0.9, trade_bonus=0.8,
        ) == 90

    def test_sell_is_half_base(self):
        assert economy.sell_price("pelt") == 5

    def test_sell_uses_loot_price(self):
        assert economy.sell_price("dragon_scale") == 500

    def test_sell_bandage_is_zero(self):
        # §35: floor(floor(1 * 0.5) * mod) == 0, no minimum.
        assert economy.sell_price("bandage") == 0

    def test_sell_with_location_modifier(self):
        # pelt 10 -> half 5 -> 5 * 1.25 = 6.25 -> 6
        assert economy.sell_price("pelt", location=1.25) == 6

    def test_sell_unknown_item_raises(self):
        with pytest.raises(KeyError):
            economy.sell_price("berries")

    def test_buy_unknown_item_raises(self):
        with pytest.raises(KeyError):
            economy.buy_price("pelt")


# ---------------------------------------------------------------------
# Location modifier (§35): one roll per node
# ---------------------------------------------------------------------

class TestLocationModifier:
    def test_rolls_once_and_caches(self):
        hidden = {}
        calls = []

        def rng():
            calls.append(1)
            return 1

        first = economy.modifier_for_node(hidden, "n1", rng)
        second = economy.modifier_for_node(hidden, "n1", rng)
        assert first == second == 1.25
        assert len(calls) == 1

    def test_each_node_has_own_modifier(self):
        hidden = {}
        rolls = [1, 6]

        def rng():
            return rolls.pop(0)

        assert economy.modifier_for_node(hidden, "n1", rng) == 1.25
        assert economy.modifier_for_node(hidden, "n2", rng) == 0.75
        assert hidden["prices_by_node"] == {"n1": 1.25, "n2": 0.75}

    def test_current_modifier_is_mirrored(self):
        hidden = {}
        economy.modifier_for_node(hidden, "n1", lambda: 3)
        assert hidden["price_modifier"] == 1.0

    def test_cached_modifier_never_rolls(self):
        hidden = {"prices_by_node": {"n1": 0.75}}

        def rng():
            raise AssertionError("cached_modifier must not roll")

        assert economy.cached_modifier(hidden, "n1") == 0.75
        assert economy.cached_modifier(hidden, "n2") == 1.0