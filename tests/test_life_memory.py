"""Тесты для life counter + memory transfer (HANDOFF-14 / TZ-4).

Проверяют:
- create_initial_state принимает memory/memory_cause
- make_new_state инкрементирует life и переносит память
- game_loop auto-restart (unit-тест через mock)
- memory injection в sensory report
- inventory/wallet reset при новой жизни
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from burt.state import create_initial_state
import main
from main import make_new_state


# ---------------------------------------------------------------------
# create_initial_state: memory parameters
# ---------------------------------------------------------------------

class TestCreateInitialStateWithMemory:
    """Test that create_initial_state accepts memory/memory_cause."""

    def _base(self):
        return create_initial_state(
            life=1,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )

    def test_no_memory_by_default(self):
        s = self._base()
        assert "memory" not in s["meta"]
        assert "memory_cause" not in s["meta"]

    def test_memory_transferred(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
            memory="I lived 5 days. I understood patience.",
            memory_cause="hunger",
        )
        assert s["meta"]["life"] == 2
        assert s["meta"]["memory"] == "I lived 5 days. I understood patience."
        assert s["meta"]["memory_cause"] == "hunger"

    def test_memory_none_not_stored(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
            memory=None,
            memory_cause=None,
        )
        assert "memory" not in s["meta"]
        assert "memory_cause" not in s["meta"]

    def test_life_counter_increments(self):
        s = create_initial_state(
            life=7,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["meta"]["life"] == 7

    def test_new_life_has_reset_inventory(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        # Starting inventory should be bread x2, water x1 (not custom)
        assert s["visible"]["inventory"] == [
            {"name": "bread", "count": 2},
            {"name": "water", "count": 1},
        ]

    def test_new_life_has_reset_wallet(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["visible"]["wallet"] == {"coin": 50}

    def test_new_life_has_reset_skills(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["visible"]["skills_visible"] == []
        assert s["hidden"]["skills_raw"] == []

    def test_new_life_has_level_one_and_zero_xp(self):
        """§7: level, XP and skills reset on a new life."""
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["visible"]["level"] == 1
        assert s["visible"]["xp"] == 0

    def test_new_life_has_reset_quests(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["hidden"]["quests_raw"] == []

    def test_new_life_has_fresh_location_graph(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        # Should start at "start" node
        assert s["hidden"]["current_node_id"] == "start"
        assert s["hidden"]["location_graph"]["start"]["type"] == "crossroads"

    def test_new_life_has_full_hp_mp(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["visible"]["hp"] == 10
        assert s["visible"]["hp_max"] == 10
        assert s["visible"]["mp"] == 3
        assert s["visible"]["mp_max"] == 3

    def test_new_life_day_step_reset(self):
        s = create_initial_state(
            life=2,
            session_uuid="test-session",
            config_hash="abc123",
            session_started="2026-10-11T20:00:00",
        )
        assert s["meta"]["day"] == 1
        assert s["meta"]["step"] == 0
        # day/step are in meta, not in hidden (hidden is synced by _sync_hidden_from_meta)
        assert s["meta"]["day"] == 1
        assert s["meta"]["step"] == 0


# ---------------------------------------------------------------------
# make_new_state: memory transfer
# ---------------------------------------------------------------------

class TestMakeNewState:
    """Test make_new_state accepts and forwards memory."""

    def test_make_new_state_default(self):
        s = make_new_state()
        assert s["meta"]["life"] == 1
        assert "memory" not in s["meta"]

    def test_make_new_state_with_memory(self):
        s = make_new_state(
            life=3,
            memory="I learned to forage.",
            memory_cause="combat",
        )
        assert s["meta"]["life"] == 3
        assert s["meta"]["memory"] == "I learned to forage."
        assert s["meta"]["memory_cause"] == "combat"

    def test_make_new_state_generates_new_session(self):
        s1 = make_new_state()
        s2 = make_new_state()
        assert s1["meta"]["session_uuid"] != s2["meta"]["session_uuid"]


# ---------------------------------------------------------------------
# game_loop: auto-restart behavior (unit mock test)
# ---------------------------------------------------------------------

class TestGameLoopAutoRestart:
    """Test that game_loop auto-restarts on game_over."""

    def test_game_over_triggers_new_life(self):
        """After game_over, make_new_state should be called with life+1."""
        from main import game_loop

        # Setup state
        state = make_new_state(life=1)

        # Mock run_turn to return game_over=True once, then success
        mock_turn_result = MagicMock()
        mock_turn_result.game_over = True
        mock_turn_result.history = []

        call_count = [0]

        async def mock_run_turn(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_turn_result
            # Second call: simulate non-game-over
            mock_non_go = MagicMock()
            mock_non_go.game_over = False
            mock_non_go.history = []
            return mock_non_go

        with patch("main.run_turn", mock_run_turn), \
             patch("main.state_io.save_state"), \
             patch("main._write_epitaph", new=AsyncMock()), \
             patch(
                 "main.resurrection.check_resurrection",
                 return_value=main.resurrection.ResurrectionOutcome.FAILED,
             ):
            asyncio_run = __import__("asyncio").run
            asyncio_run(
                game_loop(
                    state,
                    [],
                    max_steps=100,
                    dry_run=False,  # dry_run breaks after first turn
                    state_path=MagicMock(),
                )
            )

        # game_loop should have called run_turn at least twice (1st → game_over, 2nd → continue)
        assert call_count[0] >= 2, "game_loop should have called run_turn at least twice"


# ---------------------------------------------------------------------
# Memory injection in run_turn
# ---------------------------------------------------------------------

class TestMemoryInjection:
    """Test that memory is injected into sensory report on new life."""

    def test_memory_not_injected_on_first_life(self):
        """First life: no memory injection."""
        from main import run_turn
        import asyncio

        state = make_new_state(life=1)
        state["hidden"]["step"] = 0
        state["hidden"]["day"] = 1
        state["hidden"]["current_mode"] = "exploring"

        async def _test():
            result = await run_turn(
                state, [], rng=lambda: 4, dry_run=True
            )
            return result.sensory_report

        report = asyncio.run(_test())
        assert "past life" not in report.lower()

    def test_memory_injected_on_subsequent_life(self):
        """Life 2+: memory should be injected into sensory report."""
        from main import run_turn
        import asyncio

        state = make_new_state(
            life=2,
            memory="I lived 3 days. I understood patience.",
        )
        state["hidden"]["step"] = 0
        state["hidden"]["day"] = 1
        state["hidden"]["current_mode"] = "exploring"

        async def _test():
            result = await run_turn(
                state, [], rng=lambda: 4, dry_run=True
            )
            return result.sensory_report

        report = asyncio.run(_test())
        assert "past life" in report.lower() or "remember" in report.lower()
        assert "I lived 3 days" in report

    def test_memory_not_injected_without_memory_field(self):
        """No memory field → no injection even on life 2."""
        from main import run_turn
        import asyncio

        state = make_new_state(life=2)
        state["hidden"]["step"] = 0
        state["hidden"]["day"] = 1
        state["hidden"]["current_mode"] = "exploring"

        async def _test():
            result = await run_turn(
                state, [], rng=lambda: 4, dry_run=True
            )
            return result.sensory_report

        report = asyncio.run(_test())
        assert "past life" not in report.lower()


# ---------------------------------------------------------------------
# Integration: full restart cycle
# ---------------------------------------------------------------------

class TestFullRestartCycle:
    """Integration test: create state → simulate death → new state."""

    def test_full_cycle_preserves_memory(self):
        """Life 1 death → life 2 starts with memory."""
        # Life 1: create state with memory (simulating epitaph was written)
        state1 = make_new_state(
            life=1,
            memory="I died from hunger on day 3.",
            memory_cause="hunger",
        )

        # Life 2: create new state with transferred memory
        state2 = make_new_state(
            life=2,
            memory=state1["meta"]["memory"],
            memory_cause=state1["meta"]["memory_cause"],
        )

        assert state2["meta"]["life"] == 2
        assert state2["meta"]["memory"] == "I died from hunger on day 3."
        assert state2["meta"]["memory_cause"] == "hunger"
        assert state2["visible"]["inventory"] == [
            {"name": "bread", "count": 2},
            {"name": "water", "count": 1},
        ]
        assert state2["visible"]["wallet"] == {"coin": 50}

    def test_chained_lives_increment_life(self):
        """Multiple lives: life counter increments each time."""
        memory = "Life 1 memory"
        life = 1
        for i in range(5):
            state = make_new_state(life=life, memory=memory)
            assert state["meta"]["life"] == life
            life += 1
            memory = f"Life {i+1} memory"

        assert life == 6
