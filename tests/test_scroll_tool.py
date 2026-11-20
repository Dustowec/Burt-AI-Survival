"""Quest scroll tool — spec §18, §26.

The scroll is a free tool: it shows active quests as plain text and does
not advance the day counter. The quest giver stays hidden (§18): Burt
sees the text, the deadline and his own progress, never who asked, and
never where that NPC is.
"""
from __future__ import annotations

import pytest

from burt import quests
from burt.loop import Action, build_menu, execute_action


ROLES = ("elder", "blacksmith", "merchant", "guard",
         "fisherman", "veteran", "tavernkeeper")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


def make_state(day=1):
    return {
        "meta": {"life": 1, "day": day, "step": 3},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "wallet": {"coin": 50}, "inventory": [],
            "effects": [], "sleep_counter": 0, "date": f"{day} day",
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
        },
        "hidden": {
            "day": day, "step": 3,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [],
            "npcs_by_node": {},
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [],
            "quests_issued_today": {},
            "role_quest_block": {},
            "pending_encounter": None,
            "encounter_revealed": False,
            "last_action": None,
            "same_action_count": 0,
            "combat": None,
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": None, "east": None,
                                    "south": None, "west": None}},
            },
        },
    }


# ---------------------------------------------------------------------
# Menu (§26)
# ---------------------------------------------------------------------

class TestScrollInMenu:
    def test_scroll_is_offered(self):
        st = make_state()
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "scroll" in keys

    def test_scroll_is_free(self):
        st = make_state()
        action = next(a for a in build_menu(st["visible"], st) if a.key == "scroll")
        assert action.cost_free is True


# ---------------------------------------------------------------------
# Output (§18)
# ---------------------------------------------------------------------

class TestScrollOutput:
    def test_empty_scroll(self):
        st = make_state()
        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        text = "\n".join(result.events)
        assert "No open quests" in text

    def test_scroll_does_not_advance_step(self):
        st = make_state()
        before = st["hidden"]["step"]
        execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        assert st["hidden"]["step"] == before

    def test_scroll_lists_quest(self):
        st = make_state()
        quests.quest_give("elder_1", "elder", st)
        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        text = "\n".join(result.events)
        assert "Fangs of the Wolves" in text

    def test_scroll_hides_giver(self):
        st = make_state()
        quests.quest_give("elder_1", "elder", st)
        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        text = "\n".join(result.events)
        assert "elder" not in text
        assert "blacksmith" not in text

    def test_scroll_shows_deadline(self):
        st = make_state(day=3)
        quests.quest_give("elder_1", "elder", st)
        st["hidden"]["quests_raw"][0]["deadline_day"] = 8
        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        text = "\n".join(result.events)
        assert "5 days left" in text

    def test_scroll_shows_inventory_progress(self):
        st = make_state()
        quests.quest_give("elder_1", "elder", st)
        st["visible"]["inventory"] = [{"name": "fangs", "count": 2}]
        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        text = "\n".join(result.events)
        assert "2/5" in text

    def test_scroll_skips_completed(self):
        st = make_state()
        quests.quest_give("elder_1", "elder", st)
        st["hidden"]["quests_raw"][0]["status"] = "completed"
        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        assert "No open quests" in "\n".join(result.events)
