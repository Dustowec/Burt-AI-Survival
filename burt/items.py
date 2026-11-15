"""Item registry - search items only. Full unification is a separate task."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    display: str
    category: str  # "food" | "junk" | "weapon"
    hp_restore: int = 0


ITEMS: dict[str, Item] = {
    # Food - search
    "berries":    Item("berries",    "Berries",    "food", hp_restore=1),
    "mushrooms":  Item("mushrooms",  "Mushrooms",  "food", hp_restore=1),
    "roots":      Item("roots",      "Roots",      "food", hp_restore=1),
    "moss":       Item("moss",       "Moss",       "food", hp_restore=1),
    "fish":       Item("fish",       "Fish",       "food", hp_restore=1),
    # Food - existing (MUST be here, else has_food breaks for starting bread)
    "bread":      Item("bread",      "Bread",      "food", hp_restore=1),
    "food":       Item("food",       "Food",       "food", hp_restore=1),
    "dried_fish": Item("dried_fish", "Dried fish", "food", hp_restore=1),
    # Junk - search
    "shell":      Item("shell",      "Shell",      "junk"),
    # Weapons - search
    "club":              Item("club",              "Club",              "weapon"),
    "low_quality_sword": Item("low_quality_sword", "Low-quality sword", "weapon"),
    "spear":             Item("spear",             "Spear",             "weapon"),
}


def is_food(name: str) -> bool:
    it = ITEMS.get((name or "").lower())
    return it is not None and it.category == "food"


def is_junk(name: str) -> bool:
    it = ITEMS.get((name or "").lower())
    return it is not None and it.category == "junk"
