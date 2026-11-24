"""Per-trader no-money block: 3 failed purchases cut the dialogue."""
from __future__ import annotations

import pytest

from burt import trade
from burt.loop import Action, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


ROLES = ("merchant", "elder", "blacksmith", "fisherman", "tavernkeeper",
         "guard", "peasant", "child", "mage")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(inventory=None, coin=50, step=5, day=1, **hidden_over):
    st = {
        "meta": {"life": 1, "day": day, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": f"{day} day",
            "effects": [],
            "inventory": list(inventory or []),
            "wallet": {"coin": coin},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
        },
        "hidden": {
            "step": step, "day": day,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [], "npcs_by_node": {},
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [], "quests_issued_today": {},
            "role_quest_block": {}, "rep_applied": {},
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0},
            "price_modifier": 1.0,
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "has_staff": False, "teacher_found": False,
            "trained_by": [], "skills_raw": [],
            "pending_encounter": None, "encounter_revealed": False,
            "last_action": None, "same_action_count": 0,
            "combat": None, "dialog_state": None,
            "trade_buy_failures": {},
            "trade_dialog_blocked_until": {},
            "trade_fail_day": day,
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": None, "east": None,
                                    "south": None, "west": None}},
            },
        },
    }
    st["hidden"].update(hidden_over)
    return st


def open_dialog(st, role, engine, rng=None):
    st["hidden"]["npcs_here"] = [role]
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=rng or _rng_seq(4, 4), dialogue_engine=engine,
    )


def open_shop(st, engine, role="merchant", rng=None):
    open_dialog(st, role, engine)
    return execute_action(
        Action("dialog_trade", "Trade"), st,
        rng=rng or _rng_seq(4, 4), dialogue_engine=engine,
    )


def menu_keys(st, engine):
    return [a.key for a in build_menu(
        st["visible"], st, dialogue_engine=engine,
    )]


class TestTradeNoMoneyBlock:
    def test_third_failed_buy_breaks_dialog(self, engine):
        st = make_state(coin=0)
        open_shop(st, engine)
        step_before = st["hidden"]["step"]

        first = execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert first.events[0].startswith("Error:")
        assert st["hidden"]["current_mode"] == "dialog"

        second = execute_action(Action("dialog_buy_fish", "Buy fish"), st)
        assert second.events[0].startswith("Error:")
        assert st["hidden"]["current_mode"] == "dialog"

        third = execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert not third.events[0].startswith("Error:")
        assert third.events[0] == trade.TRADE_NO_MONEY_TEXT
        assert third.inject == trade.TRADE_NO_MONEY_TEXT
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["dialog_state"] is None
        assert st["hidden"]["step"] == step_before + 1
        assert st["hidden"]["trade_buy_failures"]["merchant"] == 3
        assert st["hidden"]["trade_dialog_blocked_until"]["merchant"] == 2

    def test_successful_purchase_does_not_reset_counter(self, engine):
        st = make_state(coin=2)
        open_shop(st, engine)

        execute_action(Action("dialog_buy_staff", "Buy staff"), st)  # fail 1
        execute_action(Action("dialog_buy_bread", "Buy bread"), st)  # success
        assert st["visible"]["wallet"]["coin"] == 0

        execute_action(Action("dialog_buy_fish", "Buy fish"), st)    # fail 2
        assert st["hidden"]["current_mode"] == "dialog"

        result = execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert result.events[0] == trade.TRADE_NO_MONEY_TEXT
        assert st["hidden"]["current_mode"] == "exploring"

    def test_different_items_accumulate(self, engine):
        st = make_state(coin=0)
        open_shop(st, engine)
        execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        execute_action(Action("dialog_buy_fish", "Buy fish"), st)
        result = execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert result.events[0] == trade.TRADE_NO_MONEY_TEXT

    def test_reopening_shop_same_day_does_not_reset(self, engine):
        st = make_state(coin=0)
        open_shop(st, engine)
        execute_action(Action("dialog_buy_bread", "Buy bread"), st)

        execute_action(Action("dialog_trade_close", "Done"), st)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_buy_fish", "Buy fish"), st)

        execute_action(Action("dialog_trade_close", "Done"), st)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        result = execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert result.events[0] == trade.TRADE_NO_MONEY_TEXT
        assert st["hidden"]["trade_buy_failures"]["merchant"] == 3



class TestTradeBlockScope:
    def _block_merchant(self, engine):
        st = make_state(coin=0)
        open_shop(st, engine)
        for item in ("bread", "fish", "bread"):
            execute_action(Action(f"dialog_buy_{item}", f"Buy {item}"), st)
        assert st["hidden"]["current_mode"] == "exploring"
        return st

    def test_blocked_trader_hidden_from_menu(self, engine):
        st = self._block_merchant(engine)
        st["hidden"]["npcs_here"] = ["merchant"]
        assert "talk_to_merchant" not in menu_keys(st, engine)

    def test_blocked_trader_cannot_open_dialog(self, engine):
        st = self._block_merchant(engine)
        st["hidden"]["npcs_here"] = ["merchant"]
        result = execute_action(
            Action("talk_to_merchant", "Talk to merchant"), st,
            rng=_rng_seq(4, 4), dialogue_engine=engine,
        )
        assert result.events[0].startswith("Error:")
        assert "will not talk to you today" in result.events[0]
        assert st["hidden"]["current_mode"] == "exploring"

    def test_other_trader_is_not_blocked(self, engine):
        st = self._block_merchant(engine)
        st["hidden"]["npcs_here"] = ["elder"]
        assert "talk_to_elder" in menu_keys(st, engine)
        result = open_dialog(st, "elder", engine)
        assert not result.events[0].startswith("Error:")
        assert st["hidden"]["current_mode"] == "dialog"

    def test_new_day_clears_block_and_counter(self, engine):
        st = self._block_merchant(engine)
        st["hidden"]["day"] = 2
        st["visible"]["date"] = "2 day"
        st["hidden"]["npcs_here"] = ["merchant"]

        assert "talk_to_merchant" in menu_keys(st, engine)
        result = open_dialog(st, "merchant", engine)
        assert not result.events[0].startswith("Error:")

        # The next failed purchase starts a fresh counter.
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert st["hidden"]["trade_buy_failures"]["merchant"] == 1
        assert st["hidden"]["current_mode"] == "dialog"


class TestTradeBlockExclusions:
    def test_item_not_sold_does_not_count(self, engine):
        st = make_state(coin=0)
        open_shop(st, engine, role="elder")
        result = execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert result.events[0].startswith("Error:")
        assert st["hidden"]["trade_buy_failures"] == {}

    def test_paid_room_does_not_count(self, engine):
        st = make_state(coin=0, has_room_tonight=True)
        open_shop(st, engine, role="tavernkeeper")
        result = execute_action(
            Action("dialog_buy_tavern_room", "Buy room"), st,
        )
        assert result.events[0].startswith("Error:")
        assert st["hidden"]["trade_buy_failures"] == {}

    def test_sell_does_not_count(self, engine):
        st = make_state(coin=0, inventory=[{"name": "pelt", "count": 1}])
        open_shop(st, engine)
        execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        assert st["hidden"]["trade_buy_failures"] == {}
        assert st["visible"]["wallet"]["coin"] > 0

