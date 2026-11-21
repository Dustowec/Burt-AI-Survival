"""Tool results reach the next prompt — spec §26 (ReAct loop, no step tick).

A free tool ends the turn without advancing the step, but its text is
carried into the next sensory report through hidden["pending_tool_output"].
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import main
from burt import loop


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


def _inventory_choice(st: dict) -> str:
    menu = loop.build_menu(st["visible"], st)
    idx = next(i for i, a in enumerate(menu) if a.key == "inventory")
    return f"CHOICE: {idx}"


@pytest.mark.asyncio
async def test_tool_output_is_injected_into_next_prompt():
    st = main.make_new_state(life=1)
    st["visible"]["inventory"] = [{"name": "bread", "count": 2}]
    first = _inventory_choice(st)
    fake, calls = _fake_llm([first, "CHOICE: 0"])

    with patch.object(main.llm_client, "call_llm", side_effect=fake):
        await main.run_turn(st, [], rng=lambda: 4, dry_run=False)
        pending = st["hidden"].get("pending_tool_output")
        assert pending is not None
        assert "[INVENTORY]" in pending
        assert "Bread — 2pcs" in pending

        await main.run_turn(st, [], rng=lambda: 4, dry_run=False)

    assert "[INVENTORY]" in calls[1]["user"]
    assert st["hidden"].get("pending_tool_output") is None


@pytest.mark.asyncio
async def test_tool_does_not_advance_step_in_run_turn():
    st = main.make_new_state(life=1)
    step_before = st["hidden"].get("step", 0)
    fake, _ = _fake_llm([_inventory_choice(st)])

    with patch.object(main.llm_client, "call_llm", side_effect=fake):
        await main.run_turn(st, [], rng=lambda: 4, dry_run=False)

    assert st["hidden"].get("step", 0) == step_before


@pytest.mark.asyncio
async def test_regular_action_leaves_no_pending_output():
    st = main.make_new_state(life=1)
    fake, _ = _fake_llm(["CHOICE: 0"])

    with patch.object(main.llm_client, "call_llm", side_effect=fake):
        await main.run_turn(st, [], rng=lambda: 4, dry_run=False)

    assert st["hidden"].get("pending_tool_output") is None
