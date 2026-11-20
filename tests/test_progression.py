"""Tests for burt.progression — §7 experience and levels.

Spec tables checked:
    cap(level) = 10 * 1.5^(level-1)
    total kills to level: 2, 5, 10, 17, 27, 42, 65, 99, 150, 227, ...
"""

from fractions import Fraction

import pytest

from burt import progression as p


# ---------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------

class TestCap:
    def test_level_one_is_ten(self):
        assert p.cap(1) == 10

    def test_growth_is_1_5(self):
        assert p.cap(2) == 15
        assert p.cap(3) == Fraction(45, 2)       # 22.5
        assert p.cap(4) == Fraction(135, 4)      # 33.75
        assert p.cap(5) == Fraction(405, 8)      # 50.625

    def test_level_ten(self):
        assert p.cap(10) == Fraction(98415, 256)  # 384.43359375

    @pytest.mark.parametrize("bad", [0, -1, 1.5, True, "1", None])
    def test_rejects_bad_level(self, bad):
        with pytest.raises(ValueError):
            p.cap(bad)


class TestTotalXp:
    def test_level_one_is_zero(self):
        assert p.total_xp_for_level(1) == 0

    def test_known_thresholds(self):
        assert p.total_xp_for_level(2) == 10
        assert p.total_xp_for_level(3) == 25
        assert p.total_xp_for_level(4) == Fraction(95, 2)   # 47.5
        assert p.total_xp_for_level(5) == Fraction(325, 4)  # 81.25


class TestLevelForXp:
    @pytest.mark.parametrize("kills,expected", [
        (0, 1),
        (1, 1),
        (2, 2),
        (4, 2),
        (5, 3),
        (9, 3),
        (10, 4),
        (16, 4),
        (17, 5),
        (26, 5),
        (27, 6),
        (41, 6),
        (42, 7),
        (64, 7),
        (65, 8),
        (98, 8),
        (99, 9),
        (149, 9),
        (150, 10),
        (226, 10),
        (227, 11),
    ])
    def test_spec_total_kills_table(self, kills, expected):
        assert p.level_for_xp(kills * p.KILL_EXP) == expected

    def test_rejects_negative_xp(self):
        with pytest.raises(ValueError):
            p.level_for_xp(-1)


class TestLevelProgress:
    def test_level_one_start(self):
        assert p.level_progress(1, 0) == (0, 10)

    def test_level_one_half(self):
        assert p.level_progress(1, 5) == (5, 10)

    def test_level_two_start(self):
        assert p.level_progress(2, 10) == (0, 15)

    def test_level_three_carryover(self):
        # 5 kills = 25 xp -> level 3 with 0 inside; 7 kills = 35 xp -> 10 inside
        assert p.level_progress(3, 35) == (10, 23)


# ---------------------------------------------------------------------
# Awarding kills
# ---------------------------------------------------------------------

def _visible(**overrides):
    base = {
        "hp": 10, "hp_max": 10,
        "mp": 3, "mp_max": 3,
        "level": 1, "xp": 0,
    }
    base.update(overrides)
    return base


class TestAwardKills:
    def test_one_kill_no_level_up(self):
        v = _visible()
        result = p.award_kills(v, 1)
        assert v["xp"] == 5
        assert v["level"] == 1
        assert v["hp_max"] == 10
        assert v["mp_max"] == 3
        assert result.levels_gained == 0
        assert result.gained == 5

    def test_two_kills_level_two(self):
        v = _visible()
        result = p.award_kills(v, 2)
        assert v["level"] == 2
        assert v["xp"] == 10
        assert v["hp_max"] == 12
        assert v["mp_max"] == 4
        assert v["hp"] == 12
        assert v["mp"] == 4
        assert result.levels_gained == 1

    def test_multiple_levels_at_once(self):
        v = _visible()
        result = p.award_kills(v, 6)      # 30 xp -> level 3
        assert v["level"] == 3
        assert v["xp"] == 30
        assert v["hp_max"] == 14
        assert v["mp_max"] == 5
        assert result.levels_gained == 2

    def test_level_five_after_seventeen_kills(self):
        v = _visible()
        p.award_kills(v, 17)
        assert v["level"] == 5
        assert v["xp"] == 85
        assert v["hp_max"] == 18
        assert v["mp_max"] == 7

    def test_current_hp_is_clamped(self):
        v = _visible(hp=10, hp_max=10)
        p.award_kills(v, 2)
        assert v["hp"] == 12

        v = _visible(hp=3, hp_max=10)
        p.award_kills(v, 2)
        assert v["hp"] == 5

    def test_unknown_fields_get_defaults(self):
        v = {"hp": 4, "hp_max": 10, "mp": 1, "mp_max": 3}
        p.award_kills(v, 2)
        assert v["level"] == 2
        assert v["xp"] == 10

    def test_zero_kills_is_noop(self):
        v = _visible()
        result = p.award_kills(v, 0)
        assert result.gained == 0
        assert v["xp"] == 0
        assert v["level"] == 1

    @pytest.mark.parametrize("bad", [-1, 1.5, True, "2", None])
    def test_rejects_bad_kills(self, bad):
        with pytest.raises(ValueError):
            p.award_kills(_visible(), bad)


class TestEnsureState:
    def test_adds_missing_fields(self):
        v = {}
        p.ensure_state(v)
        assert v["level"] == 1
        assert v["xp"] == 0

    def test_repairs_invalid_values(self):
        v = {"level": 0, "xp": -5}
        p.ensure_state(v)
        assert v["level"] == 1
        assert v["xp"] == 0

    def test_keeps_valid_values(self):
        v = {"level": 4, "xp": 50}
        p.ensure_state(v)
        assert v["level"] == 4
        assert v["xp"] == 50

    def test_repairs_xp_below_the_level_threshold(self):
        v = {"level": 4, "xp": 0}
        p.ensure_state(v)
        assert v["level"] == 4
        assert v["xp"] == 47   # floor(total_xp_for_level(4))

    def test_award_never_lowers_the_level(self):
        v = _visible(level=5, xp=0)
        result = p.award_kills(v, 1)
        assert v["level"] == 5
        assert v["xp"] == 81   # floor(total_xp_for_level(5))
        assert result.levels_gained == 0
