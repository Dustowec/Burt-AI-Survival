"""burt/npc.py — Dialogue engine for NPC interactions.

Public API:
    load_replicas(path: str) -> dict
    resolve_heretic_deception(roll: int) -> bool

    class Outcome(Enum)
    class Result(dataclass)
    class Session
    class DialogueEngine
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any


logger = logging.getLogger(__name__)


# ============================================================
# 1. BASIC TYPES
# ============================================================

class Outcome(Enum):
    FAIL = 0
    NEUTRAL = 1
    SUCCESS = 2


@dataclass
class Result:
    outcome: Outcome
    text: str
    bonus: dict | None
    hp_change: int
    coins_change: int
    became_angry: bool


# ============================================================
# 2. LOADERS
# ============================================================

def load_replicas(path: str) -> dict:
    """Reads replicas.json and returns {\"roles\": {...}, \"events\": {...}}."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_heretic_deception(roll: int) -> bool:
    """K2, §33: success if roll >= 3. No second roll."""
    return roll >= 3


# ============================================================
# 3. CATEGORY MAPS
# ============================================================

LIE_FORBIDDEN: frozenset[str] = frozenset({"child", "peasant", "peasant_woman"})

_ROLE_CATEGORIES: dict[str, set[str]] = {
    "elder":        {"truth", "polite", "lie", "threat", "charm",  "trade", "bribe", "quest", "exit"},
    "peasant":      {"truth", "polite", "threat",                 "exit"},
    "peasant_woman":{"truth", "polite", "charm",                  "exit"},
    "blacksmith":   {"truth", "polite", "lie",    "trade",        "quest", "exit"},
    "merchant":     {"truth", "polite", "lie",    "trade", "bribe", "quest", "exit"},
    "guard":        {"truth", "polite", "lie",    "threat", "bribe", "quest", "exit"},
    "fisherman":    {"truth", "polite", "lie",    "trade",        "quest", "exit"},
    "child":        {"truth", "polite", "charm",                   "exit"},
    "veteran":      {"truth", "polite", "lie",    "threat",        "train", "quest", "exit"},
    "cleric":       {"truth", "polite", "lie", "threat",            "train", "quest", "exit"},
    "necromancer":  {"truth", "polite", "lie",    "trade", "bribe", "train", "quest", "exit"},
    "tavernkeeper": {"truth", "polite", "lie",    "trade", "bribe",        "quest", "exit"},
    "mage_event":   {"truth", "polite", "trade", "train", "bribe", "deception", "exit"},
    "preacher_event":{"truth", "polite",                          "deception", "exit"},
}


# ============================================================
# 4. BONUS TABLE
# ============================================================

BRIBE_BASE_COST: int = 4
NO_COINS_ROLES: frozenset[str] = frozenset({"child", "peasant", "peasant_woman"})

BONUS_BY_CATEGORY: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "trade":  [("trade_discount", {"percent": 20})],
    "quest":  [("quest_discount", {}), ("quest_reward", {})],
    "bribe":  [("bribe_discount", {"amount": 2}), ("bribe_accept", {})],
    "truth":  [("coins", {"amount": 2}), ("rumor", {}), ("item", {})],
    "polite": [("coins", {"amount": 2}), ("rumor", {}), ("item", {})],
    "charm":  [("coins", {"amount": 2}), ("rumor", {}), ("item", {})],
    "threat": [("extra_info", {}), ("extra_goods", {})],
    "train":  [("skill", {"amount": 1})],
}


# ---------------------------------------------------------------------
# 4a. BONUS TEXT (new_bug §4)
# ---------------------------------------------------------------------

# Raw bonus keys never reach the LLM: every type maps to a human line.
BONUS_TEXTS: dict[str, str] = {
    "bribe_accept": "The bribe succeeds.",
    "bribe_discount": "The bribe succeeds, and the price softens.",
    "trade_discount": "The trader lowers the price.",
    "skill": "You feel your skill grow.",
    "food": "They share some bread.",
    "rumor": "They tell you a rumor.",
    "extra_info": "They let slip something useful.",
    "extra_goods": "They mention where to find better goods.",
    "quest_discount": "They seem pleased with you.",
    "quest_reward": "They seem pleased with you.",
    "item": "They have nothing to spare right now.",
}

UNKNOWN_BONUS_TEXT: str = "The conversation shifts in your favor."


