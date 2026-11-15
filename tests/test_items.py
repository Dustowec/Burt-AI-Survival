"""Tests for burt.items - item registry."""
import pytest
from burt.items import ITEMS, Item, is_food, is_junk


class TestItemRegistry:
    def test_all_items_exist(self):
        assert "berries" in ITEMS
        assert "mushrooms" in ITEMS
        assert "roots" in ITEMS
        assert "moss" in ITEMS
        assert "fish" in ITEMS
        assert "shell" in ITEMS
        assert "club" in ITEMS
        assert "low_quality_sword" in ITEMS
        assert "spear" in ITEMS
        assert "bread" in ITEMS
        assert "food" in ITEMS
        assert "dried_fish" in ITEMS

    def test_food_items_have_hp_restore(self):
        for name in ("berries", "mushrooms", "roots", "moss", "fish",
                     "bread", "food", "dried_fish"):
            item = ITEMS[name]
            assert item.category == "food"
            assert item.hp_restore == 1

    def test_junk_items(self):
        shell = ITEMS["shell"]
        assert shell.category == "junk"
        assert shell.hp_restore == 0

    def test_weapon_items(self):
        for name in ("club", "low_quality_sword", "spear"):
            item = ITEMS[name]
            assert item.category == "weapon"
            assert item.hp_restore == 0

    def test_item_is_frozen(self):
        item = ITEMS["berries"]
        with pytest.raises(Exception):
            item.hp_restore = 2

    def test_item_has_display_name(self):
        assert ITEMS["berries"].display == "Berries"
        assert ITEMS["club"].display == "Club"


class TestIsFood:
    def test_is_food_bread(self):
        assert is_food("bread") is True

    def test_is_food_berries(self):
        assert is_food("berries") is True

    def test_is_food_fish(self):
        assert is_food("fish") is True

    def test_is_food_shell_false(self):
        assert is_food("shell") is False

    def test_is_food_club_false(self):
        assert is_food("club") is False

    def test_is_food_unknown(self):
        assert is_food("unknown") is False

    def test_is_food_case_insensitive(self):
        assert is_food("BERRIES") is True

    def test_is_food_empty(self):
        assert is_food("") is False


class TestIsJunk:
    def test_is_junk_shell(self):
        assert is_junk("shell") is True

    def test_is_junk_berries_false(self):
        assert is_junk("berries") is False
