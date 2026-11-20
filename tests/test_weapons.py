"""Tests for burt.weapons — §20 damage table, quality, mastery, selection."""

import pytest

from burt import weapons


class TestDamageTable:
    @pytest.mark.parametrize("key,expected", [
        ("fists", (0, 1)),
        ("stone", (0, 1)),
        ("goblin_dagger", (1, 2)),
        ("goblin_staff", (0, 1)),
        ("club", (1, 2)),
        ("spear", (1, 3)),
        ("low_quality_sword", (1, 3)),
        ("ordinary_sword", (2, 4)),
        ("high_quality_sword", (3, 5)),
        ("sword", (2, 4)),
        ("staff", (0, 1)),
    ])
    def test_spec_ranges(self, key, expected):
        assert weapons.damage_range(key) == expected

    def test_stranger_weapon_raises(self):
        with pytest.raises(KeyError):
            weapons.damage_range("unicorn_horn")


class TestQuality:
    def test_low_shifts_minus_one(self):
        assert weapons.damage_range("low_quality_sword") == (1, 3)

    def test_ordinary_is_standard(self):
        assert weapons.damage_range("ordinary_sword") == (2, 4)

    def test_high_shifts_plus_one(self):
        assert weapons.damage_range("high_quality_sword") == (3, 5)

    def test_goblin_weapons_are_not_gradable(self):
        assert weapons.WEAPONS["goblin_dagger"].quality is None
        assert weapons.WEAPONS["goblin_staff"].quality is None


class TestNonHumanoidBan:
    @pytest.mark.parametrize("key", ["goblin_dagger", "goblin_staff"])
    def test_forbidden_in_combat(self, key):
        assert weapons.is_usable(key) is False

    @pytest.mark.parametrize("key", [
        "fists", "club", "spear", "ordinary_sword", "staff",
    ])
    def test_normal_weapons_are_usable(self, key):
        assert weapons.is_usable(key) is True

    def test_unknown_is_not_usable(self):
        assert weapons.is_usable("unicorn_horn") is False


class TestMastery:
    def test_range_bonus_every_two_levels(self):
        assert weapons.damage_range("club", 1) == (1, 2)
        assert weapons.damage_range("club", 2) == (2, 3)
        assert weapons.damage_range("club", 4) == (3, 4)
        assert weapons.damage_range("club", 10) == (6, 7)

    def test_quality_and_mastery_stack(self):
        # low sword 1-3, +2 at mastery 4 -> 3-5
        assert weapons.damage_range("low_quality_sword", 4) == (3, 5)

    def test_no_mastery_for_fists(self):
        assert weapons.damage_range("fists", 10) == (0, 1)

    def test_magic_range(self):
        assert weapons.magic_damage_range(0) == (3, 6)
        assert weapons.magic_damage_range(2) == (4, 7)
        assert weapons.magic_damage_range(10) == (8, 11)

    def test_weapon_skill_mapping(self):
        assert weapons.weapon_skill("club") == "Club"
        assert weapons.weapon_skill("ordinary_sword") == "Sword"
        assert weapons.weapon_skill("goblin_dagger") is None
        assert weapons.weapon_skill("staff") is None


def _inv(*names):
    return [{"name": n, "count": 1} for n in names]


class TestSelectWeapon:
    def test_empty_inventory_fists(self):
        choice = weapons.select_weapon([])
        assert choice.key == "fists"
        assert (choice.damage_min, choice.damage_max) == (0, 1)

    def test_single_weapon(self):
        choice = weapons.select_weapon(_inv("club"))
        assert choice.key == "club"
        assert (choice.damage_min, choice.damage_max) == (1, 2)

    def test_best_effective_weapon_wins(self):
        choice = weapons.select_weapon(_inv("club", "ordinary_sword", "spear"))
        assert choice.key == "ordinary_sword"
        assert (choice.damage_min, choice.damage_max) == (2, 4)

    def test_mastery_can_change_the_best_weapon(self):
        # Spear 1-3 +5 at mastery 10 = 6-8; ordinary sword 2-4 at 0 = 2-4
        choice = weapons.select_weapon(
            _inv("spear", "ordinary_sword"),
            {"Spear": 10},
        )
        assert choice.key == "spear"
        assert (choice.damage_min, choice.damage_max) == (6, 8)

    def test_forbidden_weapons_are_skipped(self):
        choice = weapons.select_weapon(_inv("goblin_dagger", "goblin_staff"))
        assert choice.key == "fists"

    def test_forbidden_does_not_block_a_real_weapon(self):
        choice = weapons.select_weapon(_inv("goblin_dagger", "club"))
        assert choice.key == "club"

    def test_zero_count_is_skipped(self):
        inv = [{"name": "ordinary_sword", "count": 0}]
        assert weapons.select_weapon(inv).key == "fists"

    def test_unknown_item_is_skipped(self):
        assert weapons.select_weapon(_inv("unicorn_horn")).key == "fists"

    def test_bad_count_is_skipped(self):
        inv = [{"name": "ordinary_sword", "count": "lots"}]
        assert weapons.select_weapon(inv).key == "fists"
