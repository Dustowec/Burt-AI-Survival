"""burt/weapons.py - §20 "Damage table".

Pure data and pure helpers: no I/O, no asyncio, no LLM.

Weapon damage
-------------
    fists / claws / teeth / fangs  0-1
    stone                          0-1
    goblin dagger                  1-2   (non-humanoid: cannot be used)
    goblin staff                   0-1   (non-humanoid: cannot be used)
    club                           1-2
    spear                          1-3
    low-quality sword              2-4, quality -1 -> 1-3
    ordinary sword                 2-4
    high-quality sword             2-4, quality +1 -> 3-5
    magic (cast)                   3-6

Quality shifts the whole range by -1 / 0 / +1. Weapons that cannot be
graded (goblin dagger, goblin staff) ignore quality.

Weapon mastery (§8) adds +1 to both ends of the range for every 2
skill levels. Magic is not a weapon, but its mastery works the same
way for the cast damage range.

Selection
---------
There is no equip action in the spec. The orchestrator asks for the
best usable weapon in the inventory, scored by its effective damage
range (including that weapon's own mastery). Empty inventory, only
forbidden weapons or only unknown items -> fists (0-1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from burt import skills

__all__ = [
    "Weapon",
    "WeaponChoice",
    "WEAPONS",
    "QUALITY_SHIFT",
    "FISTS",
    "MAGIC_DAMAGE_MIN",
    "MAGIC_DAMAGE_MAX",
    "is_usable",
    "weapon_skill",
    "damage_range",
    "magic_damage_range",
    "select_weapon",
]

MAGIC_DAMAGE_MIN: int = 3
MAGIC_DAMAGE_MAX: int = 6

QUALITY_SHIFT: dict[str, int] = {
    "low": -1,
    "normal": 0,
    "high": 1,
}


@dataclass(frozen=True)
class Weapon:
    key: str
    display: str
    base_min: int
    base_max: int
    quality: str | None = None      # None = cannot be graded
    skill: str | None = None        # which §8 skill grows on strikes
    humanoid: bool = True           # False = cannot be used by Burt


WEAPONS: dict[str, Weapon] = {
    "fists": Weapon(
        "fists", "fists", 0, 1,
    ),
    "stone": Weapon(
        "stone", "stone", 0, 1,
    ),
    "goblin_dagger": Weapon(
        "goblin_dagger", "goblin dagger", 1, 2, humanoid=False,
    ),
    "goblin_staff": Weapon(
        "goblin_staff", "goblin staff", 0, 1, humanoid=False,
    ),
    "club": Weapon(
        "club", "club", 1, 2, quality="normal", skill="Club",
    ),
    "spear": Weapon(
        "spear", "spear", 1, 3, quality="normal", skill="Spear",
    ),
    "low_quality_sword": Weapon(
        "low_quality_sword", "low-quality sword", 2, 4,
        quality="low", skill="Sword",
    ),
    "ordinary_sword": Weapon(
        "ordinary_sword", "ordinary sword", 2, 4,
        quality="normal", skill="Sword",
    ),
    "high_quality_sword": Weapon(
        "high_quality_sword", "high-quality sword", 2, 4,
        quality="high", skill="Sword",
    ),
    # Legacy/plain name still found in old inventories.
    "sword": Weapon(
        "sword", "sword", 2, 4, quality="normal", skill="Sword",
    ),
    # The magic staff is not in the §20 table. It is an improvised
    # 0-1 weapon; its real purpose is casting (§9).
    "staff": Weapon(
        "staff", "staff", 0, 1,
    ),
}

FISTS = WEAPONS["fists"]


@dataclass(frozen=True)
class WeaponChoice:
    key: str
    damage_min: int
    damage_max: int
    skill: str | None


def is_usable(key: str) -> bool:
    """§20: Burt cannot use non-humanoid weapons (selling is allowed)."""
    weapon = WEAPONS.get((key or "").lower())
    return bool(weapon and weapon.humanoid)


def weapon_skill(key: str) -> str | None:
    weapon = WEAPONS.get((key or "").lower())
    return weapon.skill if weapon else None


# ---------------------------------------------------------------------
# Damage ranges
# ---------------------------------------------------------------------

def _range_for(weapon: Weapon, skill_level: int) -> tuple[int, int]:
    shift = QUALITY_SHIFT.get(weapon.quality or "", 0)
    low = weapon.base_min + shift
    high = weapon.base_max + shift
    if weapon.skill is not None:
        bonus = skills.range_bonus(skill_level)
        low += bonus
        high += bonus
    return max(0, low), max(0, high)


def damage_range(key: str, skill_level: int = 0) -> tuple[int, int]:
    """Effective (min, max) of a weapon for a given mastery level."""
    weapon = WEAPONS.get((key or "").lower())
    if weapon is None:
        raise KeyError(key)
    return _range_for(weapon, skill_level)


def magic_damage_range(skill_level: int = 0) -> tuple[int, int]:
    """§20: magic starts at 3-6; mastery adds +1 per 2 levels."""
    bonus = skills.range_bonus(skill_level)
    return MAGIC_DAMAGE_MIN + bonus, MAGIC_DAMAGE_MAX + bonus


# ---------------------------------------------------------------------
# Best usable weapon in the inventory
# ---------------------------------------------------------------------

def _inventory_names(inventory: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for entry in inventory or []:
        if not isinstance(entry, dict):
            continue
        try:
            count = int(entry.get("count", 0) or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        name = (entry.get("name") or "").lower()
        if name and name not in names:
            names.append(name)
    return names


def select_weapon(
    inventory: Iterable[Any],
    skill_levels: dict[str, int] | None = None,
) -> WeaponChoice:
    """Pick the best usable weapon by effective damage range.

    Fists are the fallback. Forbidden and unknown items are ignored.
    """
    levels = skill_levels or {}
    best = WeaponChoice(
        key=FISTS.key,
        damage_min=FISTS.base_min,
        damage_max=FISTS.base_max,
        skill=FISTS.skill,
    )
    best_score = (best.damage_min + best.damage_max, best.damage_max, 0)

    for name in _inventory_names(inventory):
        weapon = WEAPONS.get(name)
        if weapon is None or not weapon.humanoid or weapon.key == FISTS.key:
            continue
        level = int(levels.get(weapon.skill, 0)) if weapon.skill else 0
        low, high = _range_for(weapon, level)
        score = (low + high, high, 1 if weapon.skill else 0)
        if score > best_score:
            best = WeaponChoice(weapon.key, low, high, weapon.skill)
            best_score = score
    return best

