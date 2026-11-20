"""Role quest templates — spec §36.

Every role that can give quests must have templates in
quests_templates.json, all referenced items / enemies / locations
must exist, and the deadline must be rolled 1d6 -> 3/5/7 days.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from burt import quests, trade, items, bestiary, world


TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "quests_templates.json"
TEMPLATES = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))

QUEST_ROLES = ("elder", "blacksmith", "merchant", "guard",
               "fisherman", "veteran", "tavernkeeper")


def _role_templates(role: str) -> list[dict]:
    return [t for t in TEMPLATES.values() if t.get("role") == role]


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


# ---------------------------------------------------------------------
# Template coverage (§36)
# ---------------------------------------------------------------------

class TestTemplateCoverage:
    @pytest.mark.parametrize("role", QUEST_ROLES)
    def test_role_has_three_quests(self, role):
        assert len(_role_templates(role)) >= 3, role

    def test_faith_chains_untouched(self):
        # §33 chains stay as they are; they are not role quests.
        for qid in ("pala_1", "pala_2", "pala_3",
                    "heretic_1", "heretic_2", "heretic_3"):
            assert qid in TEMPLATES
            assert "role" not in TEMPLATES[qid]

    def test_all_ids_unique(self):
        ids = [t["id"] for t in TEMPLATES.values()]
        assert len(ids) == len(set(ids))

    def test_every_template_has_id(self):
        for t in TEMPLATES.values():
            assert t.get("id")


# ---------------------------------------------------------------------
# Template validity
# ---------------------------------------------------------------------

class TestTemplateValidity:
    def test_quest_types_are_known(self):
        known = {"deliver", "kill", "visit", "talk", "help", "deceive", "chain"}
        for t in TEMPLATES.values():
            assert t["type"] in known, (t["id"], t["type"])

    def test_deliver_items_exist(self):
        pool = set(trade.BASE_PRICES) | set(trade.LOOT_PRICES) | set(items.ITEMS)
        for t in TEMPLATES.values():
            for req in t.get("deliver_items") or []:
                assert req["name"] in pool, (t["id"], req["name"])
                assert req["count"] > 0

    def test_kill_targets_exist(self):
        for t in TEMPLATES.values():
            if t["type"] == "kill":
                assert t["target"] in bestiary.ENEMIES, (t["id"], t["target"])

    def test_visit_targets_exist(self):
        for t in TEMPLATES.values():
            if t["type"] == "visit":
                assert t["target"] in world.LOCATION_TYPES, (t["id"], t["target"])

    def test_talk_targets_are_roles(self):
        known = set(quests.quest_roles()) if hasattr(quests, "quest_roles") else set(QUEST_ROLES)
        for t in TEMPLATES.values():
            if t["type"] == "talk":
                assert t["target"] in known, (t["id"], t["target"])

    def test_help_targets_are_roles(self):
        for t in TEMPLATES.values():
            if t["type"] == "help" and t.get("role"):
                assert t["target"] in QUEST_ROLES, (t["id"], t["target"])

    def test_required_is_positive(self):
        for t in TEMPLATES.values():
            if t["type"] in ("kill", "visit", "talk", "help", "deceive", "chain"):
                assert t["required"] >= 1, t["id"]


# ---------------------------------------------------------------------
# Deadline roll (§36)
# ---------------------------------------------------------------------

class TestDeadlineRoll:
    @pytest.mark.parametrize("roll,days", [(1, 3), (2, 3), (3, 5), (4, 5), (5, 7), (6, 7)])
    def test_mapping(self, roll, days):
        assert quests.roll_deadline(_rng_seq(roll)) == days

    def test_invalid_roll(self):
        with pytest.raises(ValueError):
            quests.roll_deadline(_rng_seq(0))


# ---------------------------------------------------------------------
# Picking a quest for a role (§36)
# ---------------------------------------------------------------------

def make_state(day=1, node="start", rep=None):
    return {
        "meta": {"life": 1, "day": day, "step": 0},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "wallet": {"coin": 50}, "inventory": [],
            "effects": [], "sleep_counter": 0, "date": f"{day} day",
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
        },
        "hidden": {
            "day": day, "step": 0,
            "current_node_id": node,
            "reputation": rep or {r: 0 for r in QUEST_ROLES},
            "quests_raw": [],
            "quests_issued_today": {},
            "role_quest_block": {},
        },
    }


class TestPickQuest:
    def test_pick_returns_template_of_role(self):
        st = make_state()
        qid = quests.pick_quest_for_role("elder", st, rng=_rng_seq(1))
        assert TEMPLATES[qid]["role"] == "elder"

    def test_pick_unknown_role(self):
        st = make_state()
        assert quests.pick_quest_for_role("child", st, rng=_rng_seq(1)) is None

    def test_pick_skips_active_role_quest(self):
        st = make_state()
        first = quests.pick_quest_for_role("elder", st, rng=_rng_seq(1))
        quests.quest_give(first, "elder", st)
        second = quests.pick_quest_for_role("elder", st, rng=_rng_seq(1))
        # Quest already active for this role -> nothing to give.
        assert quests.quest_can_give("elder", st) is False
        assert second is None

    def test_pick_rotates_with_roll(self):
        st = make_state()
        a = quests.pick_quest_for_role("merchant", st, rng=_rng_seq(1))
        b = quests.pick_quest_for_role("merchant", st, rng=_rng_seq(2))
        assert a != b

    def test_pick_is_deterministic(self):
        st = make_state()
        a = quests.pick_quest_for_role("guard", st, rng=_rng_seq(3))
        b = quests.pick_quest_for_role("guard", st, rng=_rng_seq(3))
        assert a == b


# ---------------------------------------------------------------------
# quest_state for the dialogue (§32, §36, §16)
# ---------------------------------------------------------------------

class TestQuestState:
    def test_available_when_can_give(self):
        st = make_state()
        assert quests.quest_state_for_role("elder", st) == "available"

    def test_in_progress_when_active(self):
        st = make_state()
        qid = quests.pick_quest_for_role("elder", st, rng=_rng_seq(1))
        quests.quest_give(qid, "elder", st)
        assert quests.quest_state_for_role("elder", st) == "in_progress"

    def test_none_for_role_without_quests(self):
        st = make_state()
        assert quests.quest_state_for_role("child", st) == "none"

    def test_none_when_reputation_too_low(self):
        st = make_state(rep={r: 0 for r in QUEST_ROLES} | {"elder": -6})
        assert quests.quest_state_for_role("elder", st) == "none"

    def test_available_at_reputation_minus_four(self):
        st = make_state(rep={r: 0 for r in QUEST_ROLES} | {"elder": -4})
        assert quests.quest_state_for_role("elder", st) == "available"

    def test_none_when_blocked(self):
        st = make_state()
        st["hidden"]["role_quest_block"] = {"elder": 99}
        assert quests.quest_state_for_role("elder", st) == "none"

