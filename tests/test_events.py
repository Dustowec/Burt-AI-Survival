"""Random events and effects — spec §10, §13.

Contract for burt.events:
- preacher dice: 1 -> curse, 2..5 -> nothing, 6 -> blessing;
- curse = -1 to rolls, blessing = +1, both last exactly 3 actions;
- effects live in hidden["effects_detail"], visible["effects"] carries
  only the types (no duration, no numbers);
- a preacher is spawned by the positive-event generator (d6 5-6) and is
  never cached in hidden["npcs_by_node"] (he is not a role).
"""
from __future__ import annotations

import pytest

from burt import events


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


def make_state() -> dict:
    return {
        "visible": {"effects": []},
        "hidden": {"effects_detail": [], "npcs_here": [],
                   "npcs_by_node": {}, "events_here": []},
    }


# ---------------------------------------------------------------------
# §13: preacher dice table
# ---------------------------------------------------------------------

class TestPreacherTable:
    @pytest.mark.parametrize("roll,kind", [
        (1, "curse"),
        (2, "nothing"),
        (3, "nothing"),
        (4, "nothing"),
        (5, "nothing"),
        (6, "blessing"),
    ])
    def test_table(self, roll, kind):
        assert events.resolve_preacher(roll) == kind

    @pytest.mark.parametrize("roll", [0, 7, -1, 99])
    def test_invalid_roll(self, roll):
        with pytest.raises(ValueError):
            events.resolve_preacher(roll)

    def test_constants(self):
        assert events.EFFECT_DURATION == 3
        assert events.PREACHER_KEY == "preacher_event"
        assert events.PREACHER_ENCOUNTER_TEXT == (
            "You are lucky to meet a preacher."
        )


class TestEffectFor:
    def test_curse(self):
        assert events.effect_for("curse") == events.EFFECT_CURSED

    def test_blessing(self):
        assert events.effect_for("blessing") == events.EFFECT_BLESSED

    def test_nothing(self):
        assert events.effect_for("nothing") is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            events.effect_for("doom")


# ---------------------------------------------------------------------
# Effects state
# ---------------------------------------------------------------------

class TestApplyEffect:
    def test_blessed(self):
        st = make_state()
        entry = events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED,
        )
        assert entry["type"] == "blessed"
        assert entry["modifier"] == 1
        assert entry["turns_left"] == 3
        assert st["visible"]["effects"] == ["blessed"]
        assert events.modifier(st["hidden"]) == 1

    def test_cursed(self):
        st = make_state()
        entry = events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_CURSED,
        )
        assert entry["type"] == "cursed"
        assert entry["modifier"] == -1
        assert st["visible"]["effects"] == ["cursed"]
        assert events.modifier(st["hidden"]) == -1

    def test_refresh_same_effect(self):
        st = make_state()
        events.apply_effect(st["hidden"], st["visible"], events.EFFECT_BLESSED)
        events.tick(st["hidden"], st["visible"])
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 2
        events.apply_effect(st["hidden"], st["visible"], events.EFFECT_BLESSED)
        assert len(st["hidden"]["effects_detail"]) == 1
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 3

    def test_blessed_and_cursed_coexist(self):
        st = make_state()
        events.apply_effect(st["hidden"], st["visible"], events.EFFECT_BLESSED)
        events.apply_effect(st["hidden"], st["visible"], events.EFFECT_CURSED)
        assert st["visible"]["effects"] == ["blessed", "cursed"]
        assert events.modifier(st["hidden"]) == 0

    def test_custom_duration(self):
        st = make_state()
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED, duration=1,
        )
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 1

    def test_invalid_type(self):
        st = make_state()
        with pytest.raises(ValueError):
            events.apply_effect(st["hidden"], st["visible"], "poisoned")



class TestTick:
    def test_three_actions(self):
        st = make_state()
        events.apply_effect(st["hidden"], st["visible"], events.EFFECT_BLESSED)
        assert events.tick(st["hidden"], st["visible"]) == []
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 2
        assert events.modifier(st["hidden"]) == 1
        assert events.tick(st["hidden"], st["visible"]) == []
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 1
        assert events.tick(st["hidden"], st["visible"]) == ["blessed"]
        assert st["hidden"]["effects_detail"] == []
        assert st["visible"]["effects"] == []
        assert events.modifier(st["hidden"]) == 0

    def test_expired_types_returned_once(self):
        st = make_state()
        events.apply_effect(st["hidden"], st["visible"], events.EFFECT_CURSED)
        events.tick(st["hidden"], st["visible"])
        events.tick(st["hidden"], st["visible"])
        assert events.tick(st["hidden"], st["visible"]) == ["cursed"]
        assert events.tick(st["hidden"], st["visible"]) == []

    def test_no_detail_does_not_create_key(self):
        st = {"visible": {"effects": []}, "hidden": {}}
        events.tick(st["hidden"], st["visible"])
        assert "effects_detail" not in st["hidden"]

    def test_sync_removes_stale_visible_effect(self):
        st = {"visible": {"effects": ["blessed"]},
              "hidden": {"effects_detail": []}}
        events.tick(st["hidden"], st["visible"])
        assert st["visible"]["effects"] == []