def bonus_text(bonus: dict | None) -> str:
    """Human-readable line for a dialogue bonus (never the raw key).

    Unknown types do not break the game: they get a neutral line and a
    WARN in the log.
    """
    if not bonus:
        return ""
    typ = bonus.get("type", "")
    if typ == "coins":
        amount = int(bonus.get("amount", 2))
        return f"You get {amount} coins."
    text = BONUS_TEXTS.get(typ)
    if text is not None:
        return text
    logger.warning("Unknown dialogue bonus type: %r", typ)
    return UNKNOWN_BONUS_TEXT


# ============================================================
# 5. DIALOGUE ENGINE
# ============================================================

class DialogueEngine:
    """Manages NPC dialogue data and creates Session instances."""

    def __init__(self, replicas: dict) -> None:
        self._replicas = replicas

    def available_categories(self, role_key: str) -> set[str]:
        """Returns the set of available categories for a role/event."""
        cats = set(_ROLE_CATEGORIES.get(role_key, {"truth", "polite", "exit"}))

        # lie is available to everyone not in LIE_FORBIDDEN
        if role_key not in LIE_FORBIDDEN:
            cats.add("lie")

        return cats

    def event_line(self, role_key: str, pool: str) -> str:
        """Pick one line from events.<role_key>.<pool> ('' when absent).

        Used by the preacher event, whose pools are not dialogue topics:
        intro / curse / nothing / blessing.
        """
        data = self._replicas.get("events", {}).get(role_key, {})
        lines = data.get(pool) or []
        return random.choice(lines) if lines else ""

    def start(self, role_key: str, *,
              hp: int = 10, coins: int = 100,
              reputation_bonus: int = 0) -> "Session":
        """Creates a Session for the given role or event."""
        # Look in roles first, then events
        if role_key not in self._replicas.get("roles", {}):
            if role_key not in self._replicas.get("events", {}):
                raise KeyError(f"Unknown role/event: {role_key!r}")
            is_event = True
        else:
            is_event = False
        return Session(self, role_key, hp=hp, coins=coins,
                       reputation_bonus=reputation_bonus, is_event=is_event)


# ============================================================
# 6. SESSION
# ============================================================

