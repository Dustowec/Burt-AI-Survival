"""Preacher event and curse/blessing wiring — spec §10, §13.

Contract:
- a positive travel event (movement roll 5-6) makes a rare d6 roll:
  5-6 -> preacher_event joins hidden["npcs_here"] and hidden["events_here"],
  never hidden["npcs_by_node"];
- the preacher is neutral to every faith status and is not a role;
- talking is free; the first topic reply rolls once:
  1 -> curse, 2-5 -> nothing, 6 -> blessing;
- the effect lasts exactly 3 actions, applies +1/-1 to combat and
  dialogue rolls, and is shown qualitatively in the sensory report;
- dialog_exit ticks once and the preacher disappears.
"""
from __future__ import annotations

import pytest

from burt import combat, events, faith, sensory
from burt.loop import Action, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


ROLES = ("merchant", "guard", "peasant", "peasant_woman", "elder",
         "tavernkeeper", "blacksmith", "fisherman", "child", "veteran",
         "cleric", "necromancer", "mage")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


@pytest.fixture(scope="module")
def replicas():
    return load_replicas("replicas.json")


def make_state(mode: str = "exploring", step: int = 5, **hidden_over) -> dict:
    st = {
        "meta": {"life": 1, "day": 1, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [], "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
            "location": {"name": "Village", "exits": ["north"]},
            "faith": faith.STATUS_NEUTRAL,
        },
        "hidden": {
            "step": step, "day": 1,
            "current_mode": mode,
            "current_node_id": "start",
            "npcs_here": [], "npcs_by_node": {}, "events_here": [],
            "effects_detail": [],
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [], "quests_issued_today": {},
            "role_quest_block": {}, "rep_applied": {},
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0}, "price_modifier": 1.0,
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "has_staff": False, "teacher_found": False,
            "trained_by": [], "skills_raw": [],
            "pending_encounter": None, "encounter_revealed": False,
            "last_action": None, "same_action_count": 0,
            "combat": None, "combat_npc_role": None,
            "dialog_state": None,
            "faith": faith.new_state(),
            "diary": None, "day_log": [],
            "diary_written_today": False, "diary_skipped_today": False,
            "injected_day": 0,
            "location_graph": {
                "start": {"type": "village", "entered": True,
                          "exits": {"north": "n1", "east": None,
                                    "south": None, "west": None}},
                "n1": {"type": "village", "entered": True,
                       "exits": {"south": "start", "north": None,
                                 "east": None, "west": None}},
            },
        },
    }
    st["hidden"].update(hidden_over)
    return st


def movement_state(**hidden_over) -> dict:
    """Two safe, already-entered nodes: no enter/spawn dice at all."""
    st = make_state(**hidden_over)
    st["hidden"]["location_graph"] = {
        "start": {"type": "crossroads", "entered": True,
                  "exits": {"north": "n1", "east": None,
                            "south": None, "west": None}},
        "n1": {"type": "crossroads", "entered": True,
               "exits": {"south": "start", "north": None,
                         "east": None, "west": None}},
    }
    st["visible"]["location"] = {"name": "Crossroads", "exits": ["north"]}
    return st


def open_preacher(st: dict, engine: DialogueEngine) -> None:
    st["hidden"]["npcs_here"] = [events.PREACHER_KEY]
    st["hidden"]["events_here"] = [{"type": "preacher", "used": False}]
    execute_action(
        Action(f"talk_to_{events.PREACHER_KEY}", "Talk to preacher"),
        st, rng=_rng_seq(4), dialogue_engine=engine,
    )


# ---------------------------------------------------------------------
# §10/§13: spawn on a positive travel event
# ---------------------------------------------------------------------

