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

§9 teacher spawn: a wandering mage (replica key `mage_event`) shows up in
temple / dungeon on d6 >= 5, at most once per life. The mage's element is
rolled (1d4) at spawn time -- a 5 or 6 on the element die is
rerolled -- not at training time — see magic.py.

Pure core: no I/O, no asyncio, no LLM. Dice are rolled by rng (1..6).
"""
from __future__ import annotations

from typing import Callable

from burt import magic

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
    # §32 updated (23.11.2026): the veteran lives in the village only and
    # is spawned by maybe_add_veteran (rare roll + 10-day cooldown), so
    # the forest pool is intentionally empty.
    "forest": (),
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

# §9: wandering magic teacher (`mage_event` replicas), at most once per life.
MAGE_ROLE = "mage_event"
MAGE_LOCATIONS: frozenset[str] = frozenset({"temple", "dungeon"})
MAGE_SPAWN_MIN = 5

# §32 updated (23.11.2026): the veteran spawns in the village only, on a
# rare roll, and never more often than once per 10 game days.
VETERAN_ROLE = "veteran"
VETERAN_LOCATION = "village"
VETERAN_SPAWN_MIN = 5
VETERAN_SPAWN_COOLDOWN_DAYS = 10


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


# ---------------------------------------------------------------------
# §9: wandering magic teacher
# ---------------------------------------------------------------------

def maybe_add_mage(
    hidden: dict,
    location_type: str,
    node_id: str,
    rng: Rng,
) -> bool:
    """Add the wandering mage to this node. True when he appears.

    Rules (§9 + agreement of 20.11.2026):
      - temple / dungeon only;
      - d6 >= 5;
      - at most once per life (hidden["magic"]["mage_met"]);
      - the element is rolled (1d4) right now, at spawn time
        (5/6 on the element die is rerolled: engine die is d6).

    Runs AFTER ensure_npcs, so the fixed role (cleric / necromancer) is
    already in place and stays in front of the list.
    """
    if location_type not in MAGE_LOCATIONS:
        return False

    mstate = magic.ensure_state(hidden)
    if magic.mage_spawned(mstate):
        return False

    roll = rng()
    _check_d6(roll, "roll_mage")
    if roll < MAGE_SPAWN_MIN:
        return False

    roles = list(hidden.get("npcs_here") or [])
    if MAGE_ROLE in roles:
        return False
    roles.append(MAGE_ROLE)
    hidden["npcs_here"] = roles

    cache = hidden.setdefault("npcs_by_node", {})
    if isinstance(cache, dict):
        cache[node_id] = list(roles)

    magic.record_teacher_spawn(mstate, MAGE_ROLE, rng)
    return True


def clear_npcs(hidden: dict) -> None:
    """Drop the working list (used on new life / world reset)."""
    hidden["npcs_here"] = []


def maybe_add_veteran(
    hidden: dict,
    location_type: str,
    node_id: str,
    day: int,
    rng: Rng,
) -> bool:
    """Add the veteran to a village node. True when he appears.

    Rules (updated 23.11.2026):
      - village only;
      - d6 >= 5;
      - never more often than once per VETERAN_SPAWN_COOLDOWN_DAYS
        game days (last spawn is tracked in
        hidden["veteran_last_spawn_day"]);
      - while the cooldown is active the die is NOT rolled, so the
        movement / encounter dice order is untouched.

    Runs AFTER ensure_npcs, so the village roles are already in place.
    """
    if location_type != VETERAN_LOCATION:
        return False

    last_day = hidden.get("veteran_last_spawn_day", 0)
    if not isinstance(last_day, int) or isinstance(last_day, bool):
        last_day = 0
    if day - last_day < VETERAN_SPAWN_COOLDOWN_DAYS:
        return False

    roles = list(hidden.get("npcs_here") or [])
    if VETERAN_ROLE in roles:
        return False

    roll = rng()
    _check_d6(roll, "roll_veteran")
    if roll < VETERAN_SPAWN_MIN:
        return False

    roles.append(VETERAN_ROLE)
    hidden["npcs_here"] = roles

    cache = hidden.setdefault("npcs_by_node", {})
    if isinstance(cache, dict):
        cache[node_id] = list(roles)

    hidden["veteran_last_spawn_day"] = day
    return True


def reset_cache(hidden: dict) -> None:
    """Drop every cached node (used when the world is wiped)."""
    hidden["npcs_by_node"] = {}
    hidden["npcs_here"] = []


def remove_npc(hidden: dict, node_id: str, role: str) -> bool:
    """§34: a killed resident is gone for this life."""
    removed = False
    roles = list(hidden.get("npcs_here") or [])
    if role in roles:
        roles.remove(role)
        hidden["npcs_here"] = roles
        removed = True
    cache = hidden.get("npcs_by_node")
    if isinstance(cache, dict):
        cached = list(cache.get(node_id) or [])
        if role in cached:
            cached.remove(role)
            cache[node_id] = cached
            removed = True
    return removed
