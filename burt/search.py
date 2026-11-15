"""Search loot module - TZ-3.

Loot pools per location + DoT on fail_penalty + unified search counter.

All docstrings/comments in English. No Cyrillic literals.
"""
from __future__ import annotations

from typing import Callable

from burt.dice import SearchResult as SearchRollResult


SEARCH_AVAILABLE: frozenset[str] = frozenset({
    "crossroads", "road", "forest", "field",
    "steppe", "swamp", "thicket", "river",
})

# Pools: location -> tuple of item keys (uniform choice)
SEARCH_POOLS: dict[str, tuple[str, ...]] = {
    "forest":  ("mushrooms", "berries"),
    "field":   ("roots", "berries"),
    "steppe":  ("berries",),
    "swamp":   ("moss", "berries"),
    "thicket": ("berries",),
    "river":   ("fish", "shell"),
}


def _pick(pool: tuple[str, ...], rng: Callable[[], int]) -> str:
    idx = (rng() - 1) % len(pool)
    return pool[idx]


def resolve_search(
    roll: int,
    location_type: str,
    rng: Callable[[], int],
) -> tuple[SearchRollResult, list[str], int]:
    """Apply search outcome. Caller must ensure location is searchable."""
    if roll == 1:
        return SearchRollResult("fail_penalty"), [], 0
    if roll == 2:
        return SearchRollResult("fail"), [], 0

    if location_type == "crossroads":
        return _resolve_crossroads(roll, rng)
    if location_type == "road":
        return _resolve_road(roll, rng)
    return _resolve_food_location(roll, location_type, rng)


def _resolve_crossroads(
    roll: int, rng: Callable[[], int]
) -> tuple[SearchRollResult, list[str], int]:
    # Only crit (roll 6) yields loot. roll 2-5 -> empty.
    if roll <= 5:
        return SearchRollResult("fail"), [], 0
    pick = rng()
    if pick <= 3:
        return SearchRollResult("crit"), [], rng()
    return SearchRollResult("crit"), ["club"], 0


def _resolve_road(
    roll: int, rng: Callable[[], int]
) -> tuple[SearchRollResult, list[str], int]:
    # roll 2-4 -> empty. roll 5 -> coins. roll 6 -> weapon only.
    if roll in (3, 4):
        return SearchRollResult("fail"), [], 0
    if roll == 5:
        return SearchRollResult("success"), [], rng()
    weapon_roll = rng()
    if weapon_roll <= 2:
        weapon = "club"
    elif weapon_roll <= 4:
        weapon = "low_quality_sword"
    else:
        weapon = "spear"
    return SearchRollResult("crit"), [weapon], 0


def _resolve_food_location(
    roll: int, location_type: str, rng: Callable[[], int]
) -> tuple[SearchRollResult, list[str], int]:
    pool = SEARCH_POOLS.get(location_type)
    if not pool:
        return SearchRollResult("fail"), [], 0
    if roll in (3, 4):
        return SearchRollResult("partial"), [_pick(pool, rng)], 0
    if roll == 5:
        return SearchRollResult("success"), [
            _pick(pool, rng), _pick(pool, rng),
        ], 0
    return SearchRollResult("crit"), [
        _pick(pool, rng), _pick(pool, rng),
    ], rng()


# --- DoT ---------------------------------------------------

def apply_dot(state: dict) -> None:
    """Apply -1 HP now. If not poisoned, start DoT with 2 more ticks
    (total 3 HP: 1 now + 2 at next turns). If already poisoned,
    only -1 HP (no stacking)."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    dots = hidden.setdefault("dot_effects", [])
    visible["hp"] = max(0, visible.get("hp", 10) - 1)
    hidden["hp_raw"] = visible["hp"]
    if not dots:
        dots.append({"ticks_left": 2})


def tick_dot(state: dict) -> tuple[int, bool]:
    """Tick DoT at start of turn. Returns (hp_lost, game_over).
    One tick per turn regardless of number of effects (no stacking)."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    dots = hidden.get("dot_effects") or []
    if not dots:
        return 0, False
    hp_lost = 1
    visible["hp"] = max(0, visible.get("hp", 10) - hp_lost)
    hidden["hp_raw"] = visible["hp"]
    new_dots = []
    for d in dots:
        left = d.get("ticks_left", 0) - 1
        if left > 0:
            new_dots.append({"ticks_left": left})
    hidden["dot_effects"] = new_dots
    return hp_lost, visible["hp"] <= 0


def sync_poisoned_effect(state: dict) -> None:
    """Sync visible.effects['poisoned'] with hidden.dot_effects."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    dots = hidden.get("dot_effects") or []
    effects = visible.setdefault("effects", [])
    has_poison = "poisoned" in effects
    should = len(dots) > 0
    if should and not has_poison:
        effects.append("poisoned")
    elif not should and has_poison:
        visible["effects"] = [e for e in effects if e != "poisoned"]


# --- Counter ----------------------------------------------

WARN_TEXT = (
    "You feel the gods' eyes upon you. "
    "Searching again may bring misfortune."
)
PENALTY_TEXT = "Divine spit in the face: -1 HP"


def increment_search_counter(state: dict) -> int:
    hidden = state.setdefault("hidden", {})
    hidden["last_action"] = "search"
    count = hidden.get("same_action_count", 0)
    hidden["same_action_count"] = count + 1
    return hidden["same_action_count"]


def check_search_penalty(state: dict) -> tuple[bool, str]:
    """Return (should_penalize, message).
    count >= 2 -> penalty (this is the 3rd+ search)."""
    hidden = state.setdefault("hidden", {})
    count = hidden.get("same_action_count", 0)
    if count >= 2:
        return True, PENALTY_TEXT
    return False, ""
