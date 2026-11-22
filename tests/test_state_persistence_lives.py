"""P0 — the final save keeps the LAST life (new_bug §0).

After any number of deaths the returned / saved state must be the
current life, not life 1.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import main
from burt import resurrection as res_mod
from burt import state_io


def _mk_state(life: int = 1) -> dict:
    return main.make_new_state(life=life)


class TestGameLoopReturnsLastLife:
    @pytest.mark.asyncio
    async def test_final_state_is_last_life(self, tmp_path):
        state = _mk_state(life=1)
        state_path = tmp_path / "state.json"
        calls = {"n": 0}

        async def fake_run_turn(state, history, rng, dry_run, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return main.TurnResult(game_over=True, history=history)
            return main.TurnResult(game_over=False, history=history)

        with patch("main.run_turn", side_effect=fake_run_turn), \
             patch(
                 "main.resurrection.check_resurrection",
                 return_value=res_mod.ResurrectionOutcome.FAILED,
             ), \
             patch("main._write_epitaph", new=AsyncMock()):
            returned = await main.game_loop(
                state, [], max_steps=2, dry_run=False,
                state_path=state_path, epitaphs_dir=tmp_path,
            )

        # Same object, updated in place; the return value is the last life.
        assert returned is state
        assert state["meta"]["life"] == 2
        assert returned["meta"]["life"] == 2

        # And the file on disk continues the last life.
        loaded = state_io.load_state(state_path)
        assert loaded["meta"]["life"] == 2

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_returns_current_state(self, tmp_path):
        state = _mk_state(life=1)

        async def boom(*a, **kw):
            raise KeyboardInterrupt

        with patch("main.run_turn", side_effect=boom):
            returned = await main.game_loop(
                state, [], max_steps=5, dry_run=False,
                state_path=tmp_path / "state.json",
                epitaphs_dir=tmp_path,
            )

        assert returned is state
        assert returned["meta"]["life"] == 1


class TestMainSavesReturnedState:
    @pytest.mark.asyncio
    async def test_main_saves_the_state_returned_by_game_loop(self, tmp_path):
        initial = _mk_state(life=1)
        last_life = _mk_state(life=2)
        state_path = tmp_path / "state.json"
        saved: dict = {}

        def fake_save(path, state):
            saved["state"] = state

        async def fake_game_loop(*a, **kw):
            return last_life

        with patch(
            "sys.argv",
            ["main.py", "--state", str(state_path), "--dry-run",
             "--max-steps", "1"],
        ), \
             patch("main.setup_logging"), \
             patch("main.make_new_state", return_value=initial), \
             patch("main.state_io.state_exists", return_value=False), \
             patch("main.state_io.save_state", side_effect=fake_save), \
             patch("main.game_loop", side_effect=fake_game_loop), \
             patch("main.load_dialogue_engine", return_value=None), \
             patch("main.PluginLogger") as plugin_cls, \
             patch("main.GameSessionLog"):
            plugin_cls.return_value.stop = AsyncMock()
            rc = await main.main()

        assert rc == 0
        assert saved["state"]["meta"]["life"] == 2


class TestMainSavesStateOnCrash:
    @pytest.mark.asyncio
    async def test_crash_saves_the_current_state(self, tmp_path):
        state = _mk_state(life=1)
        state_path = tmp_path / "state.json"
        calls = []

        def fake_save(path, st):
            calls.append(st)

        async def boom(*a, **kw):
            raise ValueError("roll_mage_element: expected 1-6, got 5")

        with (
            patch("sys.argv", ["main.py", "--state", str(state_path),
                               "--max-steps", "1"]),
            patch("main.setup_logging"),
            patch("main.make_new_state", return_value=state),
            patch("main.state_io.state_exists", return_value=False),
            patch("main.state_io.save_state", side_effect=fake_save),
            patch("main.game_loop", side_effect=boom),
            patch("main.load_dialogue_engine", return_value=None),
            patch("main.PluginLogger") as plugin_cls,
            patch("main.GameSessionLog"),
        ):
            plugin_cls.return_value.stop = AsyncMock()
            rc = await main.main()

        assert rc == 1
        # initial save + the save after the crash
        assert len(calls) == 2
        assert calls[-1] is state

    @pytest.mark.asyncio
    async def test_invalid_state_is_dumped_to_crashes(self, tmp_path):
        state = _mk_state(life=1)
        state_path = tmp_path / "state.json"
        crash_dir = tmp_path / "crashes"

        async def boom(*a, **kw):
            raise ValueError("boom")

        with (
            patch("sys.argv", ["main.py", "--state", str(state_path),
                               "--max-steps", "1"]),
            patch("main.setup_logging"),
            patch("main.state_io.state_exists", return_value=True),
            patch("main.state_io.load_state", return_value=state),
            patch("main.state_io.save_state",
                  side_effect=ValueError("bad state")),
            patch("main.game_loop", side_effect=boom),
            patch("main.load_dialogue_engine", return_value=None),
            patch("main.config.CRASH_DIR", str(crash_dir)),
            patch("main.PluginLogger") as plugin_cls,
            patch("main.GameSessionLog"),
        ):
            plugin_cls.return_value.stop = AsyncMock()
            rc = await main.main()

        assert rc == 1
        dumps = list(crash_dir.glob("state_*.json"))
        assert len(dumps) == 1
