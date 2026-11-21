"""P0 regression: death + resurrection on the last step of the day.

Replays the live-run sequence from Gemma 4-E4B(log_of_life_x4)_3.txt:

    step 19 attack -> step 20 combat -> Burt dies -> roll 6 (resurrection)
    -> the next step-20 turn ticks 20->21 -> the day must wrap.

Before the fix the day never rolled over: the step grew 21, 22, ... and
every state_io.save_state() raised "ValueError: step (N) > maximum (20)",
so the run stopped persisting. The second death in that same day also
rolled the dice again (resurrection_used_today was written but never read).

All tests mock the LLM / action layer: the scenario is too rare to wait
for it in a live run (one time in ~200 runs).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import main
from burt import combat as combat_mod
from burt import state_io
from burt.loop import ActionResult

SUCCESS = main.resurrection.ResurrectionOutcome.SUCCESS


def _state() -> dict:
    st = main.make_new_state(life=1)
    st["hidden"]["step"] = 19
    st["hidden"]["day"] = 1
    st["visible"]["hp"] = 4
    return st


def _combat_dict() -> dict:
    return combat_mod.start_combat(["goblin_shaman"], "enemy").to_dict()


class TestLogReplay:
    """20th step + combat + death + resurrection + the next tick."""

    @pytest.mark.asyncio
    async def test_day_end_resurrection_keeps_state_valid(self, tmp_path):
        state = _state()
        state_path = tmp_path / "state.json"
        calls = {"n": 0}

        def fake_execute(action, state, rng=None, dialogue_engine=None):
            calls["n"] += 1
            hidden = state["hidden"]
            if calls["n"] == 1:
                # step 19 attack from a revealed encounter: tick 19->20,
                # combat starts (the fight itself does not tick).
                hidden["step"] = 20
                hidden["current_mode"] = "combat"
                hidden["combat"] = _combat_dict()
                return ActionResult(events=["[COMBAT]"], game_over=False)
            if calls["n"] == 2:
                # combat round on step 20: Burt dies, combat is cleared.
                hidden["current_mode"] = "exploring"
                hidden["combat"] = None
                state["visible"]["hp"] = 0
                return ActionResult(events=["You died."], game_over=True)
            # any ticking action on step 20 (osmotret in the live log).
            hidden["step"] = hidden.get("step", 0) + 1
            hidden["current_mode"] = "exploring"
            return ActionResult(events=["You look around."], game_over=False)

        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action", side_effect=fake_execute,
        ), patch.object(
            main.resurrection, "check_resurrection", return_value=SUCCESS,
        ), patch.object(
            main, "_write_epitaph", new=AsyncMock(),
        ) as epitaph:
            state = await main.game_loop(
                state, [], max_steps=3, dry_run=False,
                state_path=state_path, epitaphs_dir=tmp_path,
            )

        assert calls["n"] == 3
        # §6: a successful resurrection is not a death -> no epitaph.
        assert epitaph.called is False
        # The day rolled over instead of overrunning DAY_STEPS.
        assert state["hidden"]["day"] == 2
        assert state["hidden"]["step"] == 0
        assert state["hidden"]["resurrection_used_today"] is False
        assert state["visible"]["hp"] == state["visible"]["hp_max"]

        # load_state validates: no "step > maximum" ever hit the disk.
        loaded = state_io.load_state(state_path)
        assert loaded["hidden"]["day"] == 2
        assert loaded["hidden"]["step"] == 0


class TestSaveAfterResurrection:
    @pytest.mark.asyncio
    async def test_resurrected_state_is_saved_immediately(self, tmp_path):
        state = _state()
        state["hidden"]["step"] = 20
        state_path = tmp_path / "state.json"

        async def dead_turn(*a, **kw):
            return main.TurnResult(
                game_over=True, history=[], death_cause="combat",
            )

        with patch("main.run_turn", side_effect=dead_turn), \
             patch.object(
                 main.resurrection, "check_resurrection", return_value=SUCCESS,
             ), \
             patch.object(main, "_write_epitaph", new=AsyncMock()) as epitaph:
            await main.game_loop(
                state, [], max_steps=1, dry_run=False,
                state_path=state_path, epitaphs_dir=tmp_path,
            )

        loaded = state_io.load_state(state_path)
        assert loaded["visible"]["hp"] == main.resurrection.RESURRECTION_HP
        assert loaded["hidden"]["resurrection_used_today"] is True
        assert loaded["hidden"]["step"] == 20
        assert epitaph.called is False


class TestOneMercyPerDay:
    @pytest.mark.asyncio
    async def test_second_death_same_day_skips_the_dice(self, tmp_path):
        state = _state()
        state["hidden"]["resurrection_used_today"] = True
        turns = {"n": 0}

        async def fake_run_turn(*a, **kw):
            turns["n"] += 1
            if turns["n"] == 1:
                return main.TurnResult(
                    game_over=True, history=[], death_cause="combat",
                )
            return main.TurnResult(game_over=False, history=[])

        with patch("main.run_turn", side_effect=fake_run_turn), \
             patch.object(
                 main.resurrection, "check_resurrection",
                 side_effect=AssertionError("dice must not roll"),
             ) as roll, \
             patch.object(main, "_write_epitaph", new=AsyncMock()) as epitaph:
            state = await main.game_loop(
                state, [], max_steps=2, dry_run=False,
                state_path=tmp_path / "state.json", epitaphs_dir=tmp_path,
            )

        assert roll.called is False
        assert epitaph.called is True
        assert epitaph.await_args.args[1] == "combat"
        assert state["meta"]["life"] == 2


class TestCombatAtDayEnd:
    @pytest.mark.asyncio
    async def test_step_is_clamped_and_the_day_wraps_after_the_fight(
        self, tmp_path,
    ):
        state = _state()
        state["hidden"]["step"] = 20
        calls = {"n": 0}
        observed = {}

        def fake_execute(action, state, rng=None, dialogue_engine=None):
            calls["n"] += 1
            hidden = state["hidden"]
            if calls["n"] == 1:
                # attack from a revealed encounter on step 20: tick 20->21
                hidden["step"] = 21
                hidden["current_mode"] = "combat"
                hidden["combat"] = _combat_dict()
                return ActionResult(events=["[COMBAT]"], game_over=False)
            # the fight ends on the next turn; combat itself does not tick
            observed["step"] = hidden["step"]
            hidden["current_mode"] = "exploring"
            hidden["combat"] = None
            return ActionResult(events=["You fled."], game_over=False)

        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action", side_effect=fake_execute,
        ):
            state = await main.game_loop(
                state, [], max_steps=2, dry_run=False,
                state_path=tmp_path / "state.json", epitaphs_dir=tmp_path,
            )

        assert calls["n"] == 2
        # The state never held step 21 while in combat -> save stayed valid.
        assert observed["step"] == main.state_mod.DAY_STEPS
        assert state["hidden"]["day"] == 2
        assert state["hidden"]["step"] == 0

