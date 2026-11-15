"""Tests for burt/resurrection.py — resurrection mechanic.

План рефакторинга: ТЗ/refactoring_of_epytaph.md.

При смерти: 1d6 roll. Если 6 — Бурт воскресает с 2 HP в том же мире.
Иначе — окончательная смерть.
"""

import pytest

from burt.resurrection import (
    ResurrectionOutcome,
    check_resurrection,
    RESURRECTION_HP,
)


# ─── Constants ─────────────────────────────────────────────────


class TestConstants:
    def test_resurrection_hp(self):
        assert RESURRECTION_HP == 2


# ─── ResurrectionOutcome ──────────────────────────────────────


class TestResurrectionOutcome:
    def test_success_value(self):
        assert ResurrectionOutcome.SUCCESS.value == "success"

    def test_failed_value(self):
        assert ResurrectionOutcome.FAILED.value == "failed"


# ─── check_resurrection ──────────────────────────────────────


class TestCheckResurrection:
    """Проверка воскрешения: 1d6 -> решение.

    roll == 6: RESURRECTION_SUCCESS — Бурт продолжает жить.
    roll != 6: RESURRECTION_FAILED — мир стирается, Бурт умер.
    """

    def test_roll_6_returns_success(self):
        """roll=6 → SUCCESS."""
        result = check_resurrection(rng=lambda: 6)
        assert result == ResurrectionOutcome.SUCCESS

    def test_roll_1_returns_failed(self):
        """roll=1 → FAILED."""
        result = check_resurrection(rng=lambda: 1)
        assert result == ResurrectionOutcome.FAILED

    def test_roll_2_returns_failed(self):
        """roll=2 → FAILED."""
        result = check_resurrection(rng=lambda: 2)
        assert result == ResurrectionOutcome.FAILED

    def test_roll_3_returns_failed(self):
        """roll=3 → FAILED."""
        result = check_resurrection(rng=lambda: 3)
        assert result == ResurrectionOutcome.FAILED

    def test_roll_4_returns_failed(self):
        """roll=4 → FAILED."""
        result = check_resurrection(rng=lambda: 4)
        assert result == ResurrectionOutcome.FAILED

    def test_roll_5_returns_failed(self):
        """roll=5 → FAILED."""
        result = check_resurrection(rng=lambda: 5)
        assert result == ResurrectionOutcome.FAILED

    @pytest.mark.parametrize("roll", [1, 2, 3, 4, 5])
    def test_non_six_always_failed(self, roll):
        """Любой roll != 6 → FAILED."""
        result = check_resurrection(rng=lambda: roll)
        assert result == ResurrectionOutcome.FAILED

    def test_roll_6_always_success(self):
        """roll=6 всегда → SUCCESS."""
        result = check_resurrection(rng=lambda: 6)
        assert result == ResurrectionOutcome.SUCCESS
