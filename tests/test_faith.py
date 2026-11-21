"""Faith core — §33/§34: statuses, chains, crime, punishment."""
from __future__ import annotations

import pytest

from burt import faith
from burt import state as state_mod


ROLES = state_mod.ROLE_NAMES


def make_state(level: int = 1, coin: int = 50, day: int = 1) -> dict:
    return {
        "meta": {"life": 1, "day": day, "step": 0},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "level": level, "xp": 0, "eat": True, "sleep_counter": 0,
            "date": "1 day", "effects": [], "inventory": [],
            "wallet": {"coin": coin}, "skills_visible": [],
            "faith": faith.STATUS_NEUTRAL,
            "location": {"name": "Crossroads", "exits": ["north"]},
        },
        "hidden": {
            "step": 0, "day": day, "current_mode": "exploring",
            "current_node_id": "start", "npcs_here": [],
            "reputation": {role: 0 for role in ROLES},
            "reputation_overall": 0,
            "quests_raw": [], "role_quest_block": {},
            "killed_quest_givers": [],
            "faith": faith.new_state(),
        },
    }


def add_quest(st: dict, quest_id: str, chain: str, required: int,
              qtype: str = "chain", progress: int = 0) -> dict:
    entry = {
        "id": quest_id, "giver_role": "cleric", "giver_node": "start",
        "title": quest_id, "status": "active", "type": qtype,
        "progress": progress, "required": required,
        "deliver_items": None, "issued_day": 1, "deadline_day": None,
        "chain": chain, "chain_step": 1, "target": None,
    }
    st["hidden"]["quests_raw"].append(entry)
    return entry


class TestStatuses:
    def test_default_neutral(self):
        st = make_state()
        assert faith.get_status(st) == faith.STATUS_NEUTRAL
        assert faith.status_line(st) is None

    def test_set_paladin_mirrors_visible(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_PALADIN)
        assert st["hidden"]["faith"]["status"] == "paladin"
        assert st["visible"]["faith"] == "paladin"
        assert faith.status_line(st) == "Faith: paladin"

    def test_killer_from_kept(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_HERETIC)
        assert faith.get_killer_from(st) == "heretic"
        faith.set_status(st, faith.STATUS_PALADIN)
        assert faith.get_killer_from(st) is None

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError):
            faith.set_status(make_state(), "prophet")

    def test_ensure_runtime_repairs_old_save(self):
        st = make_state()
        del st["hidden"]["faith"]
        del st["visible"]["faith"]
        faith.ensure_runtime(st)
        assert st["hidden"]["faith"]["status"] == "neutral"
        assert st["visible"]["faith"] == "neutral"


