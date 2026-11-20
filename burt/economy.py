"""burt/economy.py — §19, §35: coins, inventory stacks, price composition.

Pure core: no I/O, no asyncio, no LLM. Takes the `visible` / `hidden`
sections of `state` explicitly and mutates only those dicts.

Why this module exists
----------------------
`burt/trade.py` owns the numbers (§35): base prices, loot prices, which
role sells what, and the raw location modifier roll. `burt/economy.py`
owns the glue the game loop needs:

  * inventory stacks (count / add / remove) — shared by trade, search,
    loot and eating;
  * one price modifier per node, rolled once and cached in
    hidden["prices_by_node"] (§35: "кидается ОДИН РАЗ при входе в
    локацию, живёт до конца сессии");
  * composition of the three modifiers that exist in the spec:

        location    §35: 1.25 / 1.00 / 0.75
        reputation  §16: 0.90 / 1.00 / 1.10
        trade       npc.py bonus "trade_discount" (20% off)

Rounding
--------
§35 rounds down on every step. Composition is done with exact fractions,
so that 1.25 * 0.9 is 1.125 and never 1.1250000000000002: `floor` must
not depend on float noise.

    buy:  floor(base * location * reputation * trade)
    sell: floor(floor(base * 0.5) * location * reputation * trade)
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Callable, Iterable

from burt import trade

__all__ = [
    "DEFAULT_MODIFIER",
    "item_count",
    "has_item",
    "add_item",
    "remove_item",
    "sellable_items",
    "is_sellable",
    "compose",
    "buy_price",
    "sell_price",
    "modifier_for_node",
    "cached_modifier",
]

DEFAULT_MODIFIER: float = 1.0

# A price modifier is a fraction of the base price.
Modifier = float


# ---------------------------------------------------------------------
# Inventory stacks (§19: inventory is a list of {name, count})
# ---------------------------------------------------------------------

def _stacks(visible: dict) -> list[dict]:
    inventory = visible.setdefault("inventory", [])
    if not isinstance(inventory, list):
        inventory = []
        visible["inventory"] = inventory
    return inventory


def item_count(visible: dict, name: str) -> int:
    """How many of this item Burt carries (0 when absent)."""
    key = (name or "").lower()
    total = 0
    for entry in _stacks(visible):
        if entry.get("name", "").lower() == key:
            total += int(entry.get("count", 0))
    return total


def has_item(visible: dict, name: str) -> bool:
    """True when at least one copy is in the inventory."""
    return item_count(visible, name) > 0


def add_item(visible: dict, name: str, count: int = 1) -> None:
    """Add `count` copies, merging into an existing stack when possible."""
    if count <= 0:
        raise ValueError(f"add_item count must be > 0, got {count!r}")
    key = (name or "").lower()
    for entry in _stacks(visible):
        if entry.get("name", "").lower() == key:
            entry["count"] = int(entry.get("count", 0)) + count
            return
    _stacks(visible).append({"name": key, "count": count})


def remove_item(visible: dict, name: str, count: int = 1) -> bool:
    """Remove `count` copies. False (and no change) when there are too few."""
    if count <= 0:
        raise ValueError(f"remove_item count must be > 0, got {count!r}")
    key = (name or "").lower()
    inventory = _stacks(visible)
    if item_count(visible, key) < count:
        return False

    left = count
    kept: list[dict] = []
    for entry in inventory:
        if left <= 0 or entry.get("name", "").lower() != key:
            kept.append(entry)
            continue
        have = int(entry.get("count", 0))
        take = min(have, left)
        left -= take
        have -= take
        if have > 0:
            kept.append({"name": entry.get("name"), "count": have})
    inventory[:] = kept
    return True


# ---------------------------------------------------------------------
# What can be sold
# ---------------------------------------------------------------------

def is_sellable(item: str) -> bool:
    """True when trade.sell_price knows a base price for this item."""
    return item in trade.BASE_PRICES or item in trade.LOOT_PRICES


def sellable_items(visible: dict) -> list[str]:
    """Distinct inventory names a trader would buy, sorted.

    Items without a price (berries, mushrooms, ...) are skipped: they show
    up in the inventory, but nobody pays for them.
    """
    names: list[str] = []
    for entry in _stacks(visible):
        if int(entry.get("count", 0)) <= 0:
            continue
        name = (entry.get("name") or "").lower()
        if name and name not in names and is_sellable(name):
            names.append(name)
    return sorted(names)


# ---------------------------------------------------------------------
# Price composition (§35 + §16 + npc.py trade bonus)
# ---------------------------------------------------------------------

def compose(base: int, modifiers: Iterable[Modifier]) -> int:
    """floor(base * m1 * m2 * ...) with exact fractions.

    Fraction(str(1.25)) is 5/4 exactly, so the floor never depends on
    binary float representation.
    """
    value = Fraction(base)
    for modifier in modifiers:
        value *= Fraction(str(modifier))
    return math.floor(value)


def buy_price(
    item: str,
    *,
    location: Modifier = DEFAULT_MODIFIER,
    reputation: Modifier = DEFAULT_MODIFIER,
    trade_bonus: Modifier = DEFAULT_MODIFIER,
) -> int:
    """Price Burt pays: floor(base * location * reputation * trade).

    KeyError when `item` is not in trade.BASE_PRICES — nobody sells it.
    """
    base = trade.BASE_PRICES[item]
    return compose(base, (location, reputation, trade_bonus))


def sell_price(
    item: str,
    *,
    location: Modifier = DEFAULT_MODIFIER,
    reputation: Modifier = DEFAULT_MODIFIER,
    trade_bonus: Modifier = DEFAULT_MODIFIER,
) -> int:
    """Price Burt gets: floor(floor(base * 0.5) * modifiers).

    §35: the half of the base price is floored first, then modified.
    KeyError when no base price is known.
    """
    if item in trade.BASE_PRICES:
        base = trade.BASE_PRICES[item]
    elif item in trade.LOOT_PRICES:
        base = trade.LOOT_PRICES[item]
    else:
        raise KeyError(item)
    half = math.floor(Fraction(base) / 2)
    return compose(half, (location, reputation, trade_bonus))


# ---------------------------------------------------------------------
# Location modifier (§35): one roll per node, cached for the session
# ---------------------------------------------------------------------

def modifier_for_node(
    hidden: dict,
    node_id: str,
    rng: Callable[[], int],
) -> float:
    """Roll the location price modifier once per node and cache it.

    Cache lives in hidden["prices_by_node"][node_id]; the value of the
    current node is mirrored into hidden["price_modifier"] so that debug
    output can read it without knowing the node id.
    """
    cache = hidden.setdefault("prices_by_node", {})
    if not isinstance(cache, dict):
        cache = {}
        hidden["prices_by_node"] = cache

    if node_id not in cache:
        cache[node_id] = trade.roll_location_price_modifier(rng)
    value = cache[node_id]
    hidden["price_modifier"] = value
    return value


def cached_modifier(hidden: dict, node_id: str) -> float:
    """Already rolled modifier of a node (1.0 when never rolled).

    Never rolls a die: safe to call while building a menu.
    """
    cache = hidden.get("prices_by_node") or {}
    if not isinstance(cache, dict):
        return DEFAULT_MODIFIER
    value: Any = cache.get(node_id)
    if value is None:
        return DEFAULT_MODIFIER
    return float(value)