class TestEnsureState:
    def test_missing(self):
        hidden = {}
        assert events.ensure_state(hidden) == []
        assert hidden["effects_detail"] == []

    def test_repairs_entries(self):
        hidden = {"effects_detail": [
            {"type": "blessed", "turns_left": 2},
            {"type": "poisoned", "turns_left": 2},
            {"type": "cursed", "turns_left": 0},
            "junk",
        ]}
        cleaned = events.ensure_state(hidden)
        assert len(cleaned) == 1
        assert cleaned[0]["type"] == "blessed"
        assert cleaned[0]["modifier"] == 1
        assert cleaned[0]["turns_left"] == 2

    def test_keeps_valid_modifier(self):
        hidden = {"effects_detail": [
            {"type": "cursed", "modifier": -1, "turns_left": 1},
        ]}
        assert events.ensure_state(hidden)[0]["modifier"] == -1

    def test_non_list(self):
        hidden = {"effects_detail": "broken"}
        assert events.ensure_state(hidden) == []
        assert hidden["effects_detail"] == []


class TestSyncVisible:
    def test_order_preserved(self):
        hidden = {"effects_detail": [
            {"type": "cursed", "modifier": -1, "turns_left": 1},
            {"type": "blessed", "modifier": 1, "turns_left": 1},
        ]}
        visible = {"effects": []}
        events.sync_visible(hidden, visible)
        assert visible["effects"] == ["cursed", "blessed"]

    def test_empty(self):
        visible = {"effects": ["blessed"]}
        events.sync_visible({"effects_detail": []}, visible)
        assert visible["effects"] == []



# ---------------------------------------------------------------------
# §13 / §10: preacher spawn
# ---------------------------------------------------------------------

class TestSpawnPreacher:
    @pytest.mark.parametrize("roll", [1, 2, 3, 4])
    def test_not_good_no_spawn(self, roll):
        hidden = {"npcs_here": [], "npcs_by_node": {}, "events_here": []}
        assert events.spawn_preacher(hidden, _rng_seq(roll)) is False
        assert hidden["npcs_here"] == []
        assert hidden["events_here"] == []

    @pytest.mark.parametrize("roll", [5, 6])
    def test_good_spawns(self, roll):
        hidden = {"npcs_here": [], "npcs_by_node": {}, "events_here": []}
        assert events.spawn_preacher(hidden, _rng_seq(roll)) is True
        assert hidden["npcs_here"] == [events.PREACHER_KEY]
        assert hidden["events_here"] == [{"type": "preacher", "used": False}]
        assert hidden["npcs_by_node"] == {}

    def test_no_duplicate(self):
        hidden = {"npcs_here": [], "npcs_by_node": {}, "events_here": []}
        assert events.spawn_preacher(hidden, _rng_seq(5)) is True
        assert events.spawn_preacher(hidden, _rng_seq(6)) is False
        assert hidden["npcs_here"] == [events.PREACHER_KEY]
        assert len(hidden["events_here"]) == 1

    def test_invalid_roll(self):
        hidden = {"npcs_here": [], "npcs_by_node": {}, "events_here": []}
        with pytest.raises(ValueError):
            events.spawn_preacher(hidden, _rng_seq(7))


class TestMarkPreacherUsed:
    def test_marks_only_preacher(self):
        hidden = {"events_here": [
            {"type": "mage", "used": False},
            {"type": "preacher", "used": False},
        ]}
        assert events.mark_preacher_used(hidden) is True
        assert hidden["events_here"][0]["used"] is False
        assert hidden["events_here"][1]["used"] is True

    def test_second_call_returns_false(self):
        hidden = {"events_here": [{"type": "preacher", "used": False}]}
        assert events.mark_preacher_used(hidden) is True
        assert events.mark_preacher_used(hidden) is False

    def test_missing_returns_false(self):
        assert events.mark_preacher_used({"events_here": []}) is False

