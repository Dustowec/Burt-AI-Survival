"""Dialogue bonuses: human text only, real coins/food (new_bug §4)."""
from __future__ import annotations

import pytest

from burt import npc
from burt.loop import Action, bonus_text, execute_action
from burt.npc import DialogueEngine, load_replicas


ROLES = ("merchant", "elder", "veteran", "blacksmith", "guard",
         "fisherman", "tavernkeeper", "peasant", "child")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(coin: int = 50) -> dict:
    return {
        "meta": {"life": 1, "day": 1, "step": 5},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [], "inventory": [], "wallet": {"coin": coin},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
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
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0},
            "price_modifier": 1.0,
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "has_staff": False,
            "teacher_found": False,
            "trained_by": [],
            "skills_raw": [],
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


def open_dialog(st, role, engine):
    st["hidden"]["npcs_here"] = [role]
    execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=_rng_seq(4, 4), dialogue_engine=engine,
    )


def force_bonus(monkeypatch, bonus: dict) -> None:
    monkeypatch.setattr(
        npc.Session, "_pick_bonus", lambda self, category: bonus,
    )


class TestBonusText:
    @pytest.mark.parametrize("typ,expected", [
        ("bribe_accept", "The bribe succeeds."),
        ("bribe_discount", "The bribe succeeds, and the price softens."),
        ("trade_discount", "The trader lowers the price."),
        ("skill", "You feel your skill grow."),
        ("food", "They share some bread."),
        ("rumor", "They tell you a rumor."),
        ("extra_info", "They let slip something useful."),
        ("extra_goods", "They mention where to find better goods."),
        ("quest_discount", "They seem pleased with you."),
        ("quest_reward", "They seem pleased with you."),
        ("item", "They have nothing to spare right now."),
    ])
    def test_table(self, typ, expected):
        assert bonus_text({"type": typ}) == expected

    def test_coins_text(self):
        assert bonus_text({"type": "coins", "amount": 2}) == "You get 2 coins."

    def test_none(self):
        assert bonus_text(None) == ""

    def test_unknown_is_neutral(self):
        assert bonus_text({"type": "mystery"}) == npc.UNKNOWN_BONUS_TEXT


class TestMechanics:
    def test_coins_bonus_adds_coin_and_hides_key(self, engine, monkeypatch):
        force_bonus(monkeypatch, {"type": "coins", "amount": 2})
        st = make_state(coin=50)
        open_dialog(st, "merchant", engine)
        result = execute_action(
            Action("dialog_truth", "Truth"), st,
            rng=_rng_seq(5, 2), dialogue_engine=engine,
        )
        text = "\n".join(result.events)
        assert st["visible"]["wallet"]["coin"] == 52
        assert "You get 2 coins." in text
        assert "Bonus:" not in text

    def test_food_bonus_adds_bread_and_hides_key(self, engine, monkeypatch):
        force_bonus(monkeypatch, {"type": "food"})
        st = make_state()
        open_dialog(st, "merchant", engine)
        result = execute_action(
            Action("dialog_truth", "Truth"), st,
            rng=_rng_seq(5, 2), dialogue_engine=engine,
        )
        text = "\n".join(result.events)
        assert {"name": "bread", "count": 1} in st["visible"]["inventory"]
        assert "They share some bread." in text
        assert "Bonus:" not in text

    def test_bribe_accept_text_and_cost(self, engine, monkeypatch):
        force_bonus(monkeypatch, {"type": "bribe_accept"})
        st = make_state(coin=50)
        open_dialog(st, "merchant", engine)
        result = execute_action(
            Action("dialog_bribe", "Bribe"), st,
            rng=_rng_seq(5, 2), dialogue_engine=engine,
        )
        text = "\n".join(result.events)
        assert st["visible"]["wallet"]["coin"] == 46  # -4 coin
        assert "The bribe succeeds." in text
        assert "Bonus:" not in text

    def test_unknown_bonus_does_not_break(self, engine, monkeypatch):
        force_bonus(monkeypatch, {"type": "mystery"})
        st = make_state()
        open_dialog(st, "merchant", engine)
        result = execute_action(
            Action("dialog_truth", "Truth"), st,
            rng=_rng_seq(5, 2), dialogue_engine=engine,
        )
        text = "\n".join(result.events)
        assert npc.UNKNOWN_BONUS_TEXT in text
        assert "Bonus:" not in text