class TestSpawnOnTravel:
    def test_good_move_spawns_preacher(self):
        st = movement_state()
        # move=5 -> loot (no extra dice), preacher roll=6.
        result = execute_action(
            Action("go_north", "Go north"), st, rng=_rng_seq(5, 6),
        )
        assert events.PREACHER_KEY in st["hidden"]["npcs_here"]
        assert any(events.PREACHER_ENCOUNTER_TEXT in ev
                   for ev in result.events)
        assert events.PREACHER_KEY not in st["hidden"]["npcs_by_node"].get(
            "n1", [],
        )
        assert {"type": "preacher", "used": False} in st["hidden"]["events_here"]

    def test_great_move_spawns_preacher(self):
        st = movement_state()
        # move=6 -> blessing dice 2,1; preacher roll=5.
        result = execute_action(
            Action("go_north", "Go north"), st, rng=_rng_seq(6, 2, 1, 5),
        )
        assert events.PREACHER_KEY in st["hidden"]["npcs_here"]
        assert any(events.PREACHER_ENCOUNTER_TEXT in ev
                   for ev in result.events)

    @pytest.mark.parametrize("preacher_roll", [1, 2, 3, 4])
    def test_good_move_without_preacher(self, preacher_roll):
        st = movement_state()
        result = execute_action(
            Action("go_north", "Go north"), st,
            rng=_rng_seq(5, preacher_roll),
        )
        assert events.PREACHER_KEY not in st["hidden"]["npcs_here"]
        assert not any(events.PREACHER_ENCOUNTER_TEXT in ev
                       for ev in result.events)

    def test_bad_move_never_spawns(self):
        st = movement_state()
        execute_action(
            Action("go_north", "Go north"), st, rng=_rng_seq(1, 1, 1),
        )
        assert events.PREACHER_KEY not in st["hidden"]["npcs_here"]

    def test_menu_offers_talk(self, engine):
        st = make_state(npcs_here=[events.PREACHER_KEY])
        keys = [a.key for a in build_menu(
            st["visible"], st, dialogue_engine=engine,
        )]
        assert f"talk_to_{events.PREACHER_KEY}" in keys

    def test_killer_can_still_talk(self, engine):
        st = make_state(npcs_here=[events.PREACHER_KEY])
        st["hidden"]["faith"]["status"] = faith.STATUS_KILLER
        st["hidden"]["faith"]["killer_from"] = "paladin"
        keys = [a.key for a in build_menu(
            st["visible"], st, dialogue_engine=engine,
        )]
        assert f"talk_to_{events.PREACHER_KEY}" in keys



# ---------------------------------------------------------------------
# Dialogue: intro, dice, effects
# ---------------------------------------------------------------------

