"""Воскрешение — 1d6 при смерти.

При смерти Бурта: бросок 1d6.
  roll == 6 → RESURRECTION_SUCCESS — Бурт продолжает жить в том же мире с 2 HP.
  roll != 6 → RESURRECTION_FAILED — мир стирается, Бурт умер.

Это ядро механики, без I/O, без asyncio, без LLM.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass


RESURRECTION_HP = 2


class ResurrectionOutcome(Enum):
    """Результат проверки воскрешения."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class ResurrectionResult:
    """Результат воскрешения с деталями."""

    outcome: ResurrectionOutcome
    roll: int
    hp: int


def check_resurrection(rng) -> ResurrectionOutcome:
    """При смерти: 1d6 -> решение.

    rng: callable, возвращает int 1..6 (например, dice.roll_d6).

    roll != 6: RESURRECTION_FAILED — мир стирается, Бурт умер.
    roll == 6: RESURRECTION_SUCCESS — Бурт продолжает жить в том же мире.
    """
    roll = rng()  # 1d6
    if roll == 6:
        return ResurrectionOutcome.SUCCESS
    return ResurrectionOutcome.FAILED


def apply_resurrection(state: dict) -> ResurrectionResult:
    """Применяет воскрешение к state.

    Устанавливает HP=2 (RESURRECTION_HP), обновляет hidden["hp_raw"].
    Возвращает ResurrectionResult с деталями.
    """
    visible = state.setdefault("visible", {})
    hidden = state.setdefault("hidden", {})

    visible["hp"] = RESURRECTION_HP
    hidden["hp_raw"] = RESURRECTION_HP

    return ResurrectionResult(
        outcome=ResurrectionOutcome.SUCCESS,
        roll=6,
        hp=RESURRECTION_HP,
    )
