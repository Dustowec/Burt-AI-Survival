"""Invalid CHOICE: one re-ask, then a deterministic fallback (new_bug §8)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

import main
from burt import loop
from burt.combat import start_combat
from burt.loop import (
    Action, fallback_action, parse_choice_strict,
)


def _combat_state() -> dict:
    st = main.make_new_state(life=1)
    combat = start_combat(["wolf"], "burt")
    st["hidden"]["combat"] = combat.to_dict()
    st["hidden"]["current_mode"] = "combat"
    return st


def _fake_llm(answers: list[str]):
    calls: list[dict] = []

    async def call(system_msg, user_msg, history=None):
        calls.append({
            "system": system_msg,
            "user": user_msg,
            "history": list(history or []),
        })
        idx = min(len(calls) - 1, len(answers) - 1)
        return answers[idx], history or []

    return call, calls


async def _run_turn_with(answers, state=None):
    st = state or main.make_new_state(life=1)
    fake, calls = _fake_llm(answers)
    captured: dict = {}

    def fake_exec(action, state, rng=None, dialogue_engine=None):
        captured["action"] = action
        return loop.ActionResult(events=[])

    with patch.object(main.llm_client, "call_llm", side_effect=fake), \
         patch.object(main.loop, "execute_action", side_effect=fake_exec):
        await main.run_turn(st, [], rng=lambda: 4, dry_run=False)

    return st, calls, captured


class TestStrictParser:
    def _actions(self):
        return [Action("a", "A"), Action("b", "B")]

    def test_valid_index(self):
        action, reason = parse_choice_strict("CHOICE: 1", self._actions())
        assert action is not None and action.key == "b"
        assert reason == ""

    def test_valid_key(self):
        action, _ = parse_choice_strict("CHOICE: b", self._actions())
        assert action is not None and action.key == "b"

    def test_invalid_number(self):
        action, reason = parse_choice_strict("CHOICE: 99", self._actions())
        assert action is None
        assert "invalid CHOICE" in reason

    def test_no_choice_line(self):
        action, reason = parse_choice_strict("I walk north.", self._actions())
        assert action is None
        assert "no CHOICE" in reason


class TestFallbackAction:
    def test_block_first(self):
        actions = [Action("osmotret", "Look"), Action("block", "Block")]
        assert fallback_action(actions).key == "block"

    def test_osmotret_in_exploring(self):
        actions = [Action("osmotret", "Look"), Action("go_north", "Go")]
        assert fallback_action(actions).key == "osmotret"

    def test_dialog_exit(self):
        actions = [Action("dialog_truth", "Truth"),
                   Action("dialog_exit", "Leave")]
        assert fallback_action(actions).key == "dialog_exit"

    def test_first_action_last_resort(self):
        actions = [Action("x", "X"), Action("y", "Y")]
        assert fallback_action(actions).key == "x"


class TestRunTurnRetry:
    @pytest.mark.asyncio
    async def test_valid_first_try_no_retry(self):
        _, calls, captured = await _run_turn_with(["CHOICE: 0"])
        assert len(calls) == 1
        assert captured["action"].key == "osmotret"

    @pytest.mark.asyncio
    async def test_invalid_then_valid_runs_second(self):
        st, calls, captured = await _run_turn_with(
            ["CHOICE: 99", "CHOICE: 1"],
        )
        expected = loop.build_menu(st["visible"], st)[1]
        assert len(calls) == 2
        assert calls[1]["user"] == loop.INVALID_CHOICE_KICK
        assert captured["action"].key == expected.key

    @pytest.mark.asyncio
    async def test_two_invalid_exploring_falls_back_to_osmotret(self):
        _, calls, captured = await _run_turn_with(
            ["CHOICE: 99", "CHOICE: 99"],
        )
        assert len(calls) == 2
        assert captured["action"].key == "osmotret"

    @pytest.mark.asyncio
    async def test_two_invalid_combat_falls_back_to_block(self):
        _, calls, captured = await _run_turn_with(
            ["CHOICE: 99", "CHOICE: 99"], state=_combat_state(),
        )
        assert len(calls) == 2
        assert captured["action"].key == "block"

    @pytest.mark.asyncio
    async def test_missing_choice_is_retried(self):
        _, calls, captured = await _run_turn_with(
            ["I just stand there.", "CHOICE: 0"],
        )
        assert len(calls) == 2
        assert captured["action"].key == "osmotret"
