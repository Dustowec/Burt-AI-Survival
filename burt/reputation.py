"""Reputation — §16 spec v0.7.0.

Reputation is tracked per ROLE, not per NPC. Range: -10 .. +10.

Changes (§16):

    dialogue, success   +1
    dialogue, neutral    0
    dialogue, fail      -1
    dialogue, anger     -2
    quest, completed    +1
    quest, failed       -2
    resident killed     -5 overall, -10 for the victim's role (§34)

Limits: one change per dialogue, one per quest.

Effects (§16):

    rep >= +5   better prices, warmer tone, quests given more often
    rep <= -5   worse prices, colder tone, no quests

Pure core: reads and writes the `state` dict, no I/O, no asyncio, no LLM.
"""
from __future__ import annotations

REPUTATION_MIN = -10
REPUTATION_MAX = 10

DIALOGUE_SUCCESS = 1
DIALOGUE_NEUTRAL = 0
DIALOGUE_FAIL = -1
DIALOGUE_ANGER = -2

QUEST_DELTA_OK = 1
QUEST_DELTA_FAIL = -2

KILL_OVERALL = -5
KILL_ROLE = -10

HIGH_REPUTATION = 5
LOW_REPUTATION = -5

HIGH_PRICE_MODIFIER = 0.9
LOW_PRICE_MODIFIER = 1.1


# ---------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------

def _bucket(state: dict) -> dict:
    hidden = state.setdefault("hidden", {})
    rep = hidden.setdefault("reputation", {})
    if not isinstance(rep, dict):
        rep = {}
        hidden["reputation"] = rep
    return rep


def get(state: dict, role: str) -> int:
    """Current reputation with a role (0 for a role we never met)."""
    return int(_bucket(state).get(role, 0))


def change(state: dict, role: str, delta: int) -> int:
    """Apply a delta, clamp to [-10, +10], return the new value.

    Unknown roles are ignored (only keyed roles exist in state).
    """
    rep = _bucket(state)
    if role not in rep:
        return 0
    value = int(rep.get(role, 0)) + int(delta)
    value = max(REPUTATION_MIN, min(REPUTATION_MAX, value))
    rep[role] = value
    return value


# ---------------------------------------------------------------------
# Deltas by event (§16)
# ---------------------------------------------------------------------

def dialogue_delta(outcome, angry: bool = False) -> int:
    """Reputation change for one dialogue (§16)."""
    name = getattr(outcome, "name", str(outcome)).upper()
    if angry:
        return DIALOGUE_ANGER
    if name == "SUCCESS":
        return DIALOGUE_SUCCESS
    if name == "NEUTRAL":
        return DIALOGUE_NEUTRAL
    return DIALOGUE_FAIL


def apply_dialog_rep(state: dict, role: str, delta: int) -> bool:
    """Apply at most one dialogue change per role (§16, limit 1)."""
    hidden = state.setdefault("hidden", {})
    flags = hidden.setdefault("rep_applied", {})
    if flags.get(role):
        return False
    flags[role] = True
    change(state, role, delta)
    return True


def reset_dialog_rep(state: dict) -> None:
    """Called when a dialogue finally ends: next talk can count again."""
    hidden = state.setdefault("hidden", {})
    hidden["rep_applied"] = {}


# ---------------------------------------------------------------------
# Effects (§16)
# ---------------------------------------------------------------------

def price_modifier(rep: int) -> float:
    """1.0 base; 0.9 for rep >= +5; 1.1 for rep <= -5."""
    if rep >= HIGH_REPUTATION:
        return HIGH_PRICE_MODIFIER
    if rep <= LOW_REPUTATION:
        return LOW_PRICE_MODIFIER
    return 1.0


def can_give_quests(rep: int) -> bool:
    """§16: rep <= -5 -> the role gives no quests."""
    return rep > LOW_REPUTATION


def tone(rep: int) -> str:
    """Coarse tone label: warm / neutral / cold."""
    if rep >= HIGH_REPUTATION:
        return "warm"
    if rep <= LOW_REPUTATION:
        return "cold"
    return "neutral"
