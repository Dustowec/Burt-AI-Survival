"""burt/skills.py - §8 "Skills (10, one principle)".

Pure core: no I/O, no asyncio, no LLM. Mutates `hidden["skills_raw"]`
and mirrors the visible part into `visible["skills_visible"]`.

Model
-----
Ten skills: four combat (sword / club / spear / magic) and six
non-combat (smithing / stealth / search / eloquence / intimidation /
deception).

Skill = modifier to the die roll:
    +1 at skill level 5
    +2 at skill level 10

Weapon mastery (an extra mechanic):
    counted per STRIKE, not per hit;
    0 -> 1 = 30 strikes, curve x1.5;
    every 2 levels -> +1 to the damage range;
    every 5 levels -> +1 to the die roll;
    threshold 5: critical misses disappear;
    threshold 10: no misses at all.

The `strikes_to_next` value at level 1 is 30, matching the §30 state
example {"level": 1, "strikes": 14, "strikes_to_next": 30}. Level 0
also needs 30 strikes, so the first visible level appears after the
first 30 strikes ("skills are hidden until 1/10").
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

__all__ = [
    "MAX_LEVEL",
    "SKILL_NAMES",
    "COMBAT_SKILLS",
    "NON_COMBAT_SKILLS",
    "STRIKES_BASE",
    "STRIKE_CURVE",
    "SkillGain",
    "strikes_to_next",
    "modifier",
    "range_bonus",
    "level_of",
    "level_map",
    "get_entry",
    "record_strike",
    "award_level",
    "sync_visible",
    "ensure_state",
]

MAX_LEVEL: int = 10

COMBAT_SKILLS: tuple[str, ...] = ("Sword", "Club", "Spear", "Magic")
NON_COMBAT_SKILLS: tuple[str, ...] = (
    "Smithing",
    "Stealth",
    "Search",
    "Eloquence",
    "Intimidation",
    "Deception",
)
SKILL_NAMES: tuple[str, ...] = COMBAT_SKILLS + NON_COMBAT_SKILLS

STRIKES_BASE: int = 30
STRIKE_CURVE: Fraction = Fraction(3, 2)


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def _validate_name(name: str) -> None:
    if name not in SKILL_NAMES:
        raise ValueError(f"unknown skill: {name!r}")


def _clamp_level(level: Any) -> int:
    if not isinstance(level, int) or isinstance(level, bool):
        return 0
    return max(0, min(MAX_LEVEL, level))


def _clamp_strikes(strikes: Any) -> int:
    if not isinstance(strikes, int) or isinstance(strikes, bool):
        return 0
    return max(0, strikes)


# ---------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------

def strikes_to_next(level: int) -> int:
    """Strikes needed to advance from `level` to `level + 1`.

    Level 10 is the cap: 0 strikes are needed (and accepted).
    Level 0 and level 1 both need 30 (see the §30 example).
    Then the curve grows x1.5 per level, rounded up.
    """
    level = _clamp_level(level)
    if level >= MAX_LEVEL:
        return 0
    exponent = max(level, 1) - 1
    value = Fraction(STRIKES_BASE) * STRIKE_CURVE ** exponent
    return math.ceil(value)


def modifier(level: int) -> int:
    """§8: +1 to the die roll per 5 skill levels, +2 at level 10."""
    level = _clamp_level(level)
    return min(2, level // 5)


def range_bonus(level: int) -> int:
    """§8: +1 to the damage range per 2 weapon-mastery levels."""
    level = _clamp_level(level)
    return min(5, level // 2)


# ---------------------------------------------------------------------
# Raw skill records
# ---------------------------------------------------------------------

def _raw_list(hidden: dict[str, Any]) -> list[dict[str, Any]]:
    raw = hidden.get("skills_raw")
    if not isinstance(raw, list):
        raw = []
        hidden["skills_raw"] = raw
    return raw


def get_entry(hidden: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Find a raw skill record by name (None when absent)."""
    for entry in _raw_list(hidden):
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def level_of(hidden: dict[str, Any], name: str) -> int:
    """Current level of a skill (0 when the skill was never raised)."""
    entry = get_entry(hidden, name)
    if entry is None:
        return 0
    return _clamp_level(entry.get("level", 0))


