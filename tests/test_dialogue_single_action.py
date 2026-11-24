"""Dialogue = one action (new_bug §1).

Entering, replies, quests, training, trade, buys, sells and closing the
shop never advance the step. Only dialog_exit ticks exactly once.
"""
from __future__ import annotations

import pytest

from burt.loop import Action, build_menu, execute_action
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


def make_state(step: int = 5, inventory=None, coin: int = 50) -> dict:
    return {
        "meta": {"life": 1, "day": 1, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [], "inventory": list(inventory or []),
            "wallet": {"coin": coin},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
        },
        "hidden": {
            "step": step, "day": 1,
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


def open_dialog(st, role, engine, rng=None):
    st["hidden"]["npcs_here"] = [role]
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=rng or _rng_seq(4, 4), dialogue_engine=engine,
    )


def step(st) -> int:
    return st["hidden"]["step"]


class TestEntering:
    def test_talk_to_does_not_tick(self, engine):
        st = make_state(step=5)
        open_dialog(st, "merchant", engine)
        assert step(st) == 5
        assert st["hidden"]["current_mode"] == "dialog"

    def test_dialog_menu_has_no_eat_food(self, engine):
        st = make_state(step=5, inventory=[{"name": "bread", "count": 2}])
        open_dialog(st, "merchant", engine)
        keys = [a.key for a in build_menu(
            st["visible"], st, dialogue_engine=engine,
        )]
        assert "eat_food" not in keys


class TestDialogActions:
    def test_replies_do_not_tick(self, engine):
        st = make_state(step=5)
        open_dialog(st, "merchant", engine)
        replies = ("dialog_polite", "dialog_truth")
        for i in range(5):
            execute_action(Action(replies[i % 2], replies[i % 2]), st,
                           rng=_rng_seq(4, 4), dialogue_engine=engine)
            assert step(st) == 5

    def test_quest_does_not_tick(self, engine):
        st = make_state(step=5)
        open_dialog(st, "elder", engine)
        execute_action(Action("dialog_quest", "Quest"), st,
                       rng=_rng_seq(2, 4, 4, 4), dialogue_engine=engine)
        assert step(st) == 5

    def test_train_does_not_tick(self, engine):
        st = make_state(step=5)
        open_dialog(st, "veteran", engine)
        execute_action(Action("dialog_train", "Train"), st,
                       rng=_rng_seq(4, 4, 2), dialogue_engine=engine)
        assert step(st) == 5

    def test_trade_and_close_shop_do_not_tick(self, engine):
        st = make_state(step=5)
        open_dialog(st, "merchant", engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert step(st) == 5
        assert st["hidden"]["dialog_state"]["shop"] is not None
        execute_action(Action("dialog_trade_close", "Done"), st)
        assert step(st) == 5
        assert st["hidden"]["dialog_state"]["shop"] is None

    def test_buy_and_sell_do_not_tick(self, engine):
        st = make_state(step=5, inventory=[{"name": "pelt", "count": 2}])
        open_dialog(st, "merchant", engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        for _ in range(3):
            execute_action(Action("dialog_buy_bread", "Buy bread"), st)
            assert step(st) == 5
        for _ in range(2):
            execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
            assert step(st) == 5


class TestWholeDialogue:
    def test_full_dialogue_advances_exactly_one_step(self, engine):
        st = make_state(step=5, inventory=[{"name": "pelt", "count": 2}])
        before = step(st)

        open_dialog(st, "merchant", engine)
        assert step(st) == before

        replies = ("dialog_polite", "dialog_truth")
        for i in range(5):
            execute_action(Action(replies[i % 2], replies[i % 2]), st,
                           rng=_rng_seq(4, 4), dialogue_engine=engine)
            assert step(st) == before

        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert step(st) == before

        for _ in range(3):
            execute_action(Action("dialog_buy_bread", "Buy bread"), st)
            assert step(st) == before
        for _ in range(2):
            execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
            assert step(st) == before

        execute_action(Action("dialog_trade_close", "Done"), st)
        assert step(st) == before

        execute_action(Action("dialog_exit", "Leave"), st)
        assert step(st) == before + 1
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["dialog_state"] is None



class TestAngerLock:
    def test_exit_reopens_after_two_replies(self, engine):
        """The anger lock must expire; otherwise the dialogue never ends."""
        st = make_state(step=5)
        open_dialog(st, "elder", engine)

        # roll=1, second_roll=1 -> fail_angry: -1 HP, exit locked.
        execute_action(Action("dialog_truth", "Truth"), st,
                       rng=_rng_seq(1, 1), dialogue_engine=engine)
        ds = st["hidden"]["dialog_state"]
        assert ds["is_angry"] is True
        assert step(st) == 5
        keys = [a.key for a in build_menu(
            st["visible"], st, dialogue_engine=engine,
        )]
        assert "dialog_exit" not in keys

        # Two replies advance the anger lock (turn 1 -> 3).
        for _ in range(2):
            execute_action(Action("dialog_polite", "Polite"), st,
                           rng=_rng_seq(4, 4), dialogue_engine=engine)
            assert step(st) == 5

        keys = [a.key for a in build_menu(
            st["visible"], st, dialogue_engine=engine,
        )]
        assert "dialog_exit" in keys
        assert st["hidden"]["dialog_state"]["is_angry"] is False