class Session:
    """A single dialogue session with an NPC."""

    def __init__(self, engine: DialogueEngine, role_key: str, *,
                 hp: int = 10, coins: int = 100,
                 reputation_bonus: int = 0,
                 is_event: bool = False) -> None:
        self._engine = engine
        self.role_key = role_key
        self.hp = hp
        self.coins = coins
        self.is_angry = False
        self.turn = 0
        self.anger_lock_until: int | None = None
        self.bonus_used = False
        self.quest_state = "available"
        self._train_done = False
        self._is_event = is_event

    def can_exit(self) -> bool:
        if self.is_angry:
            return False
        if self.anger_lock_until is not None and self.turn < self.anger_lock_until:
            return False
        return True

    def advance_turn(self) -> None:
        self.turn += 1
        if self.anger_lock_until is not None and self.turn >= self.anger_lock_until:
            self.is_angry = False
            self.anger_lock_until = None

    def set_quest_state(self, state: str) -> None:
        self.quest_state = state

    # ---- text selection ----

    def _pick_pool(self, category: str, pool_name: str) -> str:
        """Pick random text from {category}_{pool_name} or {pool_name}."""
        role_data = self._get_role_data()
        for candidate in (f"{category}_{pool_name}", pool_name):
            lines = role_data.get(candidate)
            if lines:
                return random.choice(lines)
        return ""

    def _get_role_data(self) -> dict:
        if self._is_event:
            return self._engine._replicas.get("events", {}).get(self.role_key, {})
        return self._engine._replicas.get("roles", {}).get(self.role_key, {})

    # ---- bonus logic ----

    def _pick_bonus(self, category: str) -> dict | None:
        if category == "quest" and self.quest_state != "available":
            return None
        options = BONUS_BY_CATEGORY.get(category)
        if not options:
            return None
        typ, extra = random.choice(options)
        # For poor/child roles, kind-word bonuses fallback to food/nothing
        if self.role_key in NO_COINS_ROLES and category in ("truth", "polite", "charm"):
            return {"type": "food"}
        # Only coins fallback for poor/child roles
        if typ == "coins" and self.role_key in NO_COINS_ROLES:
            return {"type": "food"}
        return {"type": typ, **extra}

    # ---- dice resolution ----

    @staticmethod
    def _resolve_outcome(roll: int, modifier: int = 0) -> Outcome:
        pair = 0 if roll <= 2 else (1 if roll <= 4 else 2)
        pair = max(0, min(2, pair + modifier))
        return (Outcome.FAIL, Outcome.NEUTRAL, Outcome.SUCCESS)[pair]

    # ---- main entry ----

    def say(self, category: str, roll: int | None = None,
            second_roll: int | None = None,
            modifier: int = 0) -> Result:

        # --- VALIDATE ---
        assert category in self._engine.available_categories(self.role_key), \
            f"Category {category!r} not available for role {self.role_key!r}"

        # Every reply is one dialogue turn. The anger lock counts these
        # replies; without the tick it never expires and dialog_exit
        # stays hidden forever (found by the live 80-step run).
        self.advance_turn()

        # --- EXIT ---
        if category == "exit":
            return Result(
                outcome=Outcome.SUCCESS,
                text=self._pick_pool("exit", "exit_early"),
                bonus=None, hp_change=0, coins_change=0,
                became_angry=False,
            )

        # --- TRAIN ---
        if category == "train":
            if self._train_done:
                text = self._pick_pool("train", "train_done")
                return Result(
                    outcome=Outcome.SUCCESS, text=text, bonus=None,
                    hp_change=0, coins_change=0, became_angry=False,
                )
            # Если дошли сюда — обычная success-ветка с bonus skill

        # --- QUEST ---
        if category == "quest":
            pool_map = {
                "none": "quest_none",
                "available": "quest_give",
                "in_progress": "quest_already",
            }
            pool = pool_map.get(self.quest_state, "quest_none")
            outcome = self._resolve_outcome(roll, modifier)
            text = self._pick_pool("quest", pool)
            bonus = None
            if outcome == Outcome.SUCCESS and second_roll is not None and second_roll <= 3 and not self.bonus_used:
                if self.quest_state == "available":
                    bonus = self._pick_bonus("quest")
                    if bonus is not None:
                        self.bonus_used = True
            return Result(
                outcome=outcome,
                text=text, bonus=bonus,
                hp_change=0, coins_change=0, became_angry=False,
            )

        # --- DECEPTION (heretic) ---
        if category == "deception":
            success = resolve_heretic_deception(roll or 1)
            outcome = Outcome.SUCCESS if success else Outcome.FAIL
            text = self._pick_pool("deception", outcome.name.lower())
            return Result(
                outcome=outcome, text=text, bonus=None,
                hp_change=0, coins_change=0, became_angry=False,
            )

        # --- NORMAL DICE RESOLUTION ---
        assert roll is not None, f"roll is required for category {category!r}"
        outcome = self._resolve_outcome(roll, modifier)

        # --- EVENT OUTCOME MAP (preacher_event: curse/nothing/blessing) ---
        if self._is_event and self.role_key == "preacher_event":
            event_pool = {"curse", "nothing", "blessing"}
            if outcome.name.lower() in event_pool:
                text = self._pick_pool("event", outcome.name.lower())
                return Result(
                    outcome=outcome, text=text, bonus=None,
                    hp_change=0, coins_change=0, became_angry=False,
                )

        # --- NEUTRAL ---
        if outcome == Outcome.NEUTRAL:
            text = self._pick_pool(category, "neutral")
            return Result(
                outcome=Outcome.NEUTRAL, text=text, bonus=None,
                hp_change=0, coins_change=0, became_angry=False,
            )

        # --- FAIL ---
        if outcome == Outcome.FAIL:
            if second_roll is not None and second_roll <= 3:
                # penalty: -1 HP + angry
                hp_change = -1
                self.hp += hp_change
                became_angry = True
                self.is_angry = True
                self.anger_lock_until = self.turn + 2
                text = self._pick_pool(category, "fail_angry")
            else:
                # plain refusal (second_roll is None or 4-6)
                hp_change = 0
                became_angry = False
                text = self._pick_pool(category, "fail")
            return Result(
                outcome=Outcome.FAIL, text=text, bonus=None,
                hp_change=hp_change, coins_change=0,
                became_angry=became_angry,
            )

        # --- SUCCESS ---
        assert outcome == Outcome.SUCCESS

        # Determine text pool
        if second_roll is not None and second_roll <= 3:
            text = self._pick_pool(category, "success_bonus")
        else:
            text = self._pick_pool(category, "success")

        # Determine bonus
        bonus = None
        if second_roll is not None and second_roll <= 3 and not self.bonus_used:
            bonus = self._pick_bonus(category)
            if bonus is not None:
                self.bonus_used = True
                if category == "train":
                    self._train_done = True

        # Bribe coin handling
        coins_change = 0
        if category == "bribe" and outcome == Outcome.SUCCESS:
            if bonus is not None and bonus.get("type") == "bribe_discount":
                coins_change = -2
            else:
                coins_change = -BRIBE_BASE_COST
            self.coins += coins_change

        return Result(
            outcome=Outcome.SUCCESS, text=text, bonus=bonus,
            hp_change=0, coins_change=coins_change,
            became_angry=False,
        )