def level_map(hidden: dict[str, Any]) -> dict[str, int]:
    """{skill name: level} for all skill records that have a level > 0."""
    result: dict[str, int] = {}
    for entry in _raw_list(hidden):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        level = _clamp_level(entry.get("level", 0))
        if level > 0:
            result[name] = level
    return result


def _ensure_entry(hidden: dict[str, Any], name: str) -> dict[str, Any]:
    _validate_name(name)
    entry = get_entry(hidden, name)
    if entry is None:
        entry = {
            "name": name,
            "level": 0,
            "strikes": 0,
            "strikes_to_next": strikes_to_next(0),
            "curve": float(STRIKE_CURVE),
        }
        _raw_list(hidden).append(entry)
    else:
        entry["level"] = _clamp_level(entry.get("level", 0))
        entry["strikes"] = _clamp_strikes(entry.get("strikes", 0))
        entry["curve"] = float(STRIKE_CURVE)
        entry["strikes_to_next"] = strikes_to_next(entry["level"])
    return entry


def sync_visible(hidden: dict[str, Any], visible: dict[str, Any]) -> None:
    """Mirror every skill of level >= 1 into visible["skills_visible"]."""
    shown: list[dict[str, Any]] = []
    for entry in _raw_list(hidden):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        level = _clamp_level(entry.get("level", 0))
        if level >= 1:
            shown.append({"name": name, "level": level, "max": MAX_LEVEL})
    visible["skills_visible"] = shown



# ---------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class SkillGain:
    """Result of one strike or one training session."""

    name: str
    level: int
    strikes: int
    strikes_to_next: int
    levels_gained: int


def record_strike(
    hidden: dict[str, Any],
    visible: dict[str, Any],
    name: str,
    count: int = 1,
) -> SkillGain:
    """§8: count one strike (not a hit) and level the skill up."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError(f"count must be int >= 1, got {count!r}")
    entry = _ensure_entry(hidden, name)
    level = entry["level"]
    strikes = entry["strikes"]

    if level >= MAX_LEVEL:
        strikes = 0
        entry["strikes"] = strikes
        entry["strikes_to_next"] = 0
        sync_visible(hidden, visible)
        return SkillGain(name, level, strikes, 0, 0)

    strikes += count
    levels_gained = 0
    while level < MAX_LEVEL and strikes >= strikes_to_next(level):
        strikes -= strikes_to_next(level)
        level += 1
        levels_gained += 1

    if level >= MAX_LEVEL:
        strikes = 0
    entry["level"] = level
    entry["strikes"] = strikes
    entry["strikes_to_next"] = strikes_to_next(level)
    sync_visible(hidden, visible)
    return SkillGain(
        name, level, strikes, entry["strikes_to_next"], levels_gained,
    )


def award_level(
    hidden: dict[str, Any],
    visible: dict[str, Any],
    name: str,
    levels: int = 1,
) -> int:
    """§32: training gives +1 skill level (capped at 10)."""
    if not isinstance(levels, int) or isinstance(levels, bool) or levels < 0:
        raise ValueError(f"levels must be int >= 0, got {levels!r}")
    entry = _ensure_entry(hidden, name)
    new_level = min(MAX_LEVEL, entry["level"] + levels)
    entry["level"] = new_level
    entry["strikes_to_next"] = strikes_to_next(new_level)
    if new_level >= MAX_LEVEL:
        entry["strikes"] = 0
    sync_visible(hidden, visible)
    return new_level


def ensure_state(hidden: dict[str, Any], visible: dict[str, Any]) -> None:
    """Repair old skill records and re-sync the visible mirror."""
    for entry in _raw_list(hidden):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        entry["level"] = _clamp_level(entry.get("level", 0))
        entry["strikes"] = _clamp_strikes(entry.get("strikes", 0))
        entry["curve"] = float(STRIKE_CURVE)
        entry["strikes_to_next"] = strikes_to_next(entry["level"])
    sync_visible(hidden, visible)

