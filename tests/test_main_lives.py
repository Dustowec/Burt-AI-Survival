"""TZ-5: wipe LLM history when starting a new life."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import main
from burt import resurrection as res_mod, state as state_mod

# Keep a reference to the real enum so tests don't leak pollution
_REAL_ResurrectionOutcome = res_mod.ResurrectionOutcome


@pytest.fixture(autouse=True)
def _restore_resurrection_enum():
    """Restore ResurrectionOutcome after every test in this module."""
    yield
    setattr(res_mod, "ResurrectionOutcome", _REAL_ResurrectionOutcome)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mk_state(life: int = 1) -> dict:
    return state_mod.create_initial_state(
        life=life,
        session_uuid="test-uuid",
        config_hash="v0.7.0",
        session_started="2026-11-18T00:00:00+00:00",
    )


def _dead_turn(history: list) -> main.TurnResult:
    return main.TurnResult(game_over=True, history=history)


# ------------------------------------------------------------------
# Test 1 — history wiped after FAILED resurrection
# ------------------------------------------------------------------

class TestHistoryWipedAfterFailedResurrection:
    @pytest.mark.asyncio
    async def test_history_wiped_after_failed_resurrection(self):
        from main import game_loop

        state = _mk_state(life=1)

        # history с «волком» из прошлой жизни
        dirty_history = [
            {"role": "user", "content": "[COMBAT] Enemy: wolf"},
            {"role": "assistant", "content": "I strike the wolf."},
        ]
        captured: list[list] = []

        async def fake_run_turn(
            state: dict, history: list, rng, dry_run: bool, *a, **kw
        ):
            captured.append(list(history))
            # первый вызов -> смерть; второй -> не смерть (чтобы цикл завершился)
            if len(captured) == 1:
                return _dead_turn(
                    history
                    + [
                        {"role": "user", "content": "[COMBAT] Enemy: wolf"},
                        {"role": "assistant", "content": "I strike the wolf."},
                    ]
                )
            return main.TurnResult(game_over=False, history=history)

        # resurrection FAILED — заменяем enum на простой класс
        res_mod.ResurrectionOutcome = type(
            "E", (), {"SUCCESS": "success", "FAILED": "failed"}
        )

        try:
            with patch("main.run_turn", side_effect=fake_run_turn), \
                 patch(
                     "main.resurrection.check_resurrection",
                     return_value="failed",
                 ), \
                 patch("main.state_io.save_state"), \
                 patch(
                     "main.make_new_state",
                     return_value=_mk_state(life=2),
                 ):
                await game_loop(
                    state,
                    dirty_history,
                    max_steps=3,
                    dry_run=False,
                    state_path=Path("x.json"),
                )

            # Первый вызов получил dirty_history.
            # Второй вызов (новая жизнь) должен получить ПУСТОЙ history.
            assert captured[0] == dirty_history
            assert captured[1] == []  # <-- ключевой ассерт баг-фикса
        finally:
            setattr(
                res_mod, "ResurrectionOutcome", _REAL_ResurrectionOutcome
            )


# ------------------------------------------------------------------
# Test 2 — history kept after SUCCESS resurrection
# ------------------------------------------------------------------

class TestHistoryKeptAfterSuccessfulResurrection:
    @pytest.mark.asyncio
    async def test_history_kept_after_successful_resurrection(self):
        from main import game_loop

        state = _mk_state(life=1)

        dirty_history = [
            {"role": "user", "content": "[COMBAT] Enemy: wolf"},
            {"role": "assistant", "content": "I strike the wolf."},
        ]
        captured: list[list] = []

        async def fake_run_turn(
            state: dict, history: list, rng, dry_run: bool, *a, **kw
        ):
            captured.append(list(history))
            if len(captured) == 1:
                return _dead_turn(history)
            return main.TurnResult(game_over=False, history=history)

        # resurrection SUCCESS — Burt остаётся в том же мире/теле
        res_mod.ResurrectionOutcome = type(
            "E", (), {"SUCCESS": "success", "FAILED": "failed"}
        )

        try:
            with patch("main.run_turn", side_effect=fake_run_turn), \
                 patch(
                     "main.resurrection.check_resurrection",
                     return_value="success",
                 ), \
                 patch("main.state_io.save_state"):
                await game_loop(
                    state,
                    dirty_history,
                    max_steps=3,
                    dry_run=False,
                    state_path=Path("x.json"),
                )

            # Второй вызов идёт в той же жизни -> history не пустой.
            assert captured[1] == dirty_history
        finally:
            setattr(
                res_mod, "ResurrectionOutcome", _REAL_ResurrectionOutcome
            )


# ------------------------------------------------------------------
# Test 3 — epitaph memory injected in new life report
# ------------------------------------------------------------------

class TestEpitaphInjectedInNewLifeReport:
    @pytest.mark.asyncio
    async def test_epitaph_injected_in_new_life_report(self):
        from main import run_turn

        state = _mk_state(life=2)
        state["meta"]["memory"] = (
            "I died in battle. The blade is faster than mind."
        )

        # dry_run=True -> run_turn вернёт TurnResult без LLM, с sensory_report
        rng = lambda: 4
        result = await run_turn(state, [], rng, dry_run=True)

        assert "You remember your past life" in result.sensory_report
        assert "I died in battle" in result.sensory_report
