"""Reputation — spec §16.

Per role, not per NPC. Range -10..+10.

Changes:
    dialogue success  +1
    dialogue neutral   0
    dialogue fail     -1
    dialogue anger    -2
    quest completed   +1
    quest failed      -2
    resident killed   -5 overall, -10 for the victim's role (§34)

Limits: one change per dialogue, one per quest.

Effects:
    rep >= +5  better prices, warmer tone, more quests
    rep <= -5  worse prices, colder tone, no quests
"""
from __future__ import annotations

import pytest

from burt import reputation


ROLES = ("elder", "blacksmith", "merchant", "guard",
         "fisherman", "veteran", "tavernkeeper")


def make_state(rep=None):
    return {
        "meta": {"life": 1, "day": 1, "step": 0},
        "visible": {"hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
                    "wallet": {"coin": 50}, "inventory": [],
                    "effects": [], "eat": True, "sleep_counter": 0,
                    "date": "1 day", "skills_visible": [],
                    "location": {"name": "Village", "exits": ["north"]}},
        "hidden": {
            "day": 1, "step": 0,
            "reputation": rep or {r: 0 for r in ROLES},
        },
    }


# ---------------------------------------------------------------------
# Basic change (§16)
# ---------------------------------------------------------------------

class TestChange:
    def test_increase(self):
        st = make_state()
        assert reputation.change(st, "elder", 1) == 1

    def test_decrease(self):
        st = make_state()
        assert reputation.change(st, "elder", -1) == -1

    def test_clamped_upper(self):
        st = make_state({"elder": 10})
        assert reputation.change(st, "elder", 5) == 10

    def test_clamped_lower(self):
        st = make_state({"elder": -10})
        assert reputation.change(st, "elder", -5) == -10

    def test_unknown_role_is_ignored(self):
        st = make_state()
        assert reputation.change(st, "dragon", 1) == 0
        assert "dragon" not in st["hidden"]["reputation"]

    def test_get(self):
        st = make_state({"elder": 3})
        assert reputation.get(st, "elder") == 3

    def test_get_unknown_role(self):
        st = make_state()
        assert reputation.get(st, "dragon") == 0


# ---------------------------------------------------------------------
# Deltas (§16)
# ---------------------------------------------------------------------

class TestDeltas:
    def test_dialogue_success(self):
        assert reputation.DIALOGUE_SUCCESS == 1

    def test_dialogue_neutral(self):
        assert reputation.DIALOGUE_NEUTRAL == 0

    def test_dialogue_fail(self):
        assert reputation.DIALOGUE_FAIL == -1

    def test_dialogue_anger(self):
        assert reputation.DIALOGUE_ANGER == -2

    def test_quest_ok(self):
        assert reputation.QUEST_DELTA_OK == 1

    def test_quest_failed(self):
        assert reputation.QUEST_DELTA_FAIL == -2

    def test_resident_killed_overall(self):
        assert reputation.KILL_OVERALL == -5

    def test_resident_killed_role(self):
        assert reputation.KILL_ROLE == -10

    def test_dialogue_delta_maps_outcomes(self):
        from burt.npc import Outcome
        assert reputation.dialogue_delta(Outcome.SUCCESS, angry=False) == 1
        assert reputation.dialogue_delta(Outcome.NEUTRAL, angry=False) == 0
        assert reputation.dialogue_delta(Outcome.FAIL, angry=False) == -1
        assert reputation.dialogue_delta(Outcome.FAIL, angry=True) == -2


# ---------------------------------------------------------------------
# Effects (§16)
# ---------------------------------------------------------------------

class TestEffects:
    @pytest.mark.parametrize("rep,expected", [(5, 0.9), (10, 0.9)])
    def test_high_reputation_is_cheaper(self, rep, expected):
        assert reputation.price_modifier(rep) == expected

    @pytest.mark.parametrize("rep,expected", [(-5, 1.1), (-10, 1.1)])
    def test_low_reputation_is_dearer(self, rep, expected):
        assert reputation.price_modifier(rep) == expected

    @pytest.mark.parametrize("rep", [-4, -1, 0, 1, 4])
    def test_neutral_is_base_price(self, rep):
        assert reputation.price_modifier(rep) == 1.0

    def test_quests_blocked_at_minus_five(self):
        assert reputation.can_give_quests(-5) is False

    def test_quests_allowed_above_minus_five(self):
        assert reputation.can_give_quests(-4) is True


# ---------------------------------------------------------------------
# One change per dialogue (§16)
# ---------------------------------------------------------------------

class TestOnePerDialogue:
    def test_first_application_goes_through(self):
        st = make_state()
        assert reputation.apply_dialog_rep(st, "elder", 1) is True
        assert reputation.get(st, "elder") == 1

    def test_second_application_ignored(self):
        st = make_state()
        reputation.apply_dialog_rep(st, "elder", 1)
        assert reputation.apply_dialog_rep(st, "elder", 1) is False
        assert reputation.get(st, "elder") == 1

    def test_different_role_can_change(self):
        st = make_state()
        reputation.apply_dialog_rep(st, "elder", 1)
        assert reputation.apply_dialog_rep(st, "guard", 1) is True
        assert reputation.get(st, "guard") == 1
