"""Quest progress hooks — spec §18, §36.

Progress sources:
- kill:   enemy killed after the quest was accepted
- visit:  entering the target location
- talk:   a dialogue with the target role happened
- help:   another quest of the target role was completed
- deliver: items are in the inventory at hand-in time
"""
from __future__ import annotations

import pytest

from burt import quests


ROLES = ("elder", "blacksmith", "merchant", "guard",
         "fisherman", "veteran", "tavernkeeper")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


def make_state(day=1, node="start"):
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
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [],
            "quests_issued_today": {},
            "role_quest_block": {},
        },
    }


def give(st, quest_id, role):
    ok, _ = quests.quest_give(quest_id, role, st)
    assert ok, quest_id
    return quests.quest_get_active(quest_id, st)


def progress_of(st, quest_id) -> int:
    for d in st["hidden"]["quests_raw"]:
        if d["id"] == quest_id:
            return d["progress"]
    return -1


# ---------------------------------------------------------------------
# kill (§36)
# ---------------------------------------------------------------------

class TestKillHook:
    def test_kill_increments_matching_quest(self):
        st = make_state()
        give(st, "elder_2", "elder")           # kill 3 goblins
        quests.on_enemy_killed("goblin", st)
        assert progress_of(st, "elder_2") == 1

    def test_kill_other_enemy_ignored(self):
        st = make_state()
        give(st, "elder_2", "elder")
        quests.on_enemy_killed("wolf", st)
        assert progress_of(st, "elder_2") == 0

    def test_kill_does_not_exceed_required(self):
        st = make_state()
        give(st, "elder_2", "elder")           # required 3
        for _ in range(6):
            quests.on_enemy_killed("goblin", st)
        assert progress_of(st, "elder_2") == 3

    def test_kill_with_no_quests_is_safe(self):
        st = make_state()
        assert quests.on_enemy_killed("goblin", st) == []

    def test_kill_reports_ready_quests(self):
        st = make_state()
        give(st, "fisherman_3", "fisherman")   # kill 2 wolves
        quests.on_enemy_killed("wolf", st)
        ready = quests.on_enemy_killed("wolf", st)
        assert "fisherman_3" in ready


# ---------------------------------------------------------------------
# visit (§36)
# ---------------------------------------------------------------------

class TestVisitHook:
    def test_visit_completes_target_quest(self):
        st = make_state()
        give(st, "elder_4", "elder")           # visit river
        quests.on_enter_location("river", st)
        assert progress_of(st, "elder_4") == 1

    def test_visit_other_location_ignored(self):
        st = make_state()
        give(st, "elder_4", "elder")
        quests.on_enter_location("forest", st)
        assert progress_of(st, "elder_4") == 0

    def test_visit_without_quest_is_safe(self):
        st = make_state()
        assert quests.on_enter_location("river", st) == []


# ---------------------------------------------------------------------
# talk (§36)
# ---------------------------------------------------------------------

class TestTalkHook:
    def test_talk_with_target_completes(self):
        st = make_state()
        give(st, "elder_3", "elder")           # talk blacksmith
        quests.on_talk("blacksmith", st)
        assert progress_of(st, "elder_3") == 1

    def test_talk_with_other_role_ignored(self):
        st = make_state()
        give(st, "elder_3", "elder")
        quests.on_talk("guard", st)
        assert progress_of(st, "elder_3") == 0


# ---------------------------------------------------------------------
# help (§36)
# ---------------------------------------------------------------------

class TestHelpHook:
    def test_help_counts_completed_quest_of_role(self):
        st = make_state()
        give(st, "veteran_3", "veteran")       # help blacksmith
        assert quests.on_quest_completed("blacksmith", st) == ["veteran_3"]

    def test_help_ignores_other_role(self):
        st = make_state()
        give(st, "veteran_3", "veteran")
        assert quests.on_quest_completed("guard", st) == []


# ---------------------------------------------------------------------
# deliver inventory check (§18, §36)
# ---------------------------------------------------------------------

class TestDeliverCheck:
    def test_deliver_ready_when_items_in_inventory(self):
        st = make_state()
        give(st, "elder_1", "elder")           # 5 fangs
        st["visible"]["inventory"] = [{"name": "fangs", "count": 5}]
        assert quests.deliver_ready("elder_1", st) is True

    def test_deliver_not_ready_with_fewer_items(self):
        st = make_state()
        give(st, "elder_1", "elder")
        st["visible"]["inventory"] = [{"name": "fangs", "count": 4}]
        assert quests.deliver_ready("elder_1", st) is False

    def test_deliver_not_ready_without_items(self):
        st = make_state()
        give(st, "elder_1", "elder")
        assert quests.deliver_ready("elder_1", st) is False

    def test_deliver_progress_text(self):
        st = make_state()
        give(st, "elder_1", "elder")
        st["visible"]["inventory"] = [{"name": "fangs", "count": 2}]
        assert quests.deliver_progress("elder_1", st) == (2, 5)
