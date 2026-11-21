"""Faith chains through the loop — §33: K1-K2-K3, donation, deception."""
from __future__ import annotations

import pytest

import main
from burt import faith
from burt.loop import Action, execute_action
from burt.npc import DialogueEngine, load_replicas


def _rng(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(coin: int = 50) -> dict:
    st = main.make_new_state(life=1)
    st["visible"]["wallet"]["coin"] = coin
    return st


def open_dialog(st, role, engine, rng=None):
    st["hidden"]["npcs_here"] = [role]
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=rng or _rng(4, 4), dialogue_engine=engine,
    )


def act(st, key, engine, rng=None):
    return execute_action(
        Action(key, key), st, rng=rng or _rng(4, 4),
        dialogue_engine=engine,
    )


def active_ids(st) -> list[str]:
    return [d["id"] for d in st["hidden"]["quests_raw"]
            if d["status"] == "active"]


def set_progress(st, quest_id, value):
    for d in st["hidden"]["quests_raw"]:
        if d["id"] == quest_id and d["status"] == "active":
            d["progress"] = value


class TestChainIssuing:
    def test_cleric_gives_pala_1(self, engine):
        st = make_state()
        open_dialog(st, "cleric", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["pala_1"]
        assert st["hidden"]["faith"]["chain"] == faith.CHAIN_PALADIN

    def test_necromancer_gives_heretic_1(self, engine):
        st = make_state()
        open_dialog(st, "necromancer", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["heretic_1"]
        assert st["hidden"]["faith"]["chain"] == faith.CHAIN_HERETIC

    def test_killer_gets_k3_only(self, engine):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        open_dialog(st, "necromancer", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["heretic_3"]

    def test_paladin_gets_no_work(self, engine):
        st = make_state()
        faith.set_status(st, faith.STATUS_PALADIN)
        open_dialog(st, "cleric", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == []


class TestPaladinChain:
    def test_full_chain_to_paladin(self, engine):
        st = make_state(coin=40)
        st["visible"]["inventory"] = [
            {"name": "goblin_dagger", "count": 20},
            {"name": "goblin_staff", "count": 2},
            {"name": "fangs", "count": 5},
        ]

        # K1: issue and hand in at the cleric.
        open_dialog(st, "cleric", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["pala_2"]
        act(st, "dialog_exit", engine)

        # K2: one real role quest through the loop counts +1.
        open_dialog(st, "elder", engine)
        act(st, "dialog_quest", engine, _rng(1, 3, 4, 4))
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        pala2 = next(
            d for d in st["hidden"]["quests_raw"] if d["id"] == "pala_2"
        )
        assert pala2["progress"] == 1
        act(st, "dialog_exit", engine)

        # Fill the counter and hand K2 in at the cleric.
        set_progress(st, "pala_2", 5)
        open_dialog(st, "cleric", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["pala_3"]

        # K3: donate all coins at the temple.
        assert faith.donate_available(st, "cleric") is True
        act(st, "dialog_donate", engine)
        assert st["visible"]["wallet"]["coin"] == 0
        assert faith.get_status(st) == faith.STATUS_PALADIN
        assert active_ids(st) == []


class TestHereticChain:
    def test_full_chain_to_heretic(self, engine):
        st = make_state(coin=25)
        st["visible"]["inventory"] = [
            {"name": "goblin_dagger", "count": 10},
        ]

        # K1: issue and hand in at the necromancer.
        open_dialog(st, "necromancer", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["heretic_2"]
        act(st, "dialog_exit", engine)

        # K2: deceive three NPCs (first roll >= 3).
        for role in ("merchant", "blacksmith", "elder"):
            open_dialog(st, role, engine)
            act(st, "dialog_lie", engine, _rng(3, 4))
            act(st, "dialog_exit", engine)
        h2 = next(
            d for d in st["hidden"]["quests_raw"] if d["id"] == "heretic_2"
        )
        assert h2["progress"] == 3

        # Hand K2 in -> K3.
        open_dialog(st, "necromancer", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active_ids(st) == ["heretic_3"]
        act(st, "dialog_exit", engine)

        # K3: no donation before the insult.
        open_dialog(st, "cleric", engine)
        assert faith.donate_available(st, "cleric") is False
        res = act(st, "dialog_donate", engine)
        assert st["visible"]["wallet"]["coin"] == 25
        assert any("Error" in event for event in res.events)

        # K3 step 1: the insult; step 2: the donation.
        act(st, "dialog_threat", engine, _rng(5, 4))
        assert st["hidden"]["faith"]["k3_insulted"] is True
        assert faith.donate_available(st, "cleric") is True
        act(st, "dialog_donate", engine)
        assert st["visible"]["wallet"]["coin"] == 0
        h3 = next(
            d for d in st["hidden"]["quests_raw"] if d["id"] == "heretic_3"
        )
        assert h3["progress"] == 2
        act(st, "dialog_exit", engine)

        # Hand K3 in at the necromancer: heretic.
        open_dialog(st, "necromancer", engine)
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert faith.get_status(st) == faith.STATUS_HERETIC
        assert active_ids(st) == []

    def test_failed_deception_does_not_count(self, engine):
        st = make_state()
        st["hidden"]["quests_raw"].append({
            "id": "heretic_2", "giver_role": "necromancer",
            "giver_node": "start", "status": "active", "type": "deceive",
            "progress": 0, "required": 3, "deliver_items": None,
            "chain": "heretic", "chain_step": 2, "target": None,
        })
        open_dialog(st, "merchant", engine)
        act(st, "dialog_lie", engine, _rng(2, 4))
        assert st["hidden"]["quests_raw"][0]["progress"] == 0
        # §16 (the failed reply) -1 and §33 K2 (the failed deception) -1.
        assert st["hidden"]["reputation"]["merchant"] == -2
