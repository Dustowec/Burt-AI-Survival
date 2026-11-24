"""Quest journal tags (Q1, Q2, ...) -- see quests._next_tag.

A tag is assigned once, when the quest is taken, and never reused, so
it stays stable after the quest is completed or failed. The map and the
quest log use it to point at the place where the quest was taken.
"""
from __future__ import annotations

import main
from burt import loop, quests, state as state_mod


def make_state(day=1, node_id="start"):
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": f"{day} day",
            "effects": [],
            "location": {"name": "Crossroads", "exits": ["north"]},
            "inventory": [],
            "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": "exploring", "current_node_id": node_id,
            "day": day, "step": 0,
            "quests_raw": [],
            "role_quest_block": {},
            "quests_issued_today": {},
            "killed_quest_givers": [],
            "reputation": {},
            "quest_counter": 0,
        },
    }


class TestTagsOnGive:
    def test_first_quest_is_q1(self):
        st = make_state()
        assert quests.quest_give("pala_1", "elder", st, force=True)[0] is True
        entry = st["hidden"]["quests_raw"][-1]
        assert entry["tag"] == "Q1"
        assert st["hidden"]["quest_counter"] == 1

    def test_numbers_are_monotonic(self):
        st = make_state()
        quests.quest_give("pala_1", "elder", st, force=True)
        quests.quest_give("veteran_3", "veteran", st, force=True)
        tags = [e["tag"] for e in st["hidden"]["quests_raw"]]
        assert tags == ["Q1", "Q2"]

    def test_tag_is_not_reused_after_completion(self):
        st = make_state()
        quests.quest_give("veteran_3", "veteran", st, force=True)
        st["hidden"]["quests_raw"][0]["status"] = "completed"
        quests.quest_give("pala_1", "elder", st, force=True)
        tags = [e["tag"] for e in st["hidden"]["quests_raw"]]
        assert tags == ["Q1", "Q2"]

    def test_chain_step_gets_its_own_tag(self):
        st = make_state()
        quests.quest_give("pala_1", "elder", st, force=True)
        q = quests.quest_get_active("pala_1", st)
        quests._advance_chain(q, st)
        entries = st["hidden"]["quests_raw"]
        assert entries[0]["tag"] == "Q1"
        assert entries[-1]["tag"] == "Q2"


class TestEnsureTags:
    def test_old_save_gets_tags_in_order(self):
        hidden = {
            "quests_raw": [
                {"id": "a", "status": "active"},
                {"id": "b", "status": "completed"},
            ],
        }
        quests.ensure_tags(hidden)
        assert [e["tag"] for e in hidden["quests_raw"]] == ["Q1", "Q2"]
        assert hidden["quest_counter"] == 2

    def test_idempotent(self):
        hidden = {"quests_raw": [{"id": "a", "status": "active"}]}
        quests.ensure_tags(hidden)
        quests.ensure_tags(hidden)
        assert hidden["quests_raw"][0]["tag"] == "Q1"
        assert hidden["quest_counter"] == 1

    def test_keeps_existing_tags_and_counter(self):
        hidden = {
            "quest_counter": 7,
            "quests_raw": [{"id": "a", "tag": "Q3"},
                           {"id": "b"}],
        }
        quests.ensure_tags(hidden)
        assert hidden["quests_raw"][0]["tag"] == "Q3"
        assert hidden["quests_raw"][1]["tag"] == "Q8"
        assert hidden["quest_counter"] == 8

    def test_no_quests_is_a_noop(self):
        hidden = {}
        quests.ensure_tags(hidden)
        assert hidden["quest_counter"] == 0


class TestTagRoundTrip:
    def test_dict_round_trip(self):
        q = quests.Quest(id="q", giver_role="elder", giver_node="n1",
                         title="T", status="active", type="help", tag="Q5")
        back = quests._dict_to_quest(quests._quest_to_dict(q))
        assert back.tag == "Q5"

    def test_missing_tag_defaults_to_empty(self):
        d = {"id": "q", "giver_role": "elder", "giver_node": "n1",
             "title": "T", "status": "active", "type": "help"}
        assert quests._dict_to_quest(d).tag == ""


class TestQuestLogShowsTag:
    def test_tag_prefix(self):
        st = make_state()
        st["hidden"]["quests_raw"] = [{
            "id": "q", "giver_role": "elder", "giver_node": "start",
            "title": "Two Good Swords", "status": "active",
            "type": "help", "progress": 1, "required": 3,
            "deliver_items": None, "deadline_day": 5, "tag": "Q1",
        }]
        text = loop.format_quest_log(st)
        assert "Q1 Two Good Swords" in text

    def test_no_tag_no_prefix(self):
        st = make_state()
        st["hidden"]["quests_raw"] = [{
            "id": "q", "giver_role": "elder", "giver_node": "start",
            "title": "Two Good Swords", "status": "active",
            "type": "help", "progress": 1, "required": 3,
            "deliver_items": None, "deadline_day": 5,
        }]
        assert "Two Good Swords" in loop.format_quest_log(st)


class TestFreshLife:
    def test_counter_starts_at_zero(self):
        st = state_mod.create_initial_state(
            life=1, session_uuid="s", config_hash="h",
            session_started="2026-11-22T00:00:00",
        )
        assert st["hidden"]["quest_counter"] == 0

    def test_new_life_repairs_tags(self):
        st = state_mod.create_initial_state(
            life=1, session_uuid="s", config_hash="h",
            session_started="2026-11-22T00:00:00",
        )
        st["hidden"]["quests_raw"] = [{"id": "a", "status": "active"}]
        main._ensure_runtime_fields(st)
        assert st["hidden"]["quests_raw"][0]["tag"] == "Q1"
