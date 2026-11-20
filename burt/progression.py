"""burt/progression.py - §7 "Experience and levels".

Pure core: no I/O, no asyncio, no LLM. Mutates only the `visible` dict
that the orchestrator passes in.

Model
-----
The spec gives two views of the same curve:

    cap(level) = 10 * 1.5^(level-1)      # XP needed for the next level
    1->2: 2 kills, 2->3: 3, 3->4: 5 ...  # kills needed per level
    total kills to level: 2, 5, 10, 17, 27, 42, 65, 99, 150, 227 ...

The per-level kill list in §7 is inconsistent at 5->6 (it says 11,
while the total table says 27 = 17 + 10). The total table is exact:
it follows from summing the caps and carrying the remainder forward.

To keep an integer `visible["xp"]` and reproduce the total table byte
for byte, XP is stored as a running total for the current life and the
level is derived from the cumulative thresholds:

    total_xp_for_level(n) = 20 * (1.5^(n-1) - 1)

This is the closed form of cap(1) + ... + cap(n-1).

Level-up growth
---------------
Every gained level adds HP_PER_LEVEL to hp_max and MP_PER_LEVEL to
mp_max. The same amount is added to the current HP/MP, clamped by the
new maximum: a level-up gives a small reward instead of only raising
the ceiling. This is an interpretation of "HP +2 / MP +1 per level";
it is one line to change if max-only growth is preferred.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

__all__ = [
    "BASE_HP",
    "BASE_MP",
    "HP_PER_LEVEL",
    "MP_PER_LEVEL",
    "KILL_EXP",
    "CAP_BASE",
    "CAP_GROWTH",
    "AwardResult",
    "cap",
    "total_xp_for_level",
    "level_for_xp",
    "level_progress",
    "award_kills",
    "ensure_state",
]

# Base stats of a level-1 Burt (§7).
BASE_HP: int = 10
BASE_MP: int = 3
HP_PER_LEVEL: int = 2
MP_PER_LEVEL: int = 1

# Every kill is worth the same XP (§7: "kill_exp = 5 (always)").
KILL_EXP: int = 5

# cap(level) = CAP_BASE * CAP_GROWTH^(level-1)
CAP_BASE: int = 10
CAP_GROWTH: Fraction = Fraction(3, 2)

# Defensive ceiling for the level search. Level 20 needs 8864 kills;
# 1000 levels keeps the loop finite even for a corrupt XP value.
_MAX_SEARCH_LEVEL: int = 1000


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------

def _validate_level(level: int) -> None:
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        raise ValueError(f"level must be int >= 1, got {level!r}")


def _validate_xp(xp: int) -> None:
    if not isinstance(xp, int) or isinstance(xp, bool) or xp < 0:
        raise ValueError(f"xp must be int >= 0, got {xp!r}")


# ---------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------

def cap(level: int) -> Fraction:
    """§7: XP needed to advance from `level` to `level + 1`.

    Returned as an exact Fraction: 10, 15, 22.5, 33.75, 50.625, ...
    """
    _validate_level(level)
    return Fraction(CAP_BASE) * CAP_GROWTH ** (level - 1)


def total_xp_for_level(level: int) -> Fraction:
    """Cumulative XP required to reach `level` from level 1."""
    _validate_level(level)
    return Fraction(20) * (CAP_GROWTH ** (level - 1) - 1)


def level_for_xp(xp: int) -> int:
    """Highest level whose cumulative threshold is covered by `xp`."""
    _validate_xp(xp)
    level = 1
    while (
        level < _MAX_SEARCH_LEVEL
        and xp >= total_xp_for_level(level + 1)
    ):
        level += 1
    return level


def level_progress(level: int, xp: int) -> tuple[int, int]:
    """(XP earned inside the current level, XP needed for the next one).

    `needed` is ceil(cap(level)) so it can be shown as an integer.
    """
    _validate_level(level)
    _validate_xp(xp)
    floor_value = math.floor(total_xp_for_level(level))
    inside = max(0, xp - floor_value)
    needed = math.ceil(cap(level))
    return inside, needed


# ---------------------------------------------------------------------
# Awarding XP
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class AwardResult:
    """Outcome of one combat reward."""

    gained: int
    old_level: int
    new_level: int
    levels_gained: int


def award_kills(visible: dict[str, Any], kills: int) -> AwardResult:
    """§7: award KILL_EXP per dead enemy and apply level-ups.

    Mutates `visible` only. The caller is responsible for syncing
    hidden hp_raw / mp_raw mirrors afterwards.
    """
    if not isinstance(kills, int) or isinstance(kills, bool) or kills < 0:
        raise ValueError(f"kills must be int >= 0, got {kills!r}")

    gained = kills * KILL_EXP
    xp = int(visible.get("xp", 0)) + gained
    old_level = int(visible.get("level", 1))
    if old_level < 1:
        old_level = 1

    new_level = level_for_xp(xp)
    # Never lose a level because of an inconsistent old save: XP only grows.
    if new_level < old_level:
        new_level = old_level
        xp = max(xp, math.floor(total_xp_for_level(old_level)))
    visible["xp"] = xp
    visible["level"] = new_level

    levels_gained = new_level - old_level
    if levels_gained > 0:
        hp_max = int(visible.get("hp_max", BASE_HP)) + HP_PER_LEVEL * levels_gained
        mp_max = int(visible.get("mp_max", BASE_MP)) + MP_PER_LEVEL * levels_gained
        visible["hp_max"] = hp_max
        visible["mp_max"] = mp_max

        hp = int(visible.get("hp", 0)) + HP_PER_LEVEL * levels_gained
        mp = int(visible.get("mp", 0)) + MP_PER_LEVEL * levels_gained
        visible["hp"] = min(hp, hp_max)
        visible["mp"] = min(mp, mp_max)

    return AwardResult(
        gained=gained,
        old_level=old_level,
        new_level=new_level,
        levels_gained=levels_gained,
    )


def ensure_state(visible: dict[str, Any]) -> None:
    """Repair level/xp fields of an old save (additive, never shrinks)."""
    level = visible.get("level", 1)
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        level = 1
    xp = visible.get("xp", 0)
    if not isinstance(xp, int) or isinstance(xp, bool) or xp < 0:
        xp = 0
    # §7: a running total must at least cover the current level. This
    # repairs old/corrupt saves without ever lowering the level.
    minimum = math.floor(total_xp_for_level(level))
    if xp < minimum:
        xp = minimum
    visible["level"] = level
    visible["xp"] = xp
