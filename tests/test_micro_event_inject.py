"""Spec 11: the reason of a failed move goes to the model, not just the log.

The sensory report only shows the location, so the engine names the event
first: a micro-event (stone / tree / lightning / god_wrath), a bad event
(trap / sprain) or an ambush. No numbers, no mechanics.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import main
from burt import loop
from burt.loop import Action, ActionResult


def _state(loc_type: str = "crossroads") -> dict:
    graph = {
        "start": {
            "type": loc_type,
            "entered": True,
            "exits": {"north": "next", "east": None, "south": None,
                      "west": None},
        },
        "next": {"type": "road", "entered": True, "exits": {}},
    }
    return {
        "meta": {"life": 1, "day": 1, "step": 3},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "level": 1, "xp": 0,
            "eat": False, "sleep_counter": 0, "date": "1 day",
            "effects": [],
            "location": {"name": "Crossroads",
                         "exits": ["north", "east", "south", "west"]},
            "inventory": [],
            "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": "exploring",
            "current_node_id": "start",
            "location_graph": graph,
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 3, "day": 1,
            "npcs_here": [], "events_here": [],
            "pending_encounter": None,
            "encounter_revealed": False,
            "micro_location": {"active": False},
            "combat": None,
        },
    }


def _seq(values):
    it = iter(values)
    return lambda: next(it)


# ─── micro-event texts (movement roll 2 -> fail) ───────────


class TestMicroEventText:
    def test_fail_stone(self):
        st = _state()
        # event roll 1 -> stone, damage roll 2 (micro damage = rng - 1)
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([2, 1, 2]),
        )
        assert res.inject == "You stumbled over a sharp stone."
        assert st["visible"]["hp"] == 8

    def test_fail_tree(self):
        st = _state()
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([2, 2, 1]),
        )
        assert res.inject == "You hit a fallen log."

    def test_fail_lightning(self):
        st = _state()
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([2, 3, 1]),
        )
        assert res.inject == "Lightning struck you."

    def test_fail_god_wrath(self):
        st = _state()
        # event roll 4 -> god_wrath, flat damage = level
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([2, 4]),
        )
        assert res.inject == "The gods punish you."
        assert st["visible"]["hp"] == 9

    def test_texts_have_no_numbers(self):
        for text in loop._MICRO_EVENT_TEXT.values():
            assert not any(ch.isdigit() for ch in text), text


# ─── bad-event texts (movement roll 1 -> fail_bad) ─────────


class TestBadEventText:
    def test_trap(self):
        st = _state()
        # bad roll 1 -> trap, damage 2
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([1, 1, 2]),
        )
        assert res.inject == "You stepped into a trap."

    def test_sprain(self):
        st = _state()
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([1, 2, 1]),
        )
        assert res.inject == "You twisted your ankle."

    def test_nothing_has_no_inject(self):
        st = _state()
        # bad roll 5 -> nothing
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([1, 5]),
        )
        assert res.inject is None

    def test_ambush_in_dangerous_location(self):
        st = _state(loc_type="forest")
        # bad roll 3 in a dangerous location -> ambush, then spawn rolls
        res = loop.execute_action(
            Action("go_north", "Go north"), st,
            rng=_seq([1, 3, 1, 1, 4]),
        )
        assert res.inject == "You fell into an ambush."

    def test_ambush_falls_back_to_trap_when_safe(self):
        st = _state(loc_type="crossroads")
        # bad roll 3 outside dangerous locations -> trap
        res = loop.execute_action(
            Action("go_north", "Go north"), st, rng=_seq([1, 3, 2]),
        )
        assert res.inject == "You stepped into a trap."


class TestOtherActionsHaveNoInject:
    def test_look_around(self):
        st = _state()
        res = loop.execute_action(Action("osmotret", "Look around"), st,
                                  rng=lambda: 4)
        assert res.inject is None


# ─── run_turn: the reason is the first line of the prompt ──


class TestRunTurnInjection:
    def test_reason_comes_first(self):
        captured = {}

        async def fake(system, user, history):
            captured["user"] = user
            return "CHOICE: 0", history

        st = _state()
        # Turn 1 produces the event; turn 2 shows it to the model once.
        with patch.object(
            main.loop, "execute_action",
            return_value=ActionResult(events=[], game_over=False,
                                      inject="Lightning struck you."),
        ), patch.object(main.llm_client, "call_llm", new=fake):
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))

        prompt = captured["user"]
        assert prompt.startswith("Lightning struck you.")
        assert prompt.index("Lightning struck you.") < prompt.index("[STATE]")

    def test_event_is_shown_once(self):
        prompts = []
        seen = {"n": 0}

        async def fake(system, user, history):
            prompts.append(user)
            return "CHOICE: 0", history

        def fake_execute(action, state, rng=None, dialogue_engine=None):
            seen["n"] += 1
            # The event happens on the first turn only.
            inject = "Lightning struck you." if seen["n"] == 1 else None
            return ActionResult(events=[], game_over=False, inject=inject)

        st = _state()
        with patch.object(
            main.loop, "execute_action", side_effect=fake_execute,
        ), patch.object(main.llm_client, "call_llm", new=fake):
            for _ in range(3):
                asyncio.run(
                    main.run_turn(st, [], rng=lambda: 4, dry_run=False)
                )

        # Turn 2 shows the reason once; turn 3 is a plain report again.
        assert prompts[1].startswith("Lightning struck you.")
        assert prompts[2].startswith("[STATE]")
        assert "Lightning struck you." not in prompts[2]

    def test_no_inject_means_plain_report(self):
        captured = {}

        async def fake(system, user, history):
            captured["user"] = user
            return "CHOICE: 0", history

        st = _state()
        with patch.object(
            main.loop, "execute_action",
            return_value=ActionResult(events=[], game_over=False),
        ), patch.object(main.llm_client, "call_llm", new=fake):
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))

        assert captured["user"].startswith("[STATE]")
