"""Trade wired into the loop — spec §35, §19, §16, §22.

Covers: the shop sub-mode inside a dialogue, the buy/sell lists per role,
price composition (location x reputation x trade bonus), the tavern room,
selling loot and the two-staves road to a real staff (§9).
"""
from __future__ import annotations

import pytest

from burt import reputation, trade
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


def make_state(inventory=None, coin=50, step=5, **hidden_over):
    st = {
        "meta": {"life": 1, "day": 1, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [],
            "inventory": list(inventory or []),
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
            # neutral location modifier: no die is rolled for prices
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
    st["hidden"].update(hidden_over)
    return st


def open_dialog(st, role, rng=None, engine=None):
    """talk_to_<role> from the exploring menu."""
    st["hidden"]["npcs_here"] = [role]
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=rng or _rng_seq(4, 4),
        dialogue_engine=engine,
    )


def open_shop(st, engine, rng=None):
    """Enter the dialogue, then the trade category."""
    open_dialog(st, "merchant", rng=_rng_seq(4, 4), engine=engine)
    return execute_action(
        Action("dialog_trade", "Trade"), st,
        rng=rng or _rng_seq(4, 4), dialogue_engine=engine,
    )


def menu_keys(st, engine):
    return [a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)]
# ---------------------------------------------------------------------
# Menu wiring (§26, §35)
# ---------------------------------------------------------------------