class TestPreacherDialogue:
    def test_talk_enters_dialog_free(self, engine, replicas):
        st = make_state(npcs_here=[events.PREACHER_KEY])
        result = execute_action(
            Action(f"talk_to_{events.PREACHER_KEY}", "Talk"),
            st, rng=_rng_seq(4), dialogue_engine=engine,
        )
        assert st["hidden"]["current_mode"] == "dialog"
        assert st["hidden"]["dialog_state"]["role_key"] == events.PREACHER_KEY
        assert st["hidden"]["step"] == 5
        intro = replicas["events"][events.PREACHER_KEY]["intro"]
        assert any(ev in intro for ev in result.events)

    def test_curse_on_one(self, engine, replicas):
        st = make_state()
        open_preacher(st, engine)
        result = execute_action(
            Action("dialog_polite", "Polite"), st,
            rng=_rng_seq(1), dialogue_engine=engine,
        )
        assert st["visible"]["effects"] == ["cursed"]
        assert events.modifier(st["hidden"]) == -1
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 3
        assert st["hidden"]["step"] == 5
        lines = replicas["events"][events.PREACHER_KEY]["curse"]
        assert any(ev in lines for ev in result.events)

    def test_blessing_on_six(self, engine, replicas):
        st = make_state()
        open_preacher(st, engine)
        result = execute_action(
            Action("dialog_polite", "Polite"), st,
            rng=_rng_seq(6), dialogue_engine=engine,
        )
        assert st["visible"]["effects"] == ["blessed"]
        assert events.modifier(st["hidden"]) == 1
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 3
        lines = replicas["events"][events.PREACHER_KEY]["blessing"]
        assert any(ev in lines for ev in result.events)

    @pytest.mark.parametrize("roll", [2, 3, 4, 5])
    def test_nothing_on_two_to_five(self, engine, replicas, roll):
        st = make_state()
        open_preacher(st, engine)
        result = execute_action(
            Action("dialog_polite", "Polite"), st,
            rng=_rng_seq(roll), dialogue_engine=engine,
        )
        assert st["visible"]["effects"] == []
        assert events.modifier(st["hidden"]) == 0
        lines = replicas["events"][events.PREACHER_KEY]["nothing"]
        assert any(ev in lines for ev in result.events)

    def test_second_reply_does_not_reroll(self, engine):
        st = make_state()
        open_preacher(st, engine)
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(1), dialogue_engine=engine)
        execute_action(Action("dialog_truth", "Truth"), st,
                       rng=_rng_seq(6), dialogue_engine=engine)
        assert st["visible"]["effects"] == ["cursed"]
        assert events.modifier(st["hidden"]) == -1

    def test_sensory_shows_effect_without_duration(self, engine):
        st = make_state()
        open_preacher(st, engine)
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(6), dialogue_engine=engine)
        report = sensory.format_sensory_report(st["visible"])
        effects_line = next(
            line for line in report.splitlines() if line.startswith("Effects:")
        )
        assert effects_line == "Effects: blessed"
        assert "3" not in effects_line

    def test_exit_ticks_and_removes_preacher(self, engine):
        st = make_state()
        open_preacher(st, engine)
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(6), dialogue_engine=engine)
        execute_action(Action("dialog_exit", "Leave"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        assert st["hidden"]["step"] == 6
        assert st["hidden"]["current_mode"] == "exploring"
        assert events.PREACHER_KEY not in st["hidden"]["npcs_here"]
        assert st["hidden"]["events_here"][-1]["used"] is True



# ---------------------------------------------------------------------
# Effects: duration, modifier wiring, sleep
# ---------------------------------------------------------------------

class TestEffectLifecycle:
    def test_three_actions_then_gone(self):
        st = movement_state()
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED,
        )
        for direction, expected in (("north", 2), ("south", 1)):
            execute_action(Action(f"go_{direction}", "Go"), st,
                           rng=_rng_seq(4))
            assert st["hidden"]["effects_detail"][0]["turns_left"] == expected
            assert events.modifier(st["hidden"]) == 1
        execute_action(Action("go_north", "Go"), st, rng=_rng_seq(4))
        assert st["hidden"]["effects_detail"] == []
        assert st["visible"]["effects"] == []
        assert events.modifier(st["hidden"]) == 0

    def test_tools_do_not_tick(self):
        st = movement_state()
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_CURSED,
        )
        for _ in range(5):
            execute_action(Action("status", "Status"), st)
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 3
        assert events.modifier(st["hidden"]) == -1

    def test_dialog_reply_does_not_tick(self, engine):
        st = make_state(npcs_here=["merchant"])
        execute_action(Action("talk_to_merchant", "Talk"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED,
        )
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 3

    def test_combat_round_ticks(self):
        st = make_state()
        cs = combat.start_combat(["wolf"], "burt")
        cs.free_strike_done = True
        st["hidden"]["combat"] = cs.to_dict()
        st["hidden"]["current_mode"] = "combat"
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED,
        )
        step_before = st["hidden"]["step"]
        execute_action(Action(f"attack_{cs.enemies[0].id}", "Attack"),
                       st, rng=_rng_seq(5))
        assert st["hidden"]["step"] == step_before
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 2

    def test_sleep_clears_effect_and_preacher(self):
        st = make_state(npcs_here=[events.PREACHER_KEY])
        st["hidden"]["events_here"] = [{"type": "preacher", "used": False}]
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_CURSED,
        )
        execute_action(Action("write_diary_and_go_sleep", "Diary+sleep"), st)
        assert st["visible"]["effects"] == []
        assert st["hidden"]["effects_detail"] == []
        assert events.PREACHER_KEY not in st["hidden"]["npcs_here"]

    def test_burt_stats_carry_effect_modifier(self):
        from burt.loop import _build_burt_stats

        st = make_state()
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_CURSED,
        )
        stats = _build_burt_stats(st["visible"], st["hidden"])
        assert stats.modifier == -1
        assert stats.cast_modifier == -1

        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED,
        )
        # cursed + blessed cancel out
        stats = _build_burt_stats(st["visible"], st["hidden"])
        assert stats.modifier == 0

    def test_dialogue_curse_turns_neutral_into_fail(self, engine):
        st = make_state(npcs_here=["merchant"])
        execute_action(Action("talk_to_merchant", "Talk"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_CURSED,
        )
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert st["hidden"]["reputation"]["merchant"] == -1

    def test_dialogue_blessing_turns_neutral_into_success(self, engine):
        st = make_state(npcs_here=["merchant"])
        execute_action(Action("talk_to_merchant", "Talk"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        events.apply_effect(
            st["hidden"], st["visible"], events.EFFECT_BLESSED,
        )
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(3, 4), dialogue_engine=engine)
        assert st["hidden"]["reputation"]["merchant"] == 1

    def test_preacher_exit_keeps_full_three_actions(self, engine):
        """The one-action dialogue does not eat one of the 3 effect actions."""
        st = movement_state()
        open_preacher(st, engine)
        execute_action(Action("dialog_polite", "Polite"), st,
                       rng=_rng_seq(6), dialogue_engine=engine)
        execute_action(Action("dialog_exit", "Leave"), st,
                       rng=_rng_seq(4), dialogue_engine=engine)
        assert st["hidden"]["effects_detail"][0]["turns_left"] == 3
        for direction, expected in (("north", 2), ("south", 1)):
            execute_action(Action(f"go_{direction}", "Go"), st,
                           rng=_rng_seq(4))
            assert st["hidden"]["effects_detail"][0]["turns_left"] == expected
        execute_action(Action("go_north", "Go"), st, rng=_rng_seq(4))
        assert st["hidden"]["effects_detail"] == []

