"""§34 crime through the loop: dialog_attack, menus, punishment, block."""
from __future__ import annotations

import pytest

import main
from burt import faith
from burt import state_io
from burt.loop import Action, _arrive_at_node, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


def _rng(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state() -> dict:
    return main.make_new_state(life=1)


def open_dialog(st, role, engine, rng=None):
    st["hidden"]["npcs_here"] = [role]
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=rng or _rng(4, 4), dialogue_engine=engine,
    )


class TestMurder:
    def test_kill_resident_from_dialog(self, engine):
        st = make_state()
        st["hidden"]["npcs_by_node"] = {"start": ["merchant"]}
        st["hidden"]["quests_raw"].append({
            "id": "elder_1", "giver_role": "elder", "giver_node": "start",
            "status": "active", "type": "deliver", "progress": 0,
            "required": 0, "deliver_items": None, "chain": None,
        })

        open_dialog(st, "merchant", engine)
        result = execute_action(
            Action("dialog_attack", "Attack (kill)"), st,
            rng=_rng(4, 4), dialogue_engine=engine,
        )

        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["dialog_state"] is None
        assert st["hidden"]["step"] == 1  # the murder is one action
        assert faith.get_status(st) == faith.STATUS_KILLER
        assert st["visible"]["faith"] == "killer"
        assert "merchant" not in st["hidden"]["npcs_here"]
        assert "merchant" not in st["hidden"]["npcs_by_node"]["start"]
        assert st["hidden"]["quests_raw"][0]["status"] == "failed"
        assert st["hidden"]["reputation"]["merchant"] == -10
        assert st["hidden"]["reputation_overall"] == -5
        combined = "\n".join(result.events)
        assert "Faith: killer" in combined
        assert "work is lost" in combined

    def test_menu_after_crime_hides_residents(self, engine):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        st["hidden"]["npcs_here"] = [
            "merchant", "child", "guard", "cleric", "necromancer",
        ]
        keys = [a.key for a in build_menu(
            st["visible"], st, dialogue_engine=engine,
        )]
        assert "talk_to_merchant" not in keys
        assert "talk_to_child" not in keys
        assert "talk_to_guard" not in keys
        assert "talk_to_cleric" in keys
        assert "talk_to_necromancer" in keys

    def test_quest_giver_blocked_for_life(self):
        st = make_state()
        faith.on_resident_killed("elder", "elder", st)
        assert "elder" in st["hidden"]["killed_quest_givers"]
        assert st["hidden"]["role_quest_block"]["elder"] == -1
        from burt import quests
        assert quests.quest_can_give("elder", st) is False


class TestPunishment:
    def test_first_cleric_meeting_serves_wrath(self, engine):
        st = make_state()
        st["visible"]["level"] = 3
        st["visible"]["hp"] = 8
        st["hidden"]["hp_raw"] = 8
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)

        result = open_dialog(st, "cleric", engine)

        assert st["visible"]["hp"] == 5
        assert st["hidden"]["faith"]["punishment_pending"] is False
        assert any(
            "gods demand a price" in event.lower()
            for event in result.events
        )

    def test_punishment_can_kill(self, engine):
        st = make_state()
        st["visible"]["level"] = 10
        st["visible"]["hp"] = 5
        st["hidden"]["hp_raw"] = 5
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)

        result = open_dialog(st, "cleric", engine)

        assert result.game_over is True
        assert st["visible"]["hp"] == 0
        assert st["hidden"]["death_cause_override"] == "god_wrath"
        assert main._determine_death_cause(
            st, Action("talk_to_cleric", "Talk"),
        ) == "god_wrath"


class TestFlee:
    def test_child_flees_on_arrival(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        graph = {"n1": {"type": "village", "entered": True, "exits": {}}}
        st["hidden"]["location_graph"] = graph
        st["hidden"]["npcs_by_node"] = {
            "n1": ["child", "elder", "cleric"],
        }
        st["hidden"]["npcs_here"] = ["child", "elder", "cleric"]

        _loc, started = _arrive_at_node(
            "n1", graph, st["hidden"], st["visible"], _rng(4),
        )

        assert started is None
        assert "child" not in st["hidden"]["npcs_here"]
        assert "child" not in st["hidden"]["npcs_by_node"]["n1"]
        assert "elder" in st["hidden"]["npcs_here"]


class TestStateIo:
    def test_roundtrip_with_status(self, tmp_path):
        st = make_state()
        faith.set_status(st, faith.STATUS_PALADIN)
        main._sync_meta_from_hidden(st)
        path = tmp_path / "state.json"

        state_io.save_state(path, st)
        loaded = state_io.load_state(path)

        assert loaded["visible"]["faith"] == "paladin"
        assert loaded["hidden"]["faith"]["status"] == "paladin"

    def test_invalid_status_rejected(self, tmp_path):
        st = make_state()
        st["visible"]["faith"] = "prophet"
        with pytest.raises(ValueError):
            state_io.save_state(tmp_path / "state.json", st)