class TestShopMenu:
    @pytest.mark.parametrize("role", ["merchant", "elder", "blacksmith",
                                      "fisherman", "tavernkeeper"])
    def test_trade_option_for_trade_roles(self, engine, role):
        st = make_state()
        open_dialog(st, role, engine=engine)
        assert "dialog_trade" in menu_keys(st, engine)

    def test_no_trade_for_child(self, engine):
        st = make_state()
        open_dialog(st, "child", engine=engine)
        assert "dialog_trade" not in menu_keys(st, engine)

    def test_trade_opens_shop_menu(self, engine):
        st = make_state()
        open_shop(st, engine)
        keys = menu_keys(st, engine)
        assert "dialog_buy_bread" in keys
        assert "dialog_trade_close" in keys

    def test_shop_hides_topics(self, engine):
        st = make_state()
        open_shop(st, engine)
        keys = menu_keys(st, engine)
        assert "dialog_truth" not in keys
        assert "dialog_quest" not in keys

    def test_close_returns_to_topics(self, engine):
        st = make_state()
        open_shop(st, engine)
        execute_action(Action("dialog_trade_close", "Done"), st, rng=_rng_seq(4))
        keys = menu_keys(st, engine)
        assert "dialog_trade" in keys
        assert not any(k.startswith("dialog_buy_") for k in keys)

    def test_elder_sells_bedroll_and_waterskin(self, engine):
        st = make_state()
        open_dialog(st, "elder", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        keys = menu_keys(st, engine)
        assert "dialog_buy_bedroll" in keys
        assert "dialog_buy_waterskin" in keys
        assert "dialog_buy_staff" not in keys

    def test_tavernkeeper_sells_room(self, engine):
        st = make_state()
        open_dialog(st, "tavernkeeper", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert "dialog_buy_tavern_room" in menu_keys(st, engine)

    def test_necromancer_sells_only_staff(self, engine):
        st = make_state()
        open_dialog(st, "necromancer", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        buys = [k for k in menu_keys(st, engine) if k.startswith("dialog_buy_")]
        assert buys == ["dialog_buy_staff"]

    def test_sell_list_only_priced_items(self, engine):
        st = make_state(inventory=[
            {"name": "pelt", "count": 1},
            {"name": "berries", "count": 2},
        ])
        open_shop(st, engine)
        keys = menu_keys(st, engine)
        assert "dialog_sell_pelt" in keys
        assert "dialog_sell_berries" not in keys

    def test_merchant_buys_every_priced_item(self, engine):
        st = make_state(inventory=[{"name": "dragon_scale", "count": 1}])
        open_shop(st, engine)
        assert "dialog_sell_dragon_scale" in menu_keys(st, engine)


# ---------------------------------------------------------------------
# Buying (§35)
# ---------------------------------------------------------------------

class TestBuy:
    def test_buy_spends_coin_and_adds_item(self, engine):
        st = make_state(coin=50)
        open_shop(st, engine)
        execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert st["visible"]["wallet"]["coin"] == 48
        assert {"name": "bread", "count": 1} in st["visible"]["inventory"]

    def test_buy_keeps_step(self, engine):
        # new_bug §1: a purchase inside the dialogue does not tick.
        st = make_state(step=5)
        open_shop(st, engine)
        before = st["hidden"]["step"]
        execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert st["hidden"]["step"] == before

    def test_buy_without_coin_is_refused(self, engine):
        st = make_state(coin=0)
        open_shop(st, engine)
        before = st["hidden"]["step"]
        result = execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert result.events[0].startswith("Error:")
        assert st["hidden"]["step"] == before
        assert "not enough coin" in result.events[0]

    def test_buy_item_the_role_does_not_sell(self, engine):
        st = make_state()
        open_dialog(st, "elder", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        result = execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert result.events[0].startswith("Error:")

    def test_buy_staff_sets_flag_and_inventory(self, engine):
        st = make_state(coin=200)
        open_dialog(st, "necromancer", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert st["hidden"]["has_staff"] is True
        assert {"name": "staff", "count": 1} in st["visible"]["inventory"]
        assert st["visible"]["wallet"]["coin"] == 100

    def test_location_modifier_makes_it_cheaper(self, engine):
        st = make_state(coin=200)
        st["hidden"]["prices_by_node"] = {"start": 0.75}
        st["hidden"]["price_modifier"] = 0.75
        open_shop(st, engine)
        execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert st["visible"]["wallet"]["coin"] == 200 - 75

    def test_bad_reputation_makes_it_dearer(self, engine):
        st = make_state(coin=200)
        st["hidden"]["reputation"]["merchant"] = -6
        open_shop(st, engine)
        execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert st["visible"]["wallet"]["coin"] == 200 - 110

    def test_good_reputation_makes_it_cheaper(self, engine):
        st = make_state(coin=200)
        st["hidden"]["reputation"]["merchant"] = 6
        open_shop(st, engine)
        execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert st["visible"]["wallet"]["coin"] == 200 - 90

    def test_trade_bonus_applies_in_the_shop(self, engine):
        st = make_state(coin=200)
        # roll 5 = success, second roll 2 -> trade_discount bonus
        open_dialog(st, "merchant", rng=_rng_seq(5, 2), engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(5, 2), dialogue_engine=engine)
        assert st["hidden"]["dialog_state"]["shop"]["bonus"] == pytest.approx(0.8)
        execute_action(Action("dialog_buy_staff", "Buy staff"), st)
        assert st["visible"]["wallet"]["coin"] == 200 - 80

    def test_buy_without_open_shop(self, engine):
        st = make_state()
        open_dialog(st, "merchant", engine=engine)
        result = execute_action(Action("dialog_buy_bread", "Buy bread"), st)
        assert result.events[0].startswith("Error:")


# ---------------------------------------------------------------------
# Tavern room (§5, §35)
# ---------------------------------------------------------------------

class TestTavernRoom:
    def test_room_is_one_shot_goods(self, engine):
        st = make_state(coin=50)
        open_dialog(st, "tavernkeeper", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_buy_tavern_room", "Room"), st)
        assert st["hidden"]["has_room_tonight"] is True
        assert st["visible"]["wallet"]["coin"] == 45
        assert all(i["name"] != "tavern_room" for i in st["visible"]["inventory"])

    def test_second_room_same_night_refused(self, engine):
        st = make_state(coin=50)
        open_dialog(st, "tavernkeeper", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_buy_tavern_room", "Room"), st)
        result = execute_action(Action("dialog_buy_tavern_room", "Room"), st)
        assert result.events[0].startswith("Error:")
        assert st["visible"]["wallet"]["coin"] == 45

    def test_room_is_reset_after_sleep(self, engine):
        st = make_state(coin=50, inventory=[{"name": "bedroll", "count": 1}])
        st["hidden"]["has_room_tonight"] = True
        st["hidden"]["step"] = 19
        execute_action(Action("sleep", "Sleep"), st)
        assert st["hidden"]["has_room_tonight"] is False
# ---------------------------------------------------------------------
# Selling (§35, §22 loot)
# ---------------------------------------------------------------------

class TestSell:
    def test_sell_adds_coin_and_removes_item(self, engine):
        st = make_state(inventory=[{"name": "pelt", "count": 1}])
        open_shop(st, engine)
        execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        assert st["visible"]["wallet"]["coin"] == 55
        assert st["visible"]["inventory"] == []

    def test_sell_decrements_stack(self, engine):
        st = make_state(inventory=[{"name": "fangs", "count": 2}])
        open_shop(st, engine)
        execute_action(Action("dialog_sell_fangs", "Sell fangs"), st)
        assert st["visible"]["inventory"] == [{"name": "fangs", "count": 1}]
        # §35: price is per single piece, not per pair
        assert st["visible"]["wallet"]["coin"] == 51

    def test_sell_bandage_is_free_but_taken(self, engine):
        st = make_state(inventory=[{"name": "bandage", "count": 1}])
        open_shop(st, engine)
        result = execute_action(Action("dialog_sell_bandage", "Sell"), st)
        assert st["visible"]["wallet"]["coin"] == 50
        assert st["visible"]["inventory"] == []
        assert any("worth nothing" in e for e in result.events)

    def test_sell_without_item_is_refused(self, engine):
        st = make_state()
        open_shop(st, engine)
        result = execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        assert result.events[0].startswith("Error:")

    def test_sell_location_modifier(self, engine):
        st = make_state(inventory=[{"name": "pelt", "count": 1}])
        st["hidden"]["prices_by_node"] = {"start": 0.75}
        st["hidden"]["price_modifier"] = 0.75
        open_shop(st, engine)
        execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        # pelt 10 -> half 5 -> 5 * 0.75 = 3.75 -> 3
        assert st["visible"]["wallet"]["coin"] == 53

    def test_sell_keeps_step(self, engine):
        # new_bug §1: a sale inside the dialogue does not tick.
        st = make_state(inventory=[{"name": "pelt", "count": 1}])
        open_shop(st, engine)
        before = st["hidden"]["step"]
        execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        assert st["hidden"]["step"] == before

    def test_sell_without_open_shop(self, engine):
        st = make_state(inventory=[{"name": "pelt", "count": 1}])
        open_dialog(st, "merchant", engine=engine)
        result = execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        assert result.events[0].startswith("Error:")


# ---------------------------------------------------------------------
# Trophy road to a staff (§9, agreement 2026-11-20)
# ---------------------------------------------------------------------

class TestTrophyStaff:
    def test_one_goblin_staff_is_not_enough(self, engine):
        st = make_state(inventory=[{"name": "goblin_staff", "count": 1}])
        open_dialog(st, "necromancer", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_sell_goblin_staff", "Sell"), st)
        assert st["hidden"]["magic"]["loot_sold"] == 1
        assert st["hidden"]["has_staff"] is False
        assert all(i["name"] != "staff" for i in st["visible"]["inventory"])

    def test_two_goblin_staves_give_a_real_staff(self, engine):
        st = make_state(inventory=[{"name": "goblin_staff", "count": 2}])
        open_dialog(st, "necromancer", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_sell_goblin_staff", "Sell"), st)
        assert st["hidden"]["has_staff"] is False
        result = execute_action(Action("dialog_sell_goblin_staff", "Sell"), st)
        assert st["hidden"]["magic"]["loot_sold"] == 2
        assert st["hidden"]["has_staff"] is True
        assert {"name": "staff", "count": 1} in st["visible"]["inventory"]
        assert any("hands you a staff" in e for e in result.events)

    def test_other_items_do_not_count(self, engine):
        st = make_state(inventory=[{"name": "goblin_staff", "count": 1},
                                   {"name": "pelt", "count": 1}])
        open_dialog(st, "necromancer", engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_sell_pelt", "Sell pelt"), st)
        assert st["hidden"]["magic"]["loot_sold"] == 0

    def test_loot_sold_only_to_necromancer(self, engine):
        st = make_state(inventory=[{"name": "goblin_staff", "count": 2}])
        open_shop(st, engine)
        execute_action(Action("dialog_sell_goblin_staff", "Sell"), st)
        execute_action(Action("dialog_sell_goblin_staff", "Sell"), st)
        assert st["hidden"]["magic"]["loot_sold"] == 0
        assert st["hidden"]["has_staff"] is False
# ---------------------------------------------------------------------
# Location modifier roll (§35: once per node)
# ---------------------------------------------------------------------

class TestLocationModifierRoll:
    def test_first_talk_to_a_trader_rolls_once(self, engine):
        st = make_state()
        st["hidden"]["prices_by_node"] = {}
        calls = []

        def rng():
            calls.append(1)
            return 1

        open_dialog(st, "merchant", rng=rng, engine=engine)
        assert len(calls) == 1
        assert st["hidden"]["prices_by_node"]["start"] == 1.25
        assert st["hidden"]["price_modifier"] == 1.25

    def test_second_talk_does_not_reroll(self, engine):
        st = make_state()
        st["hidden"]["prices_by_node"] = {}
        calls = []

        def rng():
            calls.append(1)
            return 6

        open_dialog(st, "merchant", rng=rng, engine=engine)
        execute_action(Action("dialog_exit", "Leave"), st)
        open_dialog(st, "merchant", rng=rng, engine=engine)
        assert len(calls) == 1
        assert st["hidden"]["prices_by_node"]["start"] == 0.75

    def test_non_trader_rolls_nothing(self, engine):
        st = make_state()
        st["hidden"]["prices_by_node"] = {}

        def rng():
            raise AssertionError("guards do not trade")

        open_dialog(st, "guard", rng=rng, engine=engine)
        assert st["hidden"]["prices_by_node"] == {}