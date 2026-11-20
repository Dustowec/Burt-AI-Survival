"""Tests for burt.skills — §8 skills and weapon mastery."""

import pytest

from burt import skills


def _state():
    return {"skills_raw": []}, {"skills_visible": []}


def _levels_up(hidden, visible, name, count):
    return skills.record_strike(hidden, visible, name, count=count)


class TestRegistry:
    def test_ten_skills(self):
        assert len(skills.SKILL_NAMES) == 10
        assert len(set(skills.SKILL_NAMES)) == 10

    def test_four_combat_six_non_combat(self):
        assert len(skills.COMBAT_SKILLS) == 4
        assert len(skills.NON_COMBAT_SKILLS) == 6
        assert set(skills.COMBAT_SKILLS) == {
            "Sword", "Club", "Spear", "Magic",
        }

    def test_names_match_spec(self):
        assert set(skills.SKILL_NAMES) == {
            "Sword", "Club", "Spear", "Magic",
            "Smithing", "Stealth", "Search",
            "Eloquence", "Intimidation", "Deception",
        }


class TestFormulas:
    @pytest.mark.parametrize("level,expected", [
        (0, 30),
        (1, 30),
        (2, 45),
        (3, 68),
        (4, 102),
        (10, 0),
    ])
    def test_strikes_to_next(self, level, expected):
        assert skills.strikes_to_next(level) == expected

    @pytest.mark.parametrize("level,expected", [
        (0, 0), (1, 0), (4, 0), (5, 1), (9, 1), (10, 2),
    ])
    def test_modifier(self, level, expected):
        assert skills.modifier(level) == expected

    @pytest.mark.parametrize("level,expected", [
        (0, 0), (1, 0), (2, 1), (3, 1), (4, 2),
        (9, 4), (10, 5),
    ])
    def test_range_bonus(self, level, expected):
        assert skills.range_bonus(level) == expected


class TestVisibility:
    def test_new_skill_is_hidden(self):
        hidden, visible = _state()
        skills.record_strike(hidden, visible, "Club")
        assert hidden["skills_raw"][0]["level"] == 0
        assert visible["skills_visible"] == []

    def test_skill_appears_at_level_one(self):
        hidden, visible = _state()
        _levels_up(hidden, visible, "Club", 30)
        assert hidden["skills_raw"][0]["level"] == 1
        assert visible["skills_visible"] == [
            {"name": "Club", "level": 1, "max": 10},
        ]

    def test_visible_keeps_order(self):
        hidden, visible = _state()
        _levels_up(hidden, visible, "Sword", 30)
        _levels_up(hidden, visible, "Magic", 30)
        assert [s["name"] for s in visible["skills_visible"]] == [
            "Sword", "Magic",
        ]


class TestGrowth:
    def test_thirty_strikes_level_one(self):
        hidden, visible = _state()
        gain = _levels_up(hidden, visible, "Sword", 29)
        assert gain.level == 0
        assert gain.strikes == 29
        gain = _levels_up(hidden, visible, "Sword", 1)
        assert gain.level == 1
        assert gain.levels_gained == 1
        assert gain.strikes == 0

    def test_next_threshold_level_two(self):
        hidden, visible = _state()
        _levels_up(hidden, visible, "Sword", 30)
        gain = _levels_up(hidden, visible, "Sword", 30)
        assert gain.level == 2
        assert gain.strikes_to_next == 45

    def test_three_levels_at_once(self):
        hidden, visible = _state()
        gain = _levels_up(hidden, visible, "Spear", 30 + 30 + 45)
        assert gain.level == 3
        assert gain.levels_gained == 3

    def test_cap_at_ten(self):
        hidden, visible = _state()
        gained = skills.award_level(hidden, visible, "Sword", levels=15)
        assert gained == 10
        gain = _levels_up(hidden, visible, "Sword", 1000)
        assert gain.level == 10
        assert gain.strikes_to_next == 0

    def test_strikes_count_even_without_hit(self):
        """§8: a strike counts regardless of hit or miss."""
        hidden, visible = _state()
        _levels_up(hidden, visible, "Club", 5)
        assert hidden["skills_raw"][0]["strikes"] == 5

    def test_unknown_skill_raises(self):
        hidden, visible = _state()
        with pytest.raises(ValueError):
            skills.record_strike(hidden, visible, "Basket weaving")

    @pytest.mark.parametrize("bad", [0, -1, 1.5, True, None])
    def test_bad_count_raises(self, bad):
        hidden, visible = _state()
        with pytest.raises(ValueError):
            skills.record_strike(hidden, visible, "Club", count=bad)


class TestTraining:
    def test_award_one_level(self):
        hidden, visible = _state()
        assert skills.award_level(hidden, visible, "Magic") == 1
        assert visible["skills_visible"] == [
            {"name": "Magic", "level": 1, "max": 10},
        ]

    def test_old_record_without_strikes_is_repaired(self):
        hidden = {"skills_raw": [{"name": "Magic", "level": 9}]}
        visible = {}
        skills.ensure_state(hidden, visible)
        entry = hidden["skills_raw"][0]
        assert entry["strikes"] == 0
        assert entry["strikes_to_next"] == skills.strikes_to_next(9)
        assert entry["curve"] == 1.5
        assert visible["skills_visible"][0]["level"] == 9

    def test_level_map(self):
        hidden, visible = _state()
        skills.award_level(hidden, visible, "Sword", levels=2)
        skills.award_level(hidden, visible, "Magic", levels=1)
        assert skills.level_map(hidden) == {"Sword": 2, "Magic": 1}
        assert skills.level_of(hidden, "Spear") == 0
