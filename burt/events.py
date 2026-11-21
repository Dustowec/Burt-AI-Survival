"""Random events and effects — §10, §13 of spec v0.7.0.

Pure core: no I/O, no asyncio, no LLM.

Effects
    hidden["effects_detail"] = [
        {"type": "blessed"|"cursed", "modifier": +1|-1, "turns_left": 3},
    ]
    visible["effects"] carries only the types: Burt knows he is blessed
    or cursed, never the modifier or the duration (§13).

Preacher
    Not a role, never cached in hidden["npcs_by_node"]. The positive
    travel-event generator rolls a separate d6: 5-6 spawns him (§10).
    His dialogue rolls 1d6 once: 1 curse, 2-5 nothing, 6 blessing.
"""
from __future__ import annotations

from typing import Callable

from burt import dice


EFFECT_BLESSED = "blessed"
EFFECT_CURSED = "cursed"
EFFECTS: frozenset[str] = frozenset({EFFECT_BLESSED, EFFECT_CURSED})
EFFECT_DURATION = 3

EFFECT_MODIFIER: dict[str, int] = {
    EFFECT_BLESSED: 1,
    EFFECT_CURSED: -1,
}

PREACHER_KEY = "preacher_event"
PREACHER_EVENT_TYPE = "preacher"
PREACHER_ENCOUNTER_TEXT = "You are lucky to meet a preacher."

Rng = Callable[[], int]


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def _check_d6(value: int, name: str) -> None:
    if (not isinstance(value, int) or isinstance(value, bool)
            or not 1 <= value <= 6):
        raise ValueError(f"{name} must be int 1..6, got {value!r}")


# ---------------------------------------------------------------------
# §13: preacher dice table
# ---------------------------------------------------------------------

def resolve_preacher(roll: int) -> str:
    """1 -> curse, 2..5 -> nothing, 6 -> blessing."""
    _check_d6(roll, "preacher roll")
    if roll == 1:
        return "curse"
    if roll == 6:
        return "blessing"
    return "nothing"


def effect_for(kind: str) -> str | None:
    """Map a preacher outcome to an effect type (None for nothing)."""
    if kind == "curse":
        return EFFECT_CURSED
    if kind == "blessing":
        return EFFECT_BLESSED
    if kind == "nothing":
        return None
    raise ValueError(f"unknown preacher outcome: {kind!r}")


# ---------------------------------------------------------------------
# Effects state
# ---------------------------------------------------------------------

def ensure_state(hidden: dict) -> list[dict]:
    """Return a repaired hidden["effects_detail"] list (old saves)."""
    raw = hidden.get("effects_detail")
    if not isinstance(raw, list):
        hidden["effects_detail"] = []
        return hidden["effects_detail"]

    cleaned: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        effect_type = entry.get("type")
        if effect_type not in EFFECTS:
            continue
        turns = entry.get("turns_left", 0)
        if (not isinstance(turns, int) or isinstance(turns, bool)
                or turns <= 0):
            continue
        mod = entry.get("modifier", EFFECT_MODIFIER[effect_type])
        if not isinstance(mod, int) or isinstance(mod, bool):
            mod = EFFECT_MODIFIER[effect_type]
        cleaned.append({
            "type": effect_type,
            "modifier": mod,
            "turns_left": turns,
        })
    hidden["effects_detail"] = cleaned
    return cleaned


def sync_visible(hidden: dict, visible: dict) -> None:
    """Mirror the active effect types into visible["effects"]."""
    detail = ensure_state(hidden)
    visible["effects"] = [entry["type"] for entry in detail]


def apply_effect(
    hidden: dict,
    visible: dict,
    effect_type: str,
    duration: int = EFFECT_DURATION,
) -> dict:
    """Grant an effect for `duration` actions (refreshes a duplicate)."""
    if effect_type not in EFFECTS:
        raise ValueError(f"unknown effect type: {effect_type!r}")
    if (not isinstance(duration, int) or isinstance(duration, bool)
            or duration < 1):
        raise ValueError(f"duration must be int >= 1, got {duration!r}")

    detail = ensure_state(hidden)
    for entry in detail:
        if entry["type"] == effect_type:
            entry["turns_left"] = duration
            entry["modifier"] = EFFECT_MODIFIER[effect_type]
            sync_visible(hidden, visible)
            return entry

    entry = {
        "type": effect_type,
        "modifier": EFFECT_MODIFIER[effect_type],
        "turns_left": duration,
    }
    detail.append(entry)
    sync_visible(hidden, visible)
    return entry


def tick(hidden: dict, visible: dict) -> list[str]:
    """Spend one action: decrement every effect, drop the expired ones."""
    if "effects_detail" not in hidden:
        return []

    detail = ensure_state(hidden)
    expired: list[str] = []
    alive: list[dict] = []
    for entry in detail:
        entry["turns_left"] -= 1
        if entry["turns_left"] > 0:
            alive.append(entry)
        else:
            expired.append(entry["type"])

    hidden["effects_detail"] = alive
    sync_visible(hidden, visible)
    return expired


def modifier(hidden: dict) -> int:
    """Total roll modifier: blessing +1, curse -1 (0 when absent)."""
    detail = hidden.get("effects_detail")
    if not isinstance(detail, list):
        return 0

    total = 0
    for entry in detail:
        if not isinstance(entry, dict):
            continue
        effect_type = entry.get("type")
        if effect_type not in EFFECTS:
            continue
        turns = entry.get("turns_left", 0)
        if (isinstance(turns, int) and not isinstance(turns, bool)
                and turns > 0):
            total += EFFECT_MODIFIER[effect_type]
    return total



# ---------------------------------------------------------------------
# §10/§13: preacher spawn
# ---------------------------------------------------------------------

def spawn_preacher(hidden: dict, rng: Rng) -> bool:
    """Positive travel event (d6 5-6) may bring a preacher to this node.

    The preacher is not a role: he is added to the working npcs_here list
    only, never to the per-node cache, so walking away forgets him.
    """
    roll = rng()
    _check_d6(roll, "preacher spawn roll")
    if dice.resolve_random_event(roll).result != "good":
        return False

    npcs = hidden.setdefault("npcs_here", [])
    if PREACHER_KEY in npcs:
        return False
    npcs.append(PREACHER_KEY)

    events_here = hidden.setdefault("events_here", [])
    events_here.append({"type": PREACHER_EVENT_TYPE, "used": False})
    return True


def mark_preacher_used(hidden: dict) -> bool:
    """Mark the newest unspent preacher event as used. False if none."""
    events_here = hidden.get("events_here")
    if not isinstance(events_here, list):
        return False
    for entry in reversed(events_here):
        if (isinstance(entry, dict)
                and entry.get("type") == PREACHER_EVENT_TYPE
                and not entry.get("used")):
            entry["used"] = True
            return True
    return False

