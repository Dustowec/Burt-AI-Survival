"""Hand slots vs backpack — [HANDS] / [INVENTORY].

`visible["inventory"]` stays the single source of truth for item stacks
(counts). `visible["hands"]` only holds references to at most two stacks:

    visible["hands"] = {"weapon": "ordinary_sword", "item": "bread"}

    slot 1 (weapon): the equipped weapon, or None;
    slot 2 (item):   one auxiliary/consumable item (food, water, torch,
                     tool), or None.

Everything else lives in the backpack and is shown only by the `inventory`
tool action.

Pure core: no I/O, no asyncio, no LLM.
"""
from __future__ import annotations

from typing import Any

from burt import items
from burt import weapons

__all__ = [
    "WEAPON_SLOT",
    "ITEM_SLOT",
    "SLOTS",
    "MAX_HANDS",
    "EQUIP_PREFIX",
    "UNEQUIP_WEAPON",
    "UNEQUIP_ITEM",
    "ensure_hands",
    "sync",
    "is_weapon_item",
    "is_food_item",
    "is_water_item",
    "is_aux_item",
    "can_equip",
    "equip",
    "unequip",
    "hand_name",
    "hand_item_name",
    "first_food_name",
    "first_water_name",
    "hand_weapon_entries",
    "split_inventory",
    "is_equip_action",
    "equip_target_name",
]

WEAPON_SLOT = "weapon"
ITEM_SLOT = "item"
SLOTS: tuple[str, str] = (WEAPON_SLOT, ITEM_SLOT)
MAX_HANDS = 2

# Auxiliary items that are neither weapons nor food, but still belong in
# the second hand slot (torch/tool/water/bedroll).
AUX_NAMES: frozenset[str] = frozenset({
    "water", "waterskin", "large_waterskin",
    "bedroll", "torch", "rope", "flint", "knife",
})

WATER_NAMES: frozenset[str] = frozenset({
    "water", "waterskin", "large_waterskin",
})

EQUIP_PREFIX = "equip_"
UNEQUIP_WEAPON = "unequip_weapon"
UNEQUIP_ITEM = "unequip_item"


# ---------------------------------------------------------------------
# Stack helpers
# ---------------------------------------------------------------------

def _lower(name: Any) -> str:
    return (name or "").lower() if isinstance(name, str) else ""


def _stacks(visible: dict) -> list[dict]:
    inventory = visible.get("inventory")
    if not isinstance(inventory, list):
        inventory = []
        visible["inventory"] = inventory
    return inventory


def _count(visible: dict, name: str) -> int:
    key = _lower(name)
    if not key:
        return 0
    total = 0
    for entry in _stacks(visible):
        if not isinstance(entry, dict):
            continue
        if _lower(entry.get("name")) == key:
            try:
                total += int(entry.get("count", 0))
            except (TypeError, ValueError):
                continue
    return total


# ---------------------------------------------------------------------
# Item classification
# ---------------------------------------------------------------------

def is_weapon_item(name: str) -> bool:
    """A usable weapon (fists excluded — they are always there)."""
    key = _lower(name)
    if not key or key == "fists":
        return False
    weapon = weapons.WEAPONS.get(key)
    return bool(weapon and weapon.humanoid)


def is_food_item(name: str) -> bool:
    return items.is_food(_lower(name))


def is_water_item(name: str) -> bool:
    return _lower(name) in WATER_NAMES


def is_aux_item(name: str) -> bool:
    key = _lower(name)
    if not key:
        return False
    if is_food_item(key) or key in AUX_NAMES:
        return True
    return False


def can_equip(name: str) -> bool:
    return is_weapon_item(name) or is_aux_item(name)


# ---------------------------------------------------------------------
# Migration / repair
# ---------------------------------------------------------------------

def _first_aux(visible: dict) -> str | None:
    """First food, then water, then any other auxiliary item."""
    for entry in _stacks(visible):
        if not isinstance(entry, dict):
            continue
        name = _lower(entry.get("name"))
        try:
            count = int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count > 0 and name and is_food_item(name):
            return name
    for entry in _stacks(visible):
        if not isinstance(entry, dict):
            continue
        name = _lower(entry.get("name"))
        try:
            count = int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count > 0 and name and is_aux_item(name):
            return name
    return None


