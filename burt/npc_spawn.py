"""NPC spawn by location — §32 spec v0.7.0.

Who stands where (§32 "СПАВН ПО ЛОКАЦИЯМ"):

    village: elder, peasant, peasant_woman, blacksmith, merchant,
             child, guard, tavernkeeper
    river:   fisherman, merchant (wandering)
    road:    merchant (wandering)
    forest:  veteran
    temple:  cleric - always
    dungeon: necromancer - always

Count rules:

    village     1d6: 1-2 -> 1 role, 3-4 -> 2, 5-6 -> 3, no duplicates
    temple / dungeon    exactly one fixed role
    river / road        one role; d6 >= 5 also spawns a rare role
                        (cleric or necromancer)
    anything else       empty

`bandit` is a monster (§21), not an NPC role: it belongs to spawn.py.

Spawn is cached per node in hidden["npcs_by_node"], so walking away and
coming back shows the same people. hidden["npcs_here"] is the working
list of the current node (read by loop.build_menu).

Pure core: no I/O, no asyncio, no LLM. Dice are rolled by rng (1..6).
"""
from __future__ import annotations

from typing import Callable

Rng = Callable[[], int]


# ---------------------------------------------------------------------
# Pools (§32)
# ---------------------------------------------------------------------

ROLE_SPAWN: dict[str, tuple[str, ...]] = {
    "village": (
        "elder", "peasant", "peasant_woman", "blacksmith",
        "merchant", "child", "guard", "tavernkeeper",
    ),
    "river": ("fisherman", "merchant"),
    "road": ("merchant",),
    "forest": ("veteran",),
    "temple": ("cleric",),
    "dungeon": ("necromancer",),
}

# Roles that need d6 >= 5 on sparse locations (§32).
RARE_ROLES: frozenset[str] = frozenset({"cleric", "necromancer"})

# Locations with a fixed single role.
FIXED_LOCATIONS: frozenset[str] = frozenset({"temple", "dungeon"})

# Locations with one common role plus an optional rare one.
SPARSE_LOCATIONS: frozenset[str] = frozenset({"river", "road"})

RARE_ROLL_MIN = 5


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def _check_d6(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 6:
        raise ValueError(f"{name} must be int 1..6, got {value!r}")


def _count_for_roll(roll: int) -> int:
    """Village size: 1-2 -> 1, 3-4 -> 2, 5-6 -> 3."""
    if roll <= 2:
        return 1
    if roll <= 4:
        return 2
    return 3


# ---------------------------------------------------------------------
# Rolling
# ---------------------------------------------------------------------

def roll_npcs(
    location_type: str,
    roll_count: Rng,
    roll_rare: Rng,
) -> tuple[str, ...]:
    """Roles standing in a location of this type (§32).

    roll_count - d6 used for the village size
    roll_rare  - d6 used for rare roles on river/road

    Both are callables returning 1..6; the results are validated.
    """
    pool = ROLE_SPAWN.get(location_type)
    if not pool:
        return ()

    if location_type in FIXED_LOCATIONS:
        return (pool[0],)

    if location_type in SPARSE_LOCATIONS:
        common = tuple(r for r in pool if r not in RARE_ROLES)
        roles: list[str] = [common[0]] if common else []
        rare_roll = roll_rare()
        _check_d6(rare_roll, "roll_rare")
        if rare_roll >= RARE_ROLL_MIN:
            rare_roll2 = roll_rare()
            _check_d6(rare_roll2, "roll_rare")
            rare_pool = ("cleric", "necromancer")
            roles.append(rare_pool[(rare_roll2 - 1) % 2])
        return tuple(roles)

    # Village-like: pick N distinct roles, no duplicates.
    count_roll = roll_count()
    _check_d6(count_roll, "roll_count")
    count = _count_for_roll(count_roll)

    roles: list[str] = []
    used: set[str] = set()
    for _ in range(count):
        pick_roll = roll_rare()
        _check_d6(pick_roll, "roll_rare")
        # Deterministic, duplicate-free walk from the rolled position.
        start = pick_roll - 1
        for offset in range(len(pool)):
            candidate = pool[(start + offset) % len(pool)]
            if candidate not in used:
                used.add(candidate)
                roles.append(candidate)
                break
    return tuple(roles)


# ---------------------------------------------------------------------
# Cache per node (§32)
# ---------------------------------------------------------------------

def ensure_npcs(
    hidden: dict,
    location_type: str,
    node_id: str,
    rng: Rng,
) -> bool:
    """Fill hidden["npcs_here"] for this node. Returns True if it changed.

    A node is generated once; re-entering it restores the cached roles.
    """
    cache = hidden.setdefault("npcs_by_node", {})
    if node_id in cache:
        roles = tuple(cache[node_id])
        changed = list(hidden.get("npcs_here") or []) != list(roles)
        hidden["npcs_here"] = list(roles)
        return changed

    roles = roll_npcs(location_type, rng, rng)
    cache[node_id] = list(roles)
    changed = list(hidden.get("npcs_here") or []) != list(roles)
    hidden["npcs_here"] = list(roles)
    return changed


def npcs_for(hidden: dict, node_id: str) -> tuple[str, ...]:
    """Cached roles of a node (empty tuple when never generated)."""
    cache = hidden.get("npcs_by_node") or {}
    return tuple(cache.get(node_id, ()))


def clear_npcs(hidden: dict) -> None:
    """Drop the working list (used on new life / world reset)."""
    hidden["npcs_here"] = []


def reset_cache(hidden: dict) -> None:
    """Drop every cached node (used when the world is wiped)."""
    hidden["npcs_by_node"] = {}
    hidden["npcs_here"] = []