class TestNextChainStep:
    def test_neutral_offers_first_steps(self):
        st = make_state()
        assert faith.next_chain_step("cleric", st) == "pala_1"
        assert faith.next_chain_step("necromancer", st) == "heretic_1"

    def test_unknown_role_none(self):
        assert faith.next_chain_step("merchant", make_state()) is None

    def test_paladin_has_no_more_chains(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_PALADIN)
        assert faith.next_chain_step("cleric", st) is None
        assert faith.next_chain_step("necromancer", st) is None

    def test_heretic_has_no_more_chains(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_HERETIC)
        assert faith.next_chain_step("cleric", st) is None
        assert faith.next_chain_step("necromancer", st) is None

    def test_killer_goes_straight_to_k3(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert faith.next_chain_step("necromancer", st) == "heretic_3"
        assert faith.next_chain_step("cleric", st) is None

    def test_killer_with_dead_necromancer_gets_nothing(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        st["hidden"]["faith"]["heretic_chain_blocked"] = True
        assert faith.next_chain_step("necromancer", st) is None

    def test_active_chain_not_reissued(self):
        st = make_state()
        add_quest(st, "pala_1", faith.CHAIN_PALADIN, required=0,
                  qtype="deliver")
        assert faith.next_chain_step("cleric", st) is None

    def test_parallel_chain_can_start(self):
        st = make_state()
        add_quest(st, "heretic_1", faith.CHAIN_HERETIC, required=0,
                  qtype="deliver")
        assert faith.next_chain_step("cleric", st) == "pala_1"

    def test_blocked_paladin_chain(self):
        st = make_state()
        st["hidden"]["faith"]["paladin_chain_blocked"] = True
        assert faith.next_chain_step("cleric", st) is None


class TestChainProgress:
    def test_issue_sets_chain(self):
        st = make_state()
        faith.on_chain_issued("pala_1", st)
        assert st["hidden"]["faith"]["chain"] == faith.CHAIN_PALADIN

    def test_help_counts_up_to_required(self):
        st = make_state()
        add_quest(st, "pala_2", faith.CHAIN_PALADIN, required=5, qtype="help")
        for _ in range(6):
            faith.on_help_completed(st)
        assert st["hidden"]["quests_raw"][0]["progress"] == 5

    def test_help_ignores_chain_completions(self):
        st = make_state()
        add_quest(st, "pala_2", faith.CHAIN_PALADIN, required=5, qtype="help")
        faith.on_help_completed(st, is_chain=True)
        assert st["hidden"]["quests_raw"][0]["progress"] == 0

    def test_failed_quest_resets_help(self):
        st = make_state()
        entry = add_quest(st, "pala_2", faith.CHAIN_PALADIN,
                          required=5, qtype="help", progress=3)
        faith.on_quest_failed(st)
        assert entry["progress"] == 0

    def test_deceive_success(self):
        st = make_state()
        add_quest(st, "heretic_2", faith.CHAIN_HERETIC,
                  required=3, qtype="deceive")
        ok, _msg = faith.on_deceive("elder", "start", 3, st)
        assert ok is True
        assert st["hidden"]["quests_raw"][0]["progress"] == 1

    def test_deceive_failure_lowers_rep(self):
        st = make_state()
        add_quest(st, "heretic_2", faith.CHAIN_HERETIC,
                  required=3, qtype="deceive")
        ok, _msg = faith.on_deceive("elder", "start", 2, st)
        assert ok is False
        assert st["hidden"]["reputation"]["elder"] == -1
        assert st["hidden"]["quests_raw"][0]["progress"] == 0

    def test_deceive_one_attempt_per_npc(self):
        st = make_state()
        add_quest(st, "heretic_2", faith.CHAIN_HERETIC,
                  required=3, qtype="deceive")
        assert faith.on_deceive("elder", "start", 6, st)[0] is True
        ok, msg = faith.on_deceive("elder", "start", 6, st)
        assert ok is False
        assert msg == "already tried"

    def test_deceive_other_node_is_another_npc(self):
        st = make_state()
        add_quest(st, "heretic_2", faith.CHAIN_HERETIC,
                  required=3, qtype="deceive")
        assert faith.on_deceive("elder", "start", 6, st)[0] is True
        assert faith.on_deceive("elder", "forest_1", 6, st)[0] is True

    def test_deceive_without_quest(self):
        assert faith.on_deceive("elder", "start", 6, make_state())[0] is False

    def test_insult_needs_k3(self):
        assert faith.on_insult_to_cleric(make_state()) is False

    def test_insult_sets_first_step_once(self):
        st = make_state()
        entry = add_quest(st, "heretic_3", faith.CHAIN_HERETIC,
                          required=2)
        assert faith.on_insult_to_cleric(st) is True
        assert entry["progress"] == 1
        assert faith.on_insult_to_cleric(st) is False


class TestDonation:
    def test_donate_paladin(self):
        st = make_state(coin=50)
        add_quest(st, "pala_3", faith.CHAIN_PALADIN, required=1)
        info = faith.donate(st, "cleric")
        assert info == {
            "chain": "pala", "quest_id": "pala_3",
            "coins": 50, "complete_now": True,
        }
        assert st["visible"]["wallet"]["coin"] == 0

    def test_donate_paladin_zero_coins_autocompletes(self):
        st = make_state(coin=0)
        add_quest(st, "pala_3", faith.CHAIN_PALADIN, required=1)
        info = faith.donate(st, "cleric")
        assert info["coins"] == 0
        assert info["complete_now"] is True

    def test_donate_heretic_needs_insult(self):
        st = make_state()
        add_quest(st, "heretic_3", faith.CHAIN_HERETIC, required=2)
        assert faith.donate(st, "cleric") is None

    def test_donate_heretic_after_insult(self):
        st = make_state(coin=30)
        add_quest(st, "heretic_3", faith.CHAIN_HERETIC, required=2)
        faith.on_insult_to_cleric(st)
        info = faith.donate(st, "cleric")
        assert info["complete_now"] is False
        assert st["visible"]["wallet"]["coin"] == 0
        assert st["hidden"]["quests_raw"][0]["progress"] == 2

    def test_donate_heretic_zero_coins_still_counts(self):
        st = make_state(coin=0)
        add_quest(st, "heretic_3", faith.CHAIN_HERETIC, required=2)
        faith.on_insult_to_cleric(st)
        info = faith.donate(st, "cleric")
        assert info["coins"] == 0
        assert st["hidden"]["quests_raw"][0]["progress"] == 2

    def test_donate_only_at_cleric(self):
        st = make_state()
        add_quest(st, "pala_3", faith.CHAIN_PALADIN, required=1)
        assert faith.donate(st, "merchant") is None

    def test_chain_complete_paladin_breaks_parallel(self):
        st = make_state()
        add_quest(st, "heretic_1", faith.CHAIN_HERETIC,
                  required=0, qtype="deliver")
        faith.on_chain_complete(faith.CHAIN_PALADIN, st)
        assert faith.get_status(st) == faith.STATUS_PALADIN
        assert st["hidden"]["quests_raw"][0]["status"] == "failed"

    def test_chain_complete_heretic_clears_killer(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_KILLER)
        faith.on_chain_complete(faith.CHAIN_HERETIC, st)
        assert faith.get_status(st) == faith.STATUS_HERETIC
        assert faith.get_killer_from(st) is None


class TestPunishment:
    def test_god_wrath_is_level(self):
        assert faith.god_wrath(1) == 1
        assert faith.god_wrath(4) == 4
        assert faith.god_wrath(0) == 0

    def test_take_punishment_once(self):
        st = make_state(level=4)
        faith.set_status(st, faith.STATUS_KILLER, faith.STATUS_PALADIN)
        faith.ensure_state(st["hidden"])["punishment_pending"] = True
        assert faith.take_punishment(st) == 4
        assert faith.take_punishment(st) == 0

    def test_no_pending_no_damage(self):
        assert faith.take_punishment(make_state(level=9)) == 0


class TestCrime:
    def test_neutral_kill(self):
        st = make_state()
        summary = faith.on_resident_killed("peasant", "peasant", st)
        assert summary["status"] == "killer"
        assert summary["killer_from"] == "neutral"
        assert summary["quest_giver"] is False
        assert faith.get_status(st) == faith.STATUS_KILLER
        assert st["hidden"]["reputation_overall"] == -5
        assert st["hidden"]["reputation"]["peasant"] == -10

    def test_all_active_quests_fail(self):
        st = make_state()
        st["hidden"]["quests_raw"].extend([
            {"id": "elder_1", "giver_role": "elder", "status": "active",
             "chain": None},
            {"id": "merchant_1", "giver_role": "merchant",
             "status": "active", "chain": None},
        ])
        summary = faith.on_resident_killed("peasant", "peasant", st)
        assert summary["failed_quests"] == ["elder_1", "merchant_1"]
        assert all(q["status"] == "failed"
                   for q in st["hidden"]["quests_raw"])
        # the crime itself does not add 10-day role blocks
        assert st["hidden"]["role_quest_block"] == {}

    def test_quest_giver_blocked_for_life(self):
        st = make_state()
        summary = faith.on_resident_killed("elder", "elder", st)
        assert summary["quest_giver"] is True
        assert "elder" in st["hidden"]["killed_quest_givers"]
        assert st["hidden"]["role_quest_block"]["elder"] == -1

    def test_paladin_to_killer_punishment(self):
        st = make_state(level=3)
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)
        assert st["hidden"]["faith"]["punishment_pending"] is True
        assert st["hidden"]["faith"]["paladin_chain_blocked"] is True
        assert faith.take_punishment(st) == 3

    def test_heretic_killer(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_HERETIC)
        faith.on_resident_killed("peasant", "peasant", st)
        assert faith.get_killer_from(st) == "heretic"

    def test_kill_necromancer_blocks_heretic_chain(self):
        st = make_state()
        faith.on_resident_killed("necromancer", "necromancer", st)
        assert st["hidden"]["faith"]["heretic_chain_blocked"] is True
        assert faith.next_chain_step("necromancer", st) is None

    def test_second_kill_keeps_killer_from(self):
        st = make_state()
        faith.set_status(st, faith.STATUS_HERETIC)
        faith.on_resident_killed("peasant", "peasant", st)
        faith.on_resident_killed("child", "child", st)
        assert faith.get_killer_from(st) == "heretic"

    def test_kill_removes_chain(self):
        st = make_state()
        add_quest(st, "pala_1", faith.CHAIN_PALADIN,
                  required=0, qtype="deliver")
        faith.on_chain_issued("pala_1", st)
        faith.on_resident_killed("peasant", "peasant", st)
        assert st["hidden"]["faith"]["chain"] is None


class TestHostility:
    def test_killer_guard_fights(self):
        assert faith.hostility(faith.STATUS_KILLER, "guard") == "fight"

    def test_killer_cleric_fights(self):
        assert faith.hostility(faith.STATUS_KILLER, "cleric") == "fight"

    def test_killer_child_flees(self):
        assert faith.hostility(faith.STATUS_KILLER, "child") == "flee"

    def test_paladin_necromancer_fights(self):
        assert faith.hostility(faith.STATUS_PALADIN,
                               "necromancer") == "fight"

    def test_heretic_cleric_fights(self):
        assert faith.hostility(faith.STATUS_HERETIC, "cleric") == "fight"

    def test_neutral_none(self):
        assert faith.hostility(faith.STATUS_NEUTRAL, "guard") == "none"

    def test_no_talk_after_crime(self):
        assert faith.cannot_talk_after_crime("peasant") is True
        assert faith.cannot_talk_after_crime("cleric") is False