def ensure_hands(visible: dict) -> dict:
    """Return repaired visible["hands"], creating it for old saves.

    When the field is missing the best usable weapon and the first food /
    water / tool are equipped, so an old save keeps working.
    """
    if not isinstance(visible, dict):
        return {WEAPON_SLOT: None, ITEM_SLOT: None}

    _stacks(visible)
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        hands = {WEAPON_SLOT: None, ITEM_SLOT: None}
        best = weapons.select_weapon(visible.get("inventory") or [])
        if best.key and best.key != "fists" and _count(visible, best.key) > 0:
            hands[WEAPON_SLOT] = best.key
        hands[ITEM_SLOT] = _first_aux(visible)
        visible["hands"] = hands

    for slot in SLOTS:
        value = hands.get(slot)
        if not isinstance(value, str) or not value:
            hands[slot] = None
            continue
        name = _lower(value)
        if _count(visible, name) <= 0:
            hands[slot] = None
            continue
        if slot == WEAPON_SLOT and not is_weapon_item(name):
            hands[slot] = None
        if slot == ITEM_SLOT and not is_aux_item(name):
            hands[slot] = None

    return hands


def sync(visible: dict) -> dict:
    """Drop hand references to stacks that no longer exist.

    Safe to call after eat / drink / trade / quest delivery.
    """
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        return ensure_hands(visible)
    for slot in SLOTS:
        value = hands.get(slot)
        if not isinstance(value, str) or _count(visible, value) <= 0:
            hands[slot] = None
    return hands


# ---------------------------------------------------------------------
# Equip / unequip
# ---------------------------------------------------------------------

def equip(visible: dict, name: str) -> bool:
    """Put an item from the inventory into the matching hand slot."""
    key = _lower(name)
    if not key or _count(visible, key) <= 0:
        return False
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        hands = ensure_hands(visible)
    if is_weapon_item(key):
        hands[WEAPON_SLOT] = key
        return True
    if is_aux_item(key):
        hands[ITEM_SLOT] = key
        return True
    return False


def unequip(visible: dict, slot: str) -> bool:
    """Move a hand slot back to the backpack (clear the reference)."""
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        return False
    if slot not in SLOTS:
        return False
    if hands.get(slot) is None:
        return False
    hands[slot] = None
    return True



# ---------------------------------------------------------------------
# Read-only queries (used by menu / sensory / combat)
# ---------------------------------------------------------------------

def hand_name(visible: dict, slot: str) -> str | None:
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        return None
    value = hands.get(slot)
    if not isinstance(value, str) or _count(visible, value) <= 0:
        return None
    return value


def hand_item_name(visible: dict) -> str | None:
    """The item in slot 2.

    Old fixtures without a `hands` field fall back to the first food, then
    the first water in the inventory — this keeps the menu behaviour of
    saves made before hand slots existed.
    """
    hands = visible.get("hands")
    if isinstance(hands, dict):
        return hand_name(visible, ITEM_SLOT)
    return first_food_name(visible) or first_water_name(visible)


def _first_matching(visible: dict, predicate) -> str | None:
    for entry in _stacks(visible):
        if not isinstance(entry, dict):
            continue
        name = _lower(entry.get("name"))
        try:
            count = int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count > 0 and name and predicate(name):
            return name
    return None


def first_food_name(visible: dict) -> str | None:
    return _first_matching(visible, is_food_item)


def first_water_name(visible: dict) -> str | None:
    return _first_matching(visible, is_water_item)


def hand_weapon_entries(visible: dict) -> list:
    """Inventory-shaped list holding only the equipped weapon.

    Falls back to the whole inventory when the `hands` field is absent
    (old saves / unit fixtures), so combat stats keep working.
    """
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        inventory = visible.get("inventory")
        return inventory if isinstance(inventory, list) else []
    name = hand_name(visible, WEAPON_SLOT)
    if not name:
        return []
    return [{"name": name, "count": _count(visible, name)}]


def split_inventory(visible: dict) -> tuple:
    """Return (hands_entries, backpack_entries).

    hands_entries: list of (slot, name, count).
    backpack_entries: inventory stacks not referenced by a hand slot.
    """
    hands = visible.get("hands")
    if not isinstance(hands, dict):
        hands = {}
    entries = []
    held = set()
    for slot in SLOTS:
        name = hands.get(slot)
        if isinstance(name, str) and name and _count(visible, name) > 0:
            entries.append((slot, name, _count(visible, name)))
            held.add(_lower(name))

    backpack = []
    for entry in _stacks(visible):
        if not isinstance(entry, dict):
            continue
        name = _lower(entry.get("name"))
        if not name or name in held:
            continue
        try:
            count = int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count > 0:
            backpack.append({"name": entry.get("name"), "count": count})
    return entries, backpack


# ---------------------------------------------------------------------
# Menu action helpers
# ---------------------------------------------------------------------

def is_equip_action(key: str) -> bool:
    return key.startswith(EQUIP_PREFIX) or key in (UNEQUIP_WEAPON, UNEQUIP_ITEM)


def equip_target_name(key: str) -> str | None:
    """Item name behind an `equip_<name>` action key (None otherwise)."""
    if not key.startswith(EQUIP_PREFIX):
        return None
    name = key[len(EQUIP_PREFIX):]
    return name or None

