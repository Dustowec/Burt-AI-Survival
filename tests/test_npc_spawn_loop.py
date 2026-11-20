"""Menu + spawn integration — spec §26, §32.

Checks that NPCs spawned on node entry show up in the exploring menu
together with exits and search (not instead of them), and that the
TZ-9 encounter flow still wins when the enemy is revealed.
"""
from __future__ import annotations

import pytest

from burt import loop
from burt.loop import Action, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


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
            "location": {"name": "Village", "exits": ["north", "south"]},
        },
        "hidden": {
            "step": 5, "day": 1,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [],
            "npcs_by_node": {},
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": "n2", "east": None,
                                    "south": "n3", "west": None}},
                "n2": {"type": "village", "entered": True,
                       "exits": {"north": None, "east": None,
                                 "south": "start", "west": None}},
                "n3": {"type": "temple", "entered": True,
                       "exits": {"north": "start", "east": None,
                                 "south": None, "west": None}},
            },
            "pending_encounter": None,
            "encounter_revealed": False,
            "last_action": None,
            "same_action_count": 0,
            "combat": None,
        },
    }
    st["hidden"].update(hidden_over)
    return st


# ---------------------------------------------------------------------
# Exploring menu with NPCs (§26, §32)
# ---------------------------------------------------------------------

class TestExploringMenuWithNpcs:
    def test_npcs_listed(self, engine):
        st = make_state(npcs_here=["elder", "blacksmith"])
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert "talk_to_elder" in keys
        assert "talk_to_blacksmith" in keys

    def test_exits_still_present(self, engine):
        st = make_state(npcs_here=["elder"])
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert "go_north" in keys
        assert "go_south" in keys

    def test_search_still_present(self, engine):
        st = make_state(npcs_here=["elder"])
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert "search" in keys

    def test_osmotret_present(self, engine):
        st = make_state(npcs_here=["elder"])
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert "osmotret" in keys

    def test_no_duplicate_keys(self, engine):
        st = make_state(npcs_here=["elder", "child"])
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert len(keys) == len(set(keys))

    def test_no_npcs_no_talk(self, engine):
        st = make_state()
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert not any(k.startswith("talk_to_") for k in keys)



# ---------------------------------------------------------------------
# Revealed encounter wins (TZ-9)
# ---------------------------------------------------------------------

class TestRevealedEncounterWins:
    def test_revealed_hides_talk(self, engine):
        st = make_state(
            npcs_here=["elder"],
            encounter_revealed=True,
            pending_encounter={"node_id": "start", "enemy_keys": ["wolf"]},
        )
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        keys = [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
        assert not any(k.startswith("talk_to_") for k in keys)
        assert any(k.startswith("attack_") for k in keys)


# ---------------------------------------------------------------------
# Spawn on entry fills npcs_here through execute_action
# ---------------------------------------------------------------------

class TestSpawnThroughMovement:
    def test_go_north_to_village_spawns_npcs(self):
        st = make_state()
        execute_action(Action("go_north", "Go north"), st, rng=_rng_seq(4, 3, 5, 1))
        assert st["hidden"]["current_node_id"] == "n2"
        assert st["hidden"]["npcs_here"]
        assert all(r in loop.npc_spawn.ROLE_SPAWN["village"]
                   for r in st["hidden"]["npcs_here"])

    def test_go_north_caches_by_node(self):
        st = make_state()
        execute_action(Action("go_north", "Go north"), st, rng=_rng_seq(4, 3, 5, 1))
        assert "n2" in st["hidden"]["npcs_by_node"]

    def test_moving_to_temple_gives_cleric(self):
        st = make_state()
        execute_action(Action("go_south", "Go south"), st, rng=_rng_seq(4, 2, 5))
        assert st["hidden"]["npcs_here"] == ["cleric"]

    def test_leaving_village_clears_npcs(self):
        st = make_state()
        execute_action(Action("go_north", "Go north"), st, rng=_rng_seq(4, 3, 5, 1))
        assert st["hidden"]["npcs_here"]
        st["hidden"]["location_graph"]["n2"]["exits"]["north"] = "n4"
        st["hidden"]["location_graph"]["n4"] = {
            "type": "field", "entered": True,
            "exits": {"south": "n2", "north": None, "east": None, "west": None},
        }
        st["visible"]["location"]["exits"] = ["south"]
        execute_action(Action("go_north", "Go north"), st, rng=_rng_seq(4, 2, 5))
        assert st["hidden"]["npcs_here"] == []

    def test_reentry_keeps_same_npcs(self):
        st = make_state()
        execute_action(Action("go_north", "Go north"), st,
                       rng=_rng_seq(6, 3, 5, 2, 1, 4))
        first = list(st["hidden"]["npcs_here"])
        # Walk away (movement roll 4 = normal) and come back.
        execute_action(Action("go_south", "Go south"), st, rng=_rng_seq(4, 2))
        execute_action(Action("go_north", "Go north"), st, rng=_rng_seq(4, 1, 4))
        assert st["hidden"]["current_node_id"] == "n2"
        assert st["hidden"]["npcs_here"] == first


# ---------------------------------------------------------------------
# talk_to still enters dialog (§26)
# ---------------------------------------------------------------------

class TestTalkStillWorks:
    def test_talk_enters_dialog(self, engine):
        st = make_state(npcs_here=["elder"])
        execute_action(Action("talk_to_elder", "Talk to elder"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        assert st["hidden"]["current_mode"] == "dialog"
        assert st["hidden"]["dialog_state"]["role_key"] == "elder"
