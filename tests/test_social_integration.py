"""Social layer end-to-end — spec §32, §36, §18, §16.

One flowing scenario: arrive in a village, meet an NPC, take a quest,
kill the target, report back, gain reputation.
"""
from __future__ import annotations

import pytest

from burt import quests, reputation
from burt.loop import Action, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


ROLES = ("elder", "blacksmith", "merchant", "guard",
         "fisherman", "veteran", "tavernkeeper")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(**hidden_over):
    st = {
        "meta": {"life": 1, "day": 1, "step": 5},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [], "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
            "location": {"name": "Crossroads", "exits": ["north"]},
        },
        "hidden": {
            "step": 5, "day": 1,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [],
            "npcs_by_node": {},
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [],
            "quests_issued_today": {},
            "role_quest_block": {},
            "rep_applied": {},
            "pending_encounter": None,
            "encounter_revealed": False,
            "last_action": None,
            "same_action_count": 0,
            "combat": None,
            "location_graph": {
                "start": {"type": "crossroads", "entered": True,
                          "exits": {"north": "v1", "east": None,
                                    "south": None, "west": None}},
                "v1": {"type": "village", "entered": False,
                       "exits": {"south": "start", "north": None,
                                 "east": None, "west": None}},
            },
        },
    }
    st["hidden"].update(hidden_over)
    return st


# ---------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------

class TestMenuWiring:
    def test_village_offers_talk_exits_search(self, engine):
        st = make_state(npcs_here=["elder"])
        keys = [a.key for a in build_menu(st["visible"], st,
                                          dialogue_engine=engine)]
        assert "talk_to_elder" in keys
        assert "search" in keys


# ---------------------------------------------------------------------
# Full loop
# ---------------------------------------------------------------------

class TestFullLoop:
    def test_dialog_issues_quest_with_deadline(self, engine):
        st = make_state(npcs_here=["elder"])
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        assert st["hidden"]["dialog_state"]["quest_state"] == "available"

        execute_action(Action("dialog_quest", "Quest"), st,
                       rng=_rng_seq(2, 4, 4, 4), dialogue_engine=engine)
        active = [q for q in st["hidden"]["quests_raw"] if q["status"] == "active"]
        assert len(active) == 1
        assert active[0]["giver_role"] == "elder"
        assert active[0]["deadline_day"] is not None
        assert st["hidden"]["dialog_state"]["quest_state"] == "in_progress"

    def test_kill_quest_ready_then_reported(self, engine):
        st = make_state(npcs_here=["elder"])
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        execute_action(Action("dialog_quest", "Quest"), st,
                       rng=_rng_seq(2, 4, 4, 4), dialogue_engine=engine)
        quest_id = [q["id"] for q in st["hidden"]["quests_raw"]
                    if q["status"] == "active"][0]

        # Turn it into a one-goblin kill quest and kill a goblin.
        for entry in st["hidden"]["quests_raw"]:
            if entry["id"] == quest_id:
                entry.update(type="kill", target="goblin",
                             required=1, progress=0)
        assert quest_id in quests.on_enemy_killed("goblin", st)

        before = reputation.get(st, "elder")
        execute_action(Action("dialog_exit", "Leave"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)

        # Come back and report: quest completes, reputation +1 (§16).
        st["hidden"]["npcs_here"] = ["elder"]
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        result = execute_action(Action("dialog_quest", "Quest"), st,
                                rng=_rng_seq(2, 4, 4, 4),
                                dialogue_engine=engine)
        assert "Quest complete" in "\n".join(result.events)
        assert reputation.get(st, "elder") == before + 1

    def test_scroll_lists_issued_quest(self, engine):
        st = make_state(npcs_here=["elder"])
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        execute_action(Action("dialog_quest", "Quest"), st,
                       rng=_rng_seq(2, 4, 4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_exit", "Leave"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)

        result = execute_action(Action("scroll", "Scroll"), st, rng=_rng_seq(4))
        text = "\n".join(result.events)
        assert "[SCROLL]" in text
        assert "elder" not in text          # giver stays hidden (§18)

    def test_low_reputation_blocks_quests(self, engine):
        st = make_state(npcs_here=["elder"])
        st["hidden"]["reputation"]["elder"] = -6
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        assert st["hidden"]["dialog_state"]["quest_state"] == "none"

    def test_dialog_reputation_changes_once(self, engine):
        st = make_state(npcs_here=["elder"])
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        for _ in range(3):
            execute_action(Action("dialog_polite", "Polite"), st,
                           rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert -1 <= reputation.get(st, "elder") <= 1

    def test_visit_quest_completes_on_arrival(self):
        st = make_state()
        qid = "merchant_3"                  # visit forest
        assert quests.quest_give(qid, "merchant", st)[0]
        st["hidden"]["location_graph"]["start"]["exits"]["north"] = "f1"
        st["hidden"]["location_graph"]["f1"] = {
            "type": "forest", "entered": True,
            "exits": {"south": "start", "north": None,
                      "east": None, "west": None},
        }
        execute_action(Action("go_north", "Go north"), st,
                       rng=_rng_seq(4, 2, 5))
        assert st["hidden"]["current_node_id"] == "f1"
        entry = next(q for q in st["hidden"]["quests_raw"] if q["id"] == qid)
        assert entry["progress"] >= entry["required"]

    def test_village_spawns_npcs_on_arrival(self):
        st = make_state()
        execute_action(Action("go_north", "Go north"), st,
                       rng=_rng_seq(5, 1, 2, 3, 4, 5))
        assert st["hidden"]["current_node_id"] == "v1"
        assert st["hidden"]["npcs_here"]
