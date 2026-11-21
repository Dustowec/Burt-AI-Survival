"""NPC hostility combat core -- §34 spec v0.7.0.

Pure core: no I/O, no asyncio, no LLM. Decides *which* resident fights
and which bestiary entry represents that resident. The orchestration
(state mutation, dice, combat rounds) lives in loop.py.

Rules (§33/§34):

    killer   -> guard, cleric        fight
    killer   -> child, peasant*      flee (handled by faith.hostility)
    paladin  -> necromancer          fight
    heretic  -> cleric               fight

A killer is not "still a paladin": `killer_from` never changes the
reaction, so a paladin-turned-killer does not aggro the necromancer.
"""
from __future__ import annotations

from burt import faith


# Roles that can turn a meeting into combat. `bandit` is a monster.
NPC_ROLES: frozenset[str] = frozenset({
    "guard", "cleric", "necromancer",
})

# Bestiary key for each fighting resident (1:1 today).
NPC_ENEMY_KEY: dict[str, str] = {role: role for role in NPC_ROLES}


def enemy_key(role_key: str) -> str | None:
    """Bestiary key for a fighting resident; None for non-combatants."""
    return NPC_ENEMY_KEY.get(role_key)


def is_npc_enemy(key: str) -> bool:
    """True for guard / cleric / necromancer bestiary keys."""
    return key in NPC_ROLES


def is_hostile(state: dict, role_key: str) -> bool:
    """True when this role's meeting must start combat (§34)."""
    return faith.hostility(faith.get_status(state), role_key) == "fight"


def hostile_role(npcs: list[str], state: dict) -> str | None:
    """First role in `npcs` that fights on meeting, None otherwise.

    Only "fight" counts: "flee" and "none" are ignored. The first match
    in the list wins (spawn order is stable, so the result is stable).
    """
    for role_key in npcs:
        if is_hostile(state, role_key):
            return role_key
    return None
