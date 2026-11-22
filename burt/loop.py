"""Loop — section 26 spec v0.7.0.

Synchronous game-loop core: build_menu, parse_choice, execute_action.

Combat delegates to burt.combat.resolve_round (§23):
- combat opening (ambush free strike) is resolved in _start_combat via
  combat.resolve_free_strike, on the very step that triggered combat,
  before the menu is built and before the LLM narrates;
- CombatState is stored as dict in hidden["combat"];
- BurtStats is assembled from visible + hidden["spells"];
- after each round, hidden["combat"] is written back (or None on end);
- hp/mp synced visible <-> hidden;
- [COMBAT] report appended to events while combat is ongoing.

All docstrings/comments in English. No Cyrillic literals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from burt import world
from burt import sensory
from burt import hunger
from burt import sleep as sleep_mod
from burt import dice
from burt import spawn
from burt import combat
from burt import npc_spawn
from burt import quests
from burt import faith
from burt import npc_combat
from burt import reputation
from burt import loot
from burt import search as search_mod
from burt import items
from burt import map as map_mod
from burt import economy
from burt import progression
from burt import trade
from burt import weapons
from burt import skills
from burt import magic
from burt import state as state_mod
from burt import events
from burt.combat import CombatState, BurtStats
from burt.bestiary import ENEMIES
from burt.dice import (
    resolve_micro_event, calculate_micro_damage,
    resolve_movement_event, resolve_bad_movement_event,
)
from burt.npc import DialogueEngine, Outcome, bonus_text


@dataclass
class Action:
    """One menu entry the LLM can choose."""
    key: str
    label: str
    cost_free: bool = False
    target_id: str | None = None
    item: str | None = None


@dataclass
class ActionResult:
    """Result of executing one action."""
    events: list[str] = field(default_factory=list)
    new_hp: int | None = None
    game_over: bool = False
    search_result: str | None = None
    direction_moved: str | None = None
    # §13: the preacher dialogue is one action; its effect starts after it.
    skip_effect_tick: bool = False
    # §11: world event of this turn, injected as the first line of the
    # next prompt (reason first, then the sensory report).
    inject: str | None = None


@dataclass
class CombatStart:
    """Events emitted when combat opens, ambush free strike included."""
    events: list[str] = field(default_factory=list)
    game_over: bool = False


# Location name mapping
_LOCATION_NAMES = {
    'crossroads': 'Crossroads',
    'thicket': 'Thicket',
    'forest': 'Forest',
    'field': 'Field',
    'steppe': 'Steppe',
    'swamp': 'Swamp',
    'river': 'River',
    'road': 'Road',
    'village': 'Village',
    'temple': 'Temple',
    'dungeon': 'Dungeon',
}

DIRECTIONS = ("north", "east", "south", "west")
COMBAT_ACTIONS = frozenset({"attack", "block", "flee"})
SLEEP_THRESHOLD = 20
CRITICAL_HP_RATIO = 0.25

# §23: locations where entering can trigger an ambush/encounter.
_ENCOUNTER_LOCATIONS = {
    "forest": "forest",
    "dungeon": "dungeon",
    "field": "field",
    "steppe": "steppe",
    "swamp": "swamp",
}
_AMBUSH_LOCATION = "thicket"  # §32: ambush at thicket
_COMBAT_HEADER = "[COMBAT]"  # first line of sensory.format_combat_report

# §26: free tools. A tool never advances the day counter.
TOOL_KEYS: frozenset[str] = frozenset({
    "scroll", "inventory", "status", "remember", "diary", "map",
})

_TOOL_LABELS: dict[str, str] = {
    "scroll": "Quest scroll",
    "inventory": "Inventory",
    "status": "Status",
    "remember": "Remember",
    "diary": "Diary",
    "map": "Map",
}

# §11: why Burt did not get where he was going. Reason only, no numbers.
_MICRO_EVENT_TEXT = {
    "stone": "You stumbled over a sharp stone.",
    "tree": "You hit a fallen log.",
    "lightning": "Lightning struck you.",
    "god_wrath": "The gods punish you.",
}
_AMBUSH_TEXT = "You fell into an ambush."
_BAD_EVENT_TEXT = {
    "trap": "You stepped into a trap.",
    "sprain": "You twisted your ankle.",
}


# new_bug §3: blessing text depends on the REAL delta.
BLESSING_RESTORES = "A blessing restores your vitality."
BLESSING_WASHES = "A blessing washes over you."

# new_bug §8: one re-ask when the model returns no valid choice.
INVALID_CHOICE_KICK = (
    "Hey, you bumpkin! What are you doing?! "
    "Think again and pick a valid action from the menu."
)

# §9/§16: replica keys of spawned non-role NPCs mapped to a reputation role.
# "mage_event" teaches elements (§9) but reputation is tracked per §16 role.
_REP_ROLE_ALIAS = {
    "mage_event": "mage",
    "preacher_event": "cleric",
}

# npc.py bonus "trade_discount" percent -> multiplier (20% -> 0.8).
_TRADE_DISCOUNT_DEFAULT = 20

# П.1: Словарь синонимов для парсинга текста.
_ACTION_SYNONYMS = {
    "go_north": ["north", "walk north", "step north", "head north", "move north"],
    "go_east": ["east", "walk east", "step east", "head east", "move east"],
    "go_south": ["south", "walk south", "step south", "head south", "move south"],
    "go_west": ["west", "walk west", "step west", "head west", "move west"],
    "osmotret": ["look around", "check my surroundings", "look about", "examine surroundings"],
    "search": ["search", "rummage", "look for", "find", "scavenge"],
    "eat_food": ["eat", "consume bread", "take the bread", "munch"],
    "drink_water": ["drink", "take water"],
    "sleep": ["sleep", "rest", "close my eyes"],
    "inventory": ["inventory", "check inventory", "my things",
                  "my belongings", "what do i carry"],
    "status": ["status", "check my state", "how do i feel",
               "check myself"],
    "remember": ["remember", "memory", "recall", "past life"],
    "diary": ["diary", "journal", "last entry", "my notes"],
}


def _append_tools(
    actions: list[Action],
    keys: tuple[str, ...] = ("scroll", "inventory", "status",
                             "remember", "diary"),
) -> list[Action]:
    """§26: free tools go at the end, so old menu indices stay stable."""
    for key in keys:
        actions.append(Action(key=key, label=_TOOL_LABELS[key],
                              cost_free=True))
    return actions


def build_menu(visible: dict, state: dict, *,
               dialogue_engine: DialogueEngine | None = None) -> list[Action]:
    """Build available actions from current game state."""
    hidden = state.get("hidden", {})
    mode = hidden.get("current_mode", "exploring")

    if mode == "combat":
        return _build_combat_menu(visible, state)

    if mode == "dialog":
        return _build_dialog_menu(visible, state, dialogue_engine)

    # ── Talk actions (§32): NPCs of this node, next to exits and search.
    talk_actions: list[Action] = []
    if dialogue_engine is not None:
        for role_key in hidden.get("npcs_here", []):
            # §34: a hostile resident is approached, not talked to; the
            # first approach starts combat (enemy initiative).
            if npc_combat.is_hostile(state, role_key):
                talk_actions.append(Action(
                    key=f"talk_to_{role_key}",
                    label=f"Approach the {role_key}",
                ))
                continue
            if not faith.can_talk_to(state, role_key):
                continue
            talk_actions.append(
                Action(key=f"talk_to_{role_key}",
                       label=f"Talk to {role_key}")
            )

    # ── Micro-location exits (§11) ──────────────────────────
    micro = hidden.get("micro_location")
    if micro and micro.get("active"):
        actions: list[Action] = []
        actions.append(Action(key="go_back", label="Go back"))
        actions.append(Action(key="go_forward", label="Go forward"))
        return actions

    # ─── TZ-9: Encounter menu (revealed pending encounter) ───
    if hidden.get("encounter_revealed") is True:
        if _is_pending_encounter_valid(hidden):
            return _build_encounter_menu(hidden)
        else:
            _clear_pending_encounter(hidden)

    actions: list[Action] = []
    last = hidden.get("last_action")
    same_count = hidden.get("same_action_count", 0)
    # Hide osmotret if repeated 2+ times — force the model to choose differently
    if last != "osmotret" or same_count < 2:
        actions.append(Action(key="osmotret", label="Look around"))

    exits = visible.get("location", {}).get("exits", [])
    for d in DIRECTIONS:
        if d in exits:
            actions.append(Action(key=f"go_{d}", label=f"Go {d}"))

    actions.append(Action(key="search", label="Search"))
    actions.append(Action(key="scroll", label="Quest scroll", cost_free=True))

    step = hidden.get("step", 0)
    if _sleep_available(visible, hidden):
        actions.append(Action(key="sleep", label="Sleep"))
        if step >= sleep_mod.SLEEP_AVAILABLE_FROM:
            actions.append(Action(
                key="write_diary_and_go_sleep",
                label="Write diary and go to sleep",
            ))

    inventory = visible.get("inventory", [])
    has_food = False
    has_water = False
    for item in inventory:
        name = item.get("name", "").lower()
        if items.is_food(name):
            has_food = True
        if name in ("water", "waterskin", "large_waterskin"):
            has_water = True
    if has_food:
        actions.append(Action(key="eat_food", label="Eat food"))
    if has_water:
        actions.append(Action(key="drink_water", label="Drink water"))

    actions.extend(talk_actions)
    return _append_tools(
        actions, ("inventory", "status", "remember", "diary", "map"),
    )


def _build_dialog_menu(visible: dict, state: dict,
                       engine: DialogueEngine | None) -> list[Action]:
    """Build dialog menu from engine.available_categories(role_key)."""
    if engine is None:
        return [Action(key="dialog_exit", label="Leave conversation")]
    hidden = state.get("hidden", {})
    ds = hidden.get("dialog_state")
    if ds is None:
        return []
    # §35: while the shop is open, the trader shows goods, not topics.
    if ds.get("shop"):
        return _build_shop_menu(visible, state, ds)
    role_key = ds.get("role_key", "")
    cats = engine.available_categories(role_key)
    actions: list[Action] = []
    for cat in sorted(cats):
        if cat == "exit":
            # Exit hidden when angry and lock still active
            is_angry = ds.get("is_angry", False)
            lock_until = ds.get("anger_lock_until")
            turn = ds.get("turn", 0)
            if is_angry and (lock_until is None or turn < lock_until):
                continue
            actions.append(Action(key="dialog_exit", label="Leave conversation"))
        else:
            actions.append(Action(key=f"dialog_{cat}", label=cat.capitalize()))

    # §33/§34: the K3 donation and the hostile act.
    if faith.donate_available(state, role_key):
        actions.append(Action(key="dialog_donate", label="Donate all coin"))
    if role_key in faith.RESIDENT_ROLES:
        actions.append(Action(key="dialog_attack", label="Attack (kill)"))
    return _append_tools(actions)


def _rep_role(role_key: str) -> str:
    """Reputation role behind a replica key (§16)."""
    return _REP_ROLE_ALIAS.get(role_key, role_key)


def _shop_role(ds: dict) -> str:
    """Catalog role of the open shop (§35 ROLE_SELLS key)."""
    return ds.get("shop_role") or _rep_role(ds.get("role_key", ""))


def _has_staff(visible: dict, hidden: dict) -> bool:
    """§9: a staff is either in the inventory or flagged in hidden."""
    return bool(hidden.get("has_staff")) or economy.has_item(visible, "staff")


def _display_name(item: str) -> str:
    """Human-readable item name for menu labels and events."""
    known = items.ITEMS.get(item)
    if known is not None:
        return known.display
    return item.replace("_", " ").capitalize()


def _price_context(state: dict, ds: dict) -> dict:
    """Three modifiers of §35 + §16 + npc.py trade bonus."""
    hidden = state.setdefault("hidden", {})
    node_id = hidden.get("current_node_id", "start")
    role = _shop_role(ds)
    shop = ds.get("shop") or {}
    return {
        "location": economy.cached_modifier(hidden, node_id),
        "reputation": reputation.price_modifier(reputation.get(state, role)),
        "trade_bonus": float(shop.get("bonus", 1.0)),
    }


def _build_shop_menu(visible: dict, state: dict, ds: dict) -> list[Action]:
    """§35: buy list of the role + sell list of the inventory."""
    ctx = _price_context(state, ds)
    role = _shop_role(ds)
    actions: list[Action] = []

    for item in sorted(trade.ROLE_SELLS.get(role, frozenset())):
        price = economy.buy_price(item, **ctx)
        actions.append(Action(
            key=f"dialog_buy_{item}",
            label=f"Buy {_display_name(item)} ({price} coin)",
            item=item,
        ))

    for item in economy.sellable_items(visible):
        price = economy.sell_price(item, **ctx)
        actions.append(Action(
            key=f"dialog_sell_{item}",
            label=f"Sell {_display_name(item)} ({price} coin)",
            item=item,
        ))

    actions.append(Action(key="dialog_trade_close", label="Done trading"))
    return actions


def _build_combat_menu(visible: dict, state: dict) -> list[Action]:
    """Build combat menu from hidden["combat"] (CombatState dict)."""
    hidden = state.get("hidden", {})
    combat_dict = hidden.get("combat")
    if combat_dict is None:
        return []
    try:
        combat_state = CombatState.from_dict(combat_dict)
    except (KeyError, ValueError, TypeError):
        return []

    actions: list[Action] = []
    any_alive = False
    for enemy in combat_state.enemies:
        if not enemy.alive:
            continue
        any_alive = True
        t = ENEMIES.get(enemy.key)
        name = t.name if t is not None else enemy.key
        actions.append(Action(
            key=f"attack_{enemy.id}",
            label=f"Attack {name}",
            target_id=enemy.id,
        ))
    if any_alive:
        actions.append(Action(key="block", label="Block"))
        actions.append(Action(key="flee", label="Flee"))
        burt = _build_burt_stats(visible, hidden)
        if burt.spells_available:
            actions.append(Action(key="cast", label="Cast"))
    return _append_tools(actions)


def _build_encounter_menu(hidden: dict) -> list[Action]:
    """Build encounter menu: attack enemies + go_away_to exits."""
    pe = hidden.get("pending_encounter")
    if not isinstance(pe, dict):
        return []
    enemy_keys = pe.get("enemy_keys", [])
    if not enemy_keys:
        return []

    preview = _preview_pending_enemies(enemy_keys)
    actions: list[Action] = []

    for e in preview:
        actions.append(Action(
            key=f"attack_{e['id']}",
            label=f"Attack {e['display']} ({e['id']})",
            target_id=e["id"],
        ))

    # Add go_away_to for each exit
    graph = hidden.get("location_graph", {})
    node_id = hidden.get("current_node_id", "start")
    node = graph.get(node_id, {})
    exits = node.get("exits", {})
    for d in DIRECTIONS:
        if exits.get(d):
            actions.append(Action(
                key=f"go_away_to_{d}",
                label=f"Go away to {d}",
            ))

    return actions


def _execute_encounter_attack(
    action: Action, hidden: dict, visible: dict, rng,
) -> ActionResult:
    """Handle attack_{enemy_id} from revealed encounter."""
    target_id = action.target_id or action.key[len("attack_"):]

    pe = hidden.get("pending_encounter")
    if not isinstance(pe, dict):
        return error_result("no pending encounter")

    enemy_keys = pe.get("enemy_keys", [])
    if not enemy_keys:
        return error_result("no pending encounter")

    # Validate target against preview
    preview = _preview_pending_enemies(enemy_keys)
    valid_ids = {e["id"] for e in preview}
    if target_id not in valid_ids:
        return error_result(f"unknown enemy: {target_id}")

    # Start combat with Burt initiative
    _clear_pending_encounter(hidden)
    hidden["step"] = hidden.get("step", 0) + 1
    started = _start_combat(enemy_keys, "burt", hidden, visible, rng)
    return ActionResult(events=started.events, game_over=started.game_over)


def _execute_go_away(
    action: Action, hidden: dict, visible: dict, rng,
) -> ActionResult:
    """Handle go_away_to_{direction} from revealed encounter."""
    direction = action.key[len("go_away_to_"):]
    if direction not in DIRECTIONS:
        return error_result(f"Invalid direction: {direction}")

    graph = hidden.get("location_graph", {})
    current = hidden.get("current_node_id", "start")
    if current not in graph:
        return error_result("current node missing from graph")
    node = graph[current]
    if "exits" in node:
        next_id = node["exits"].get(direction)
    else:
        next_id = node.get(direction)
    if not next_id or next_id not in graph:
        return error_result(f"no exit {direction}")

    # Clear pending before movement and record last_action like normal go.
    _clear_pending_encounter(hidden)
    hidden["last_action"] = action.key
    hidden["same_action_count"] = 1

    # Execute normal movement (one step, same as go_)
    move_roll = rng()
    move_result = dice.resolve_movement(move_roll).result
    if move_result in ("fail_bad", "fail"):
        return _handle_movement_failure(
            direction, move_result, hidden, visible, rng,
        )

    hidden["current_node_id"] = next_id

    loc_type, started = _arrive_at_node(
        next_id, graph, hidden, visible, rng,
    )

    hidden["step"] = hidden.get("step", 0) + 1

    if started is not None:
        return ActionResult(
            events=started.events,
            game_over=started.game_over,
            direction_moved=direction,
        )

    if move_roll in (5, 6):
        ev = resolve_movement_event(
            move_roll,
            level=visible.get("level", 1),
            rng=rng,
            hp_max=visible.get("hp_max", 10),
            mp_max=visible.get("mp_max", 3),
        )
        return ActionResult(
            events=_apply_positive_movement_event(ev, visible, hidden, rng),
            direction_moved=direction,
        )

    return ActionResult(
        events=[sensory.format_sensory_report(visible)],
        direction_moved=direction,
    )


def _match_choice_value(choice: str, actions: list[Action]) -> Action | None:
    """Strict match of one CHOICE value: index, key, label, substring."""
    # numeric index
    try:
        idx = int(choice)
        if 0 <= idx < len(actions):
            return actions[idx]
    except ValueError:
        pass

    choice_lower = choice.lower()

    # action key (e.g. "attack_wolf_1")
    for action in actions:
        if action.key.lower() == choice_lower:
            return action

    # label match (e.g. "Attack wolf")
    for action in actions:
        if action.label.lower() == choice_lower:
            return action

    # substring: choice contains key or label
    for action in actions:
        if action.key.lower() in choice_lower:
            return action
        if action.label.lower() in choice_lower:
            return action

    return None


def _match_mention(text: str, actions: list[Action]) -> Action | None:
    """Free-text fallback: label/key/synonym anywhere; LAST mention wins."""
    text_lower = text.lower()
    best_idx = -1
    best_action = None

    for action in actions:
        candidates = [action.label.lower(), action.key.lower()]
        if action.key in _ACTION_SYNONYMS:
            candidates.extend(_ACTION_SYNONYMS[action.key])

        for cand in candidates:
            if not cand:
                continue
            idx = text_lower.rfind(cand)
            if idx > best_idx:
                best_idx = idx
                best_action = action

    return best_action


def parse_choice(user_text: str, actions: list[Action]) -> Action:
    """Parse LLM response and return the chosen Action.

    Lenient parser kept for tests and as a fallback wrapper:
    1. Look for a line starting with "CHOICE:" (case-insensitive).
    2. Fallback: find any action label/key/synonym mentioned in text.
       If multiple mentioned, the LAST one (rfind) wins.
    3. Fallback: first action (index 0).
    """
    if not actions:
        return Action(key="osmotret", label="Look around")

    # 1. CHOICE: prefix
    for line in user_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CHOICE:"):
            choice = stripped[len("CHOICE:"):].strip()
            action = _match_choice_value(choice, actions)
            if action is not None:
                return action

    # 2. Fallback: label/key/synonym anywhere in text (LAST match wins)
    action = _match_mention(user_text, actions)
    if action is not None:
        return action

    # 3. Fallback: first action
    return actions[0]


def parse_choice_strict(
    user_text: str, actions: list[Action],
) -> tuple[Action | None, str]:
    """Strict parser for run_turn (new_bug §8).

    A response is valid only when it has a CHOICE line with a valid
    value. An explicit but invalid CHOICE is never silently replaced by
    prose: the caller re-asks the model once.

    Returns (action_or_None, reason). Empty reason on success.
    """
    if not actions:
        return None, "empty menu"

    for line in user_text.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("CHOICE:"):
            continue
        choice = stripped[len("CHOICE:"):].strip()
        if not choice:
            return None, "empty CHOICE"
        action = _match_choice_value(choice, actions)
        if action is None:
            return None, f"invalid CHOICE: {choice!r}"
        return action, ""

    # No CHOICE line at all — do not guess from prose.
    return None, "no CHOICE line"


def fallback_action(actions: list[Action]) -> Action:
    """Deterministic last resort (new_bug §8).

    block -> osmotret -> dialog_exit -> first menu action.
    """
    if not actions:
        return Action(key="osmotret", label="Look around")
    by_key = {a.key: a for a in actions}
    for key in ("block", "osmotret", "dialog_exit"):
        if key in by_key:
            return by_key[key]
    return actions[0]


def _apply_movement_event(ev, visible: dict, hidden: dict) -> str:
    """Apply a positive movement event, return the LLM-facing text.

    new_bug §3: a blessing only says "restores" when HP/MP really grew;
    at full HP/MP it says "washes over" and changes nothing.
    """
    if ev.event_type == "loot":
        wallet = visible.setdefault("wallet", {})
        wallet["coin"] = int(wallet.get("coin", 0)) + ev.coin
        return ev.description

    if ev.event_type == "blessing":
        hp_before = int(visible.get("hp", 10))
        mp_before = int(visible.get("mp", 3))
        hp_after = min(hp_before + ev.hp_restore, visible.get("hp_max", 10))
        mp_after = min(mp_before + ev.mp_restore, visible.get("mp_max", 3))
        visible["hp"] = hp_after
        visible["mp"] = mp_after
        hidden["hp_raw"] = hp_after
        hidden["mp_raw"] = mp_after
        healed = (hp_after - hp_before) + (mp_after - mp_before)
        return BLESSING_RESTORES if healed > 0 else BLESSING_WASHES

    return ev.description


def _apply_positive_movement_event(ev, visible: dict, hidden: dict,
                                   rng) -> list[str]:
    """Apply a §10 positive event, then roll the rare preacher spawn.

    Order matters: the preacher roll is the LAST die of the movement, so
    the existing dice order (movement, arrival, encounter, spawn, magic,
    blessing restore) is untouched.
    """
    result: list[str] = []
    text = _apply_movement_event(ev, visible, hidden)
    if text:
        result.append(text)
    if events.spawn_preacher(hidden, rng):
        result.append(events.PREACHER_ENCOUNTER_TEXT)
    result.append(sensory.format_sensory_report(visible))
    return result


def _apply_sleep_state(state: dict) -> None:
    """One night: voluntary and forced sleep share this exact effect set.

    new_bug §7: HP/MP to max, effects cleared, eat=False, day+1, step=0,
    room consumed, diary flags, no pending encounter, resurrection
    mercy renewed.
    """
    visible = state.setdefault("visible", {})
    hidden = state.setdefault("hidden", {})

    hp_max = visible.get("hp_max", 10)
    mp_max = visible.get("mp_max", 3)
    new_hp, new_mp, new_effects = sleep_mod.apply_sleep(hp_max, mp_max)
    visible["hp"] = new_hp
    visible["mp"] = new_mp
    visible["effects"] = new_effects
    hidden["effects_detail"] = []
    hidden["hp_raw"] = new_hp
    hidden["mp_raw"] = new_mp

    # §13: a preacher does not survive the night either.
    if events.PREACHER_KEY in (hidden.get("npcs_here") or []):
        npc_spawn.remove_npc(
            hidden, hidden.get("current_node_id", "start"),
            events.PREACHER_KEY,
        )
        events.mark_preacher_used(hidden)

    eat, res_used = hunger.reset_hunger_after_sleep()
    visible["eat"] = eat
    visible["sleep_counter"] = 0
    # §35: a paid room is good for one night only.
    hidden["has_room_tonight"] = False
    hidden["resurrection_used_today"] = res_used
    hidden["day"] = hidden.get("day", 1) + 1
    hidden["step"] = 0
    visible["date"] = state_mod.format_date(hidden["day"])
    hidden["day_log"] = []

    if not hidden.get("diary_written_today", False):
        hidden["diary"] = None
        hidden["diary_skipped_today"] = True
    hidden["diary_written_today"] = False

    # new_bug §7: an encounter does not survive the night.
    hidden["pending_encounter"] = None
    hidden["encounter_revealed"] = False


def _apply_bonus_effects(bonus: dict, visible: dict) -> None:
    """new_bug §4: bonus text promises are backed by real state changes."""
    typ = bonus.get("type")
    if typ == "coins":
        amount = int(bonus.get("amount", 2))
        wallet = visible.setdefault("wallet", {})
        wallet["coin"] = int(wallet.get("coin", 0)) + amount
    elif typ == "food":
        economy.add_item(visible, "bread")


def format_inventory(state: dict) -> str:
    """§26 inventory tool: the full item list."""
    return sensory.format_inventory(state.get("visible", {}))


def format_status(state: dict) -> str:
    """§26 status tool: HP/MP, hunger, sleep, effects (no duration)."""
    return sensory.format_status(state.get("visible", {}))


def format_memory(state: dict) -> str:
    """§26 remember tool: the last memory record of a past life."""
    meta = state.get("meta", {})
    memory = meta.get("memory") or meta.get("memory_summary")
    body = memory if memory else "You remember nothing."
    return "[MEMORY]\n" + body


def format_diary(state: dict) -> str:
    """§26 diary tool: the last diary entry."""
    diary = state.get("hidden", {}).get("diary")
    body = diary if diary else "You have no diary entry."
    return "[DIARY]\n" + body


def format_map(state: dict) -> str:
    """Spec 26 map tool: what Burt remembers of the world (spec 17)."""
    return map_mod.render_ascii(state)


def _execute_tool(action: Action, state: dict) -> ActionResult | None:
    """§26: free tools. Return None for a normal (non-tool) action."""
    key = action.key
    if key not in TOOL_KEYS:
        return None
    if key == "scroll":
        return ActionResult(events=[format_scroll(state)])
    if key == "inventory":
        return ActionResult(events=[format_inventory(state)])
    if key == "status":
        return ActionResult(events=[format_status(state)])
    if key == "remember":
        return ActionResult(events=[format_memory(state)])
    if key == "map":
        return ActionResult(events=[format_map(state)])
    return ActionResult(events=[format_diary(state)])


def _execute_action_impl(action: Action, state: dict, rng=None,
                         dialogue_engine: DialogueEngine | None = None,
                         ) -> ActionResult:
    """Execute an action and mutate state. Delegates to sub-modules.

    rng is a callable returning 1..6 (dice roll). Defaults to dice.roll_d6.
    """
    if rng is None:
        rng = dice.roll_d6
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    mode = hidden.get("current_mode", "exploring")

    # ---- §26: free tools (any mode, no step tick) ----
    tool_result = _execute_tool(action, state)
    if tool_result is not None:
        return tool_result

    # ---- dialog mode routing ----
    if mode == "dialog":
        return _execute_dialog_action(action, state, rng, dialogue_engine)

    # ---- exploring mode: talk_to routing ----
    if action.key.startswith("talk_to_"):
        role_key = action.key[len("talk_to_"):]
        if dialogue_engine is None:
            return error_result(f"no dialogue engine for talk_to_{role_key}")
        return _execute_talk_to(action, state, role_key, dialogue_engine, rng)

    # KNOWN ISSUES #5: block movement in combat (defensive).
    # go_back / go_forward / go_north / go_east / go_south / go_west all
    # start with "go_". Combat menu never offers them, so this only fires
    # on hallucinated input and must not move Burt or touch last_action.
    if mode == "combat" and (action.key.startswith("go_") or action.key == "search"):
        return error_result(f"cannot {action.key} in combat")

    # ─── TZ-9: Encounter guard ─────────────────────────────
    if mode != "combat" and hidden.get("combat") is None:
        micro = hidden.get("micro_location")
        micro_active = micro and micro.get("active")
        if not micro_active and hidden.get("encounter_revealed") is True:
            if _is_pending_encounter_valid(hidden):
                # Only attack_* and go_away_to_* are allowed
                if action.key.startswith("attack_"):
                    return _execute_encounter_attack(
                        action, hidden, visible, rng,
                    )
                if action.key.startswith("go_away_to_"):
                    return _execute_go_away(
                        action, hidden, visible, rng,
                    )
                return error_result("cannot take this action during encounter")
            else:
                # Stale encounter — clear and continue normal
                _clear_pending_encounter(hidden)

    # Reset "scared" counter on any non-osmotret/search action.
    if action.key not in ("osmotret", "search"):
        hidden["last_action"] = action.key
        hidden["same_action_count"] = 1

    if action.key == "osmotret":
        hidden["step"] = hidden.get("step", 0) + 1

        last = hidden.get("last_action")
        count = hidden.get("same_action_count", 0)
        if last == "osmotret":
            count += 1
        else:
            count = 1
        hidden["last_action"] = "osmotret"
        hidden["same_action_count"] = count

        events: list[str] = ["You look around."]

        if count == 2:
            events.append(
                "You look around again. Nothing has changed. Satisfied?"
            )
        elif count >= 3:
            damage = 1
            new_hp = max(0, visible["hp"] - damage)
            visible["hp"] = new_hp
            hidden["hp_raw"] = new_hp
            events.append(
                "A branch whips your face. You take 1 damage."
            )
            events.append(f"HP: {new_hp}/{visible['hp_max']}")
            if new_hp <= 0:
                return ActionResult(events=events, game_over=True)

        # TZ-9: handle pending encounter on osmotret
        if _is_pending_encounter_valid(hidden):
            hidden["encounter_revealed"] = True
            pe = hidden["pending_encounter"]
            preview = _preview_pending_enemies(pe.get("enemy_keys", []))
            display_names = [e["display"] for e in preview]
            events.append("You see: " + ", ".join(display_names) + ".")
        elif hidden.get("pending_encounter") is not None:
            # Pending exists but is stale — clear it
            _clear_pending_encounter(hidden)

        report = sensory.format_sensory_report(visible)
        events.append(report)
        return ActionResult(events=events)

    # ── Micro-location exits (§11) ──────────────────────────
    if action.key == "go_back":
        micro = hidden.get("micro_location")
        if micro is None or not micro.get("active"):
            return error_result("no active micro-location")
        source = micro["source_node"]
        graph = hidden.get("location_graph", {})
        if source not in graph:
            return error_result(f"source node {source!r} missing")
        hidden["current_node_id"] = source
        hidden["micro_location"] = {"active": False}
        # TZ-9: clear stale pending after leaving micro-location source
        _clear_pending_encounter(hidden)
        node = graph[source]
        visible["location"]["name"] = _resolve_location_name(
            node.get("type", ""), source,
        )
        if "exits" in node:
            visible["location"]["exits"] = [
                d for d, t in node["exits"].items() if t
            ]
        hidden["step"] = hidden.get("step", 0) + 1
        hidden["day"] = hidden.get("day", 1)
        visible["date"] = state_mod.format_date(hidden["day"])
        return ActionResult(
            events=[
                f"Return to {visible['location']['name']}.",
                sensory.format_sensory_report(visible),
            ],
        )

    if action.key == "go_forward":
        micro = hidden.get("micro_location")
        if micro is None or not micro.get("active"):
            return error_result("no active micro-location")
        target = micro["target_node"]
        if target is None:
            return error_result("no target node for micro-location")
        graph = hidden.get("location_graph", {})
        if target not in graph:
            return error_result(f"target node {target!r} missing")
        hidden["current_node_id"] = target
        hidden["micro_location"] = {"active": False}

        # TZ-9: clear stale pending before checking for new encounter
        _clear_pending_encounter(hidden)

        loc_type, started = _arrive_at_node(
            target, graph, hidden, visible, rng,
        )

        hidden["step"] = hidden.get("step", 0) + 1
        if started is not None:
            return ActionResult(
                events=started.events, game_over=started.game_over,
            )
        return ActionResult(
            events=[sensory.format_sensory_report(visible)],
        )

    if action.key.startswith("go_"):
        direction = action.key[3:]
        if direction not in DIRECTIONS:
            return error_result(f"Invalid direction: {direction}")
        graph = hidden.get("location_graph", {})
        current = hidden.get("current_node_id", "start")
        if current not in graph:
            return error_result("current node missing from graph")
        node = graph[current]
        if "exits" in node:
            next_id = node["exits"].get(direction)
        else:
            next_id = node.get(direction)
        if not next_id or next_id not in graph:
            return error_result(f"no exit {direction}")

        # TZ-9: clear stale pending on any valid movement attempt
        _clear_pending_encounter(hidden)

        move_roll = rng()
        move_result = dice.resolve_movement(move_roll).result
        if move_result in ("fail_bad", "fail"):
            return _handle_movement_failure(
                direction, move_result, hidden, visible, rng,
            )

        hidden["current_node_id"] = next_id

        loc_type, started = _arrive_at_node(
            next_id, graph, hidden, visible, rng,
        )

        hidden["step"] = hidden.get("step", 0) + 1

        if started is not None:
            return ActionResult(
                events=started.events,
                game_over=started.game_over,
                direction_moved=direction,
            )

        if move_roll in (5, 6):
            ev = resolve_movement_event(
                move_roll,
                level=visible.get("level", 1),
                rng=rng,
                hp_max=visible.get("hp_max", 10),
                mp_max=visible.get("mp_max", 3),
            )
            return ActionResult(
                events=_apply_positive_movement_event(
                    ev, visible, hidden, rng,
                ),
                direction_moved=direction,
            )
        return ActionResult(
            events=[sensory.format_sensory_report(visible)],
            direction_moved=direction,
        )

    if action.key == "search":
        loc_type = _current_location_type(hidden)
        if loc_type not in search_mod.SEARCH_AVAILABLE:
            return error_result(f"cannot search in {loc_type or 'unknown'}")

        # Reset counter if previous action was not search
        if hidden.get("last_action") != "search":
            hidden["same_action_count"] = 0

        # Check penalty BEFORE increment (count reflects previous calls)
        should_penalize, penalty_msg = search_mod.check_search_penalty(state)
        if should_penalize:
            visible["hp"] = max(0, visible.get("hp", 10) - 1)
            hidden["hp_raw"] = visible["hp"]
            events = [penalty_msg, "You find nothing."]
            if visible["hp"] <= 0:
                return ActionResult(events=events, game_over=True)
            events.append(sensory.format_sensory_report(visible))
            return ActionResult(events=events)

        # Increment and maybe warn
        count = search_mod.increment_search_counter(state)
        events: list[str] = []
        if count == 2:
            events.append(search_mod.WARN_TEXT)

        hidden["step"] = hidden.get("step", 0) + 1
        roll = rng()
        category, loot_items, coin_gain = search_mod.resolve_search(
            roll, loc_type, rng,
        )

        if category.result == "fail_penalty":
            search_mod.apply_dot(state)
            search_mod.sync_poisoned_effect(state)
            events.append("You cut yourself while searching. -1 HP.")
            events.append("You find nothing.")
            if visible["hp"] <= 0:
                return ActionResult(events=events, game_over=True,
                                    search_result="fail_penalty")
            events.append(sensory.format_sensory_report(visible))
            return ActionResult(events=events, search_result="fail_penalty")

        # Apply loot (aggregate counts)
        inventory = visible.setdefault("inventory", [])
        aggregated: dict[str, int] = {}
        for name in loot_items:
            aggregated[name] = aggregated.get(name, 0) + 1
        for name, cnt in aggregated.items():
            found = False
            for inv in inventory:
                if inv.get("name") == name:
                    inv["count"] = inv.get("count", 0) + cnt
                    found = True
                    break
            if not found:
                inventory.append({"name": name, "count": cnt})

        if coin_gain > 0:
            visible["wallet"]["coin"] = (
                visible["wallet"].get("coin", 0) + coin_gain
            )

        # Build message
        if aggregated or coin_gain > 0:
            parts = [f"{cnt}x {name}" for name, cnt in aggregated.items()]
            if coin_gain > 0:
                parts.append(f"{coin_gain} coin")
            events.append("Found: " + "; ".join(parts) + ".")
        else:
            events.append("You find nothing.")

        events.append(sensory.format_sensory_report(visible))
        return ActionResult(events=events, search_result=category.result)

    if action.key in ("sleep", "write_diary_and_go_sleep"):
        _apply_sleep_state(state)
        return ActionResult(events=["You sleep.", sensory.format_sensory_report(visible)])

    if action.key == "eat_food":
        eat, new_hp = hunger.apply_eat(
            visible.get("eat", False),
            visible.get("hp", 10),
            visible.get("hp_max", 10),
        )
        visible["eat"] = eat
        visible["hp"] = new_hp
        hidden["hp_raw"] = new_hp
        inventory = visible.get("inventory", [])
        for i, item in enumerate(inventory):
            name = item.get("name", "").lower()
            if items.is_food(name):
                item["count"] -= 1
                if item["count"] <= 0:
                    inventory.pop(i)
                break
        hidden["step"] = hidden.get("step", 0) + 1
        return ActionResult(
            events=["You eat.", sensory.format_sensory_report(visible)],
        )

    if action.key == "drink_water":
        inventory = visible.get("inventory", [])
        for i, item in enumerate(inventory):
            name = item.get("name", "").lower()
            if name in ("water", "waterskin", "large_waterskin"):
                item["count"] -= 1
                if item["count"] <= 0:
                    inventory.pop(i)
                break
        hidden["step"] = hidden.get("step", 0) + 1
        return ActionResult(
            events=["You drink some water.", sensory.format_sensory_report(visible)],
        )

    if mode == "combat":
        return _execute_combat(action, state, rng)

    return error_result(f"Unknown action: {action.key}")


def execute_action(action: Action, state: dict, rng=None,
                   dialogue_engine: DialogueEngine | None = None,
                   ) -> ActionResult:
    """Public entry: run the action, then spend one effect action if due.

    §13: curse/blessing lasts 3 actions. A real action is either a
    step-advancing action or one combat round (combat freezes the day
    counter). Free tools and dialogue replies do not tick the effects.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    step_before = hidden.get("step", 0)
    mode_before = hidden.get("current_mode", "exploring")

    result = _execute_action_impl(action, state, rng, dialogue_engine)

    if result.events and result.events[0].startswith("Error:"):
        return result
    if result.skip_effect_tick:
        return result
    if action.key in TOOL_KEYS:
        return result

    if hidden.get("step", 0) > step_before:
        events.tick(hidden, visible)
    elif mode_before == "combat" and (
        action.key.startswith("attack_")
        or action.key in ("block", "flee", "cast")
    ):
        events.tick(hidden, visible)
    return result


def _execute_combat(action: Action, state: dict, rng) -> ActionResult:
    """Execute one combat action via combat.resolve_round (§23)."""
    hidden = state["hidden"]
    visible = state["visible"]

    combat_dict = hidden.get("combat")
    if combat_dict is None:
        return error_result("no active combat")

    try:
        combat_state = CombatState.from_dict(combat_dict)
    except (KeyError, ValueError, TypeError) as ex:
        return error_result(f"invalid combat state: {ex}")

    if action.key.startswith("attack_"):
        target_id = action.target_id or action.key[len("attack_"):]
        found = None
        for e in combat_state.enemies:
            if e.id == target_id:
                found = e
                break
        if found is None:
            return error_result(f"no such enemy: {target_id}")
        if not found.alive:
            return error_result(f"enemy is dead: {target_id}")
        combat_action = "attack"
    elif action.key == "block":
        combat_action = "block"
        target_id = None
    elif action.key == "flee":
        combat_action = "flee"
        target_id = None
    elif action.key == "cast":
        combat_action = "cast"
        target_id = None
    else:
        return error_result(f"unknown combat action: {action.key}")

    burt = _build_burt_stats(visible, hidden)

    try:
        result = combat.resolve_round(
            combat_state, burt, combat_action, target_id, rng,
        )
    except ValueError as ex:
        return error_result(str(ex))

    visible["hp"] = max(0, result.burt.hp)
    visible["mp"] = max(0, result.burt.mp)
    hidden["hp_raw"] = visible["hp"]
    hidden["mp_raw"] = visible["mp"]

    events: list[str] = list(result.events_llm)
    action_result = ActionResult(events=events)

    # §8: weapon mastery counts every strike (not every hit). A cast
    # counts as a strike for the Magic skill (§9: it works like any
    # other combat skill).
    if getattr(result, "burt_acted", False):
        strike_skill: str | None = None
        if combat_action == "attack":
            strike_skill = weapons.weapon_skill(result.burt.weapon)
        elif combat_action == "cast":
            strike_skill = "Magic"
        if strike_skill:
            skills.record_strike(hidden, visible, strike_skill)

    if result.outcome == "ongoing":
        hidden["combat"] = result.combat.to_dict()
        hidden["current_mode"] = "combat"
        report = sensory.format_combat_report(result.combat, result.burt)
        events.append(report)
    else:
        npc_role = hidden.get("combat_npc_role")
        hidden["combat"] = None
        hidden["current_mode"] = "exploring"
        dead_enemies = [e for e in result.combat.enemies if not e.alive]
        # §7: XP for every dead enemy, even if Burt fled afterwards.
        club_granted = False
        if result.outcome != "burt_died" and dead_enemies:
            club_granted = _award_combat_xp(
                visible, hidden, len(dead_enemies), events,
                dead_keys=[e.key for e in dead_enemies],
            )
        if result.outcome == "burt_won":
            if dead_enemies:
                enemy_keys = [e.key for e in dead_enemies]
                # §36: "kill" quests count every enemy killed after accept.
                ready_quests: list[str] = []
                for enemy_key in enemy_keys:
                    ready_quests.extend(quests.on_enemy_killed(enemy_key, state))
                rolls = [rng() for _ in dead_enemies]
                drop = loot.collect_loot(enemy_keys, rolls)
                inventory = visible.setdefault("inventory", [])
                for item in drop.items:
                    name = item["name"]
                    count = item["count"]
                    existing = None
                    for inv_item in inventory:
                        if inv_item.get("name") == name:
                            existing = inv_item
                            break
                    if existing is not None:
                        existing["count"] = existing.get("count", 0) + count
                    else:
                        inventory.append({"name": name, "count": count})
                if drop.coins > 0:
                    visible["wallet"]["coin"] = (
                        visible["wallet"].get("coin", 0) + drop.coins
                    )
                loot_parts: list[str] = []
                if drop.items:
                    loot_parts.append(
                        ", ".join(
                            f"{i['count']}x {i['name']}" for i in drop.items
                        )
                    )
                if drop.coins > 0:
                    loot_parts.append(f"{drop.coins} coin")
                if loot_parts:
                    events.append("Loot: " + "; ".join(loot_parts))
                elif not club_granted:
                    events.append("Loot: nothing.")
                for quest_id in ready_quests:
                    events.append(
                        f"Quest ready to report: {_quest_title(quest_id)}."
                    )
            # §34: killing a resident in combat is the same crime as
            # dialog_attack. The dead enemy must match the stored role.
            if (npc_role and npc_combat.is_npc_enemy(npc_role)
                    and any(e.key == npc_role and not e.alive
                            for e in result.combat.enemies)):
                _apply_npc_combat_crime(npc_role, state, events)
        if result.outcome == "burt_died":
            action_result.game_over = True
        if npc_role is not None:
            hidden["combat_npc_role"] = None

    return action_result


def _apply_npc_combat_crime(
    role_key: str,
    state: dict,
    events: list[str],
) -> None:
    """§34: a resident killed in combat runs the full crime pipeline."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    summary = faith.on_resident_killed(role_key, role_key, state)
    npc_spawn.remove_npc(
        hidden, hidden.get("current_node_id", "start"), role_key,
    )
    if summary["failed_quests"]:
        events.append("Your open work is lost.")
    events.append(sensory.format_sensory_report(visible))


def _award_combat_xp(
    visible: dict,
    hidden: dict,
    dead_count: int,
    events: list[str],
    dead_keys: list[str] | None = None,
) -> bool:
    """§7: award kill XP at the end of a combat and apply level-ups.

    Reaching level 2 grants one club as a simulated drop from the
    tutorial young goblin. The club is deliberately not in loot.py.
    Returns True when the club was granted this combat.
    """
    if dead_count <= 0:
        return False
    result = progression.award_kills(visible, dead_count)
    hidden["hp_raw"] = visible.get("hp", 0)
    hidden["mp_raw"] = visible.get("mp", 0)
    if result.gained > 0:
        events.append(f"You gain {result.gained} XP.")
    for level in range(result.old_level + 1, result.new_level + 1):
        events.append(
            f"You reach level {level}. "
            f"HP +{progression.HP_PER_LEVEL}, MP +{progression.MP_PER_LEVEL}."
        )

    # Tutorial reward: 1 -> 2 transition only (level never goes down).
    club_granted = False
    if result.old_level < spawn.YOUNG_LEVEL <= result.new_level:
        economy.add_item(visible, "club")
        if dead_keys and spawn.YOUNG_GOBLIN_KEY in dead_keys:
            events.append("You take a club from the young goblin.")
        else:
            events.append("You pick up a club.")
        club_granted = True
    return club_granted


def _build_burt_stats(visible: dict, hidden: dict) -> BurtStats:
    """Assemble BurtStats from visible + hidden for combat."""
    # §9: casting needs staff + spell + teacher (magic.cast_ready).
    spells_available = magic.cast_ready(hidden, _has_staff(visible, hidden))

    # §8: skill levels drive weapon choice, damage range and die rolls.
    levels = skills.level_map(hidden)
    choice = weapons.select_weapon(visible.get("inventory") or [], levels)
    weapon_level = int(levels.get(choice.skill, 0)) if choice.skill else 0
    magic_level = int(levels.get("Magic", 0))
    cast_min, cast_max = weapons.magic_damage_range(magic_level)
    event_mod = events.modifier(hidden)

    return BurtStats(
        hp=visible["hp"],
        hp_max=visible["hp_max"],
        mp=visible["mp"],
        mp_max=visible["mp_max"],
        damage_min=choice.damage_min,
        damage_max=choice.damage_max,
        master=weapon_level,
        modifier=skills.modifier(weapon_level) + event_mod,
        spells_available=spells_available,
        weapon=choice.key,
        cast_damage_min=cast_min,
        cast_damage_max=cast_max,
        cast_master=magic_level,
        cast_modifier=skills.modifier(magic_level) + event_mod,
    )


def _sleep_available(visible: dict, hidden: dict) -> bool:
    """§5: sleep needs a bedroll or a paid room, and not combat.

    The `sleep.py` core decides; this wrapper only reads the state.
    Critical HP keeps a safety valve below the step threshold (deviation
    documented in known_issues #13: a dying Burt may sleep without a bed).
    """
    has_bedroll = economy.has_item(visible, "bedroll")
    has_room = bool(hidden.get("has_room_tonight"))
    in_combat = hidden.get("current_mode") == "combat"
    step = hidden.get("step", 0)
    if sleep_mod.is_sleep_available(step, in_combat, has_bedroll, has_room):
        return True

    hp = visible.get("hp", 10)
    hp_max = visible.get("hp_max", 10)
    return hp_max > 0 and hp * 100 < hp_max * 25


def should_sleep(visible: dict, state: dict) -> bool:
    """Check if character should sleep now."""
    sc = visible.get("sleep_counter", 0)
    if sc >= SLEEP_THRESHOLD:
        return True
    hp = visible.get("hp", 10)
    hp_max = visible.get("hp_max", 10)
    if hp_max > 0 and hp * 100 < hp_max * CRITICAL_HP_RATIO * 100:
        return True
    return False


def error_result(msg: str) -> ActionResult:
    """Create an error ActionResult."""
    return ActionResult(events=["Error: " + msg])


def _execute_talk_to(action: Action, state: dict, role_key: str,
                     engine: DialogueEngine, rng) -> ActionResult:
    """Meet an NPC: a hostile resident fights, the rest talk (§34)."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})

    # §34: guard / cleric / necromancer attack instead of talking.
    if npc_combat.is_hostile(state, role_key):
        started = _start_npc_fight(role_key, state, rng)
        return ActionResult(
            events=started.events, game_over=started.game_over,
        )

    # §34: residents have no dialogue after a crime. The necromancer is
    # the only exception (the killer may still take K3 from him).
    if not faith.can_talk_to(state, role_key):
        return error_result(f"the {role_key} will not talk to you")

    # §13: the preacher is an event, not a role. He has one intro and
    # one dice reply; no reputation, no quests, no training.
    if role_key == events.PREACHER_KEY:
        hidden["current_mode"] = "dialog"
        hidden["dialog_state"] = {
            "role_key": role_key,
            "rep_role": None,
            "shop_role": None,
            "shop": None,
            "train_asked": False,
            "is_angry": False,
            "turn": 0,
            "anger_lock_until": None,
            "bonus_used": False,
            "quest_state": "none",
            "rep_applied": True,
            "preacher_done": False,
        }
        hidden["last_action"] = action.key
        hidden["same_action_count"] = 1
        intro = (engine.event_line(role_key, "intro")
                 or "The preacher greets you.")
        return ActionResult(events=[
            intro, sensory.format_sensory_report(visible),
        ])

    rep_role = _rep_role(role_key)
    hidden["current_mode"] = "dialog"
    hidden["dialog_state"] = {
        "role_key": role_key,
        "rep_role": rep_role,
        "shop_role": rep_role,
        "shop": None,
        "train_asked": False,
        "is_angry": False,
        "turn": 0,
        "anger_lock_until": None,
        "bonus_used": False,
        "quest_state": quests.quest_state_for_role(rep_role, state),
        "rep_applied": False,
    }
    # §35: the location price modifier is rolled once per node — on the
    # first meeting with a trader there. Rolling it here (not on arrival)
    # keeps the movement/encounter dice order untouched.
    if rep_role in trade.TRADE_ROLES:
        economy.modifier_for_node(
            hidden, hidden.get("current_node_id", "start"), rng,
        )
    # new_bug §1: entering the dialogue is free; the whole dialogue is
    # one action and only dialog_exit advances the step.
    hidden["last_action"] = action.key
    hidden["same_action_count"] = 1
    return ActionResult(events=[
        f"You approach the {role_key}.",
        sensory.format_sensory_report(visible),
    ])


def _finish_dialog(state: dict) -> ActionResult:
    """The only exit from dialog mode (new_bug §1).

    Every dialogue path that closes the conversation goes through here:
    exactly one step tick for the whole dialogue.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    role_key = (hidden.get("dialog_state") or {}).get("role_key")
    hidden["current_mode"] = "exploring"
    hidden["dialog_state"] = None
    hidden["step"] = hidden.get("step", 0) + 1
    # §16: the next talk may change reputation again.
    reputation.reset_dialog_rep(state)
    # §13: after the dialogue the preacher disappears and is forgotten.
    skip_tick = False
    if role_key == events.PREACHER_KEY:
        npc_spawn.remove_npc(
            hidden, hidden.get("current_node_id", "start"),
            events.PREACHER_KEY,
        )
        events.mark_preacher_used(hidden)
        # The effect starts after this one-action dialogue.
        skip_tick = True
    return ActionResult(
        events=["You leave the conversation.",
                sensory.format_sensory_report(visible)],
        skip_effect_tick=skip_tick,
    )


def _execute_preacher_reply(
    action: Action,
    state: dict,
    rng,
    engine: DialogueEngine | None,
) -> ActionResult:
    """§13: one d6 for the whole dialogue with the preacher.

    1 -> curse, 2-5 -> nothing, 6 -> blessing; the effect lasts 3
    actions. The reply is free: the whole dialogue is one action and
    only dialog_exit ticks. The preacher never touches reputation.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}

    if not action.key.startswith("dialog_"):
        return error_result(f"unknown dialog action: {action.key}")
    category = action.key[len("dialog_"):]
    if engine is not None:
        allowed = engine.available_categories(events.PREACHER_KEY)
        if category not in allowed:
            return error_result(
                f"the preacher does not answer {category!r}"
            )

    if ds.get("preacher_done"):
        return ActionResult(events=[
            "The preacher has nothing more to say.",
            sensory.format_sensory_report(visible),
        ])

    roll = rng()
    kind = events.resolve_preacher(roll)
    text = ""
    if engine is not None:
        text = engine.event_line(events.PREACHER_KEY, kind)

    effect = events.effect_for(kind)
    if effect is not None:
        events.apply_effect(hidden, visible, effect)

    ds["preacher_done"] = True
    result_events = [text] if text else []
    result_events.append(sensory.format_sensory_report(visible))
    return ActionResult(events=result_events)


def _execute_dialog_action(action: Action, state: dict, rng,
                           engine: DialogueEngine | None) -> ActionResult:
    """Handle dialog actions: dialog_<cat> or dialog_exit."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state")
    if ds is None:
        return error_result("no active dialog")

    # dialog_exit
    if action.key == "dialog_exit":
        is_angry = ds.get("is_angry", False)
        lock_until = ds.get("anger_lock_until")
        turn = ds.get("turn", 0)
        if is_angry and (lock_until is None or turn < lock_until):
            return error_result("cannot leave while angry")
        return _finish_dialog(state)

    # §13: the preacher's one dice reply (curse / nothing / blessing).
    if ds.get("role_key") == events.PREACHER_KEY:
        return _execute_preacher_reply(action, state, rng, engine)

    # §33/§34: faith actions are handled before the generic topics.
    if action.key == "dialog_attack":
        return _execute_kill_resident(state, rng)
    if action.key == "dialog_donate":
        return _execute_donate(state)

    # §35: an open shop is driven by buy_/sell_/close, not by topics.
    if action.key == "dialog_trade_close":
        return _close_shop(state)
    if action.key.startswith("dialog_buy_"):
        return _execute_trade_buy(action.key[len("dialog_buy_"):], state)
    if action.key.startswith("dialog_sell_"):
        return _execute_trade_sell(action.key[len("dialog_sell_"):], state)

    # dialog_<category>
    if engine is None:
        return error_result("no dialogue engine")
    if not action.key.startswith("dialog_"):
        return error_result(f"unknown dialog action: {action.key}")
    category = action.key[len("dialog_"):]

    # §36: asking for work may actually hand out a quest.
    if category == "quest" and ds.get("quest_state") == "available":
        return _issue_role_quest(state, rng, engine)

    # §36/§18: report a finished quest to its giver.
    if category == "quest" and ds.get("quest_state") == "in_progress":
        handin = _try_hand_in_quest(state, ds.get("role_key", ""))
        if handin is not None:
            return handin

    # §36: "talk" quests count a conversation with the target role.
    quests.on_talk(ds.get("role_key", ""), state)

    # §35: trade opens the shop sub-mode; §9/§32: training changes skills.
    if category == "trade":
        return _open_shop(state, engine, rng)
    if category == "train":
        return _execute_train(state, engine, rng)

    # §33 K2 heretic: the first roll decides (>= 3), one try per NPC.
    if category == "lie" and faith.heretic_k2_active(state):
        roll = rng()
        second_roll = rng()
        faith.on_deceive(
            ds.get("rep_role", ""),
            hidden.get("current_node_id", ""),
            roll,
            state,
        )
        return execute_dialog(
            action, state, engine, rng, category=category,
            roll=roll, second_roll=second_roll,
        )

    result = execute_dialog(action, state, engine, rng, category=category)
    # §33 K3 heretic: a successful threat against the cleric counts.
    if (category == "threat" and ds.get("role_key") == "cleric"
            and ds.get("last_outcome") == "SUCCESS"
            and faith.on_insult_to_cleric(state)):
        result.events.insert(0, "The insult lands.")
    return result


def _execute_kill_resident(state: dict, rng) -> ActionResult:
    """§34: a single hostile act kills a resident (no combat rounds)."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}
    role_key = ds.get("role_key", "")
    rep_role = ds.get("rep_role") or role_key
    node_id = hidden.get("current_node_id", "start")
    if role_key not in faith.RESIDENT_ROLES:
        return error_result("not a resident")

    summary = faith.on_resident_killed(role_key, rep_role, state)
    npc_spawn.remove_npc(hidden, node_id, role_key)

    # The murder closes the dialogue and is one action (§3).
    hidden["current_mode"] = "exploring"
    hidden["dialog_state"] = None
    hidden["step"] = hidden.get("step", 0) + 1
    hidden["last_action"] = "dialog_attack"
    hidden["same_action_count"] = 1
    reputation.reset_dialog_rep(state)

    events = [f"You strike the {role_key} down. The body falls still."]
    if summary["failed_quests"]:
        events.append("Your open work is lost.")
    events.append(sensory.format_sensory_report(visible))

    # §34: the murder wakes any hostile resident still standing here;
    # children and peasants run away on the spot.
    events.extend(_remove_fleeing_residents(hidden, node_id))
    started = _start_npc_hostility_if_any(state, rng)
    if started is not None:
        events.extend(started.events)
        return ActionResult(events=events, game_over=started.game_over)
    return ActionResult(events=events)


def _execute_donate(state: dict) -> ActionResult:
    """§33 K3: give every coin to the temple (paladin / heretic chain)."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}
    role_key = ds.get("role_key", "")

    info = faith.donate(state, role_key)
    if info is None:
        return error_result("nothing to donate")

    events = ["You give every coin to the temple."]
    if info["coins"] > 0:
        events.append(f"Donated: {info['coins']} coin.")

    if info["complete_now"]:
        ok, _message = quests.quest_complete(info["quest_id"], state)
        if ok:
            events.append("The temple accepts your offering.")
    else:
        events.append(
            "The temple accepts your offering. "
            "Report back to the one who sent you."
        )
    events.append(sensory.format_sensory_report(visible))
    return ActionResult(events=events)


def _close_shop(state: dict) -> ActionResult:
    """§35: leave the goods list, stay in the dialogue."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}
    ds["shop"] = None
    return ActionResult(events=[
        "You step back from the counter.",
        sensory.format_sensory_report(visible),
    ])


def _open_shop(state: dict, engine: DialogueEngine, rng) -> ActionResult:
    """§35: run the trade reply, then open the goods list.

    The npc.py bonus "trade_discount" (20% off) applies to every deal of
    this dialogue, so it is read once, here.
    """
    hidden = state.setdefault("hidden", {})
    ds = hidden.get("dialog_state") or {}
    result = execute_dialog(
        Action(key="dialog_trade", label="Trade"),
        state, engine, rng, category="trade",
    )

    result_bonus = ds.get("last_bonus") or {}
    discount = 1.0
    if result_bonus.get("type") == "trade_discount":
        percent = int(result_bonus.get("percent", _TRADE_DISCOUNT_DEFAULT))
        discount = 1.0 - percent / 100.0

    ds["shop"] = {"bonus": discount}

    events = list(result.events)
    hint = "The trader lays out the goods: buy, sell, or be done."
    if events:
        events.insert(len(events) - 1, hint)
    else:
        events.append(hint)
    return ActionResult(events=events)


def _execute_trade_buy(item: str, state: dict) -> ActionResult:
    """§35: Burt buys one item from the open shop."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}
    shop = ds.get("shop")
    if not shop:
        return error_result("no open shop")

    role = _shop_role(ds)
    if item not in trade.ROLE_SELLS.get(role, frozenset()):
        return error_result(f"{role} does not sell {item}")

    if item == "tavern_room" and hidden.get("has_room_tonight"):
        return error_result("you already paid for a room tonight")

    price = economy.buy_price(item, **_price_context(state, ds))
    coin = int(visible.get("wallet", {}).get("coin", 0))
    if price > coin:
        return error_result(
            f"not enough coin for {item}: {price} needed, {coin} in purse"
        )

    visible.setdefault("wallet", {})["coin"] = coin - price

    if item == "tavern_room":
        # One-shot goods: a night in the tavern, not an inventory item.
        hidden["has_room_tonight"] = True
        events = [f"You pay {price} coin for a room for the night."]
    else:
        economy.add_item(visible, item)
        events = [f"You buy {_display_name(item)} for {price} coin."]
        if item == "staff":
            hidden["has_staff"] = True

    events.append(sensory.format_sensory_report(visible))
    return ActionResult(events=events)


def _execute_trade_sell(item: str, state: dict) -> ActionResult:
    """§35: Burt sells one item (loot included) to the open shop."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}
    shop = ds.get("shop")
    if not shop:
        return error_result("no open shop")

    if not economy.has_item(visible, item):
        return error_result(f"you have no {item}")

    try:
        price = economy.sell_price(item, **_price_context(state, ds))
    except KeyError:
        return error_result(f"nobody wants {item}")

    role = _shop_role(ds)
    economy.remove_item(visible, item, 1)
    visible.setdefault("wallet", {})["coin"] = (
        int(visible.get("wallet", {}).get("coin", 0)) + price
    )

    events = [f"You sell {_display_name(item)} for {price} coin."]
    if price == 0:
        events.append("It is worth nothing here, but they take it anyway.")

    # §9 (agreement 20.11.2026): two goblin staves sold to the necromancer
    # and he hands over a proper staff — the trophy road to magic.
    if role == "necromancer" and item == "goblin_staff":
        mstate = magic.ensure_state(hidden)
        if magic.record_loot_staff_sale(mstate):
            economy.add_item(visible, "staff")
            hidden["has_staff"] = True
            events.append(
                "He studies the goblin work, snorts, and hands you a staff."
            )

    events.append(sensory.format_sensory_report(visible))
    return ActionResult(events=events)


def _execute_train(state: dict, engine: DialogueEngine, rng) -> ActionResult:
    """§9/§32: a training reply, then the skill effect.

    npc.py already returns the right replica (train_offer / train_done /
    train_locked); magic.train() decides whether the skill actually grows.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state") or {}
    role = ds.get("role_key", "")

    result = execute_dialog(
        Action(key="dialog_train", label="Train"),
        state, engine, rng, category="train",
    )
    ds["train_asked"] = True

    outcome = magic.train(hidden, visible, role, rng=rng)
    events = list(result.events)

    if outcome.applied:
        parts: list[str] = []
        if outcome.granted:
            parts.append(f"You learn the way of {outcome.granted}.")
        if outcome.skill_name:
            parts.append(
                f"Skill {outcome.skill_name} "
                f"{outcome.skill_level}/{magic.SKILL_MAX_LEVEL}."
            )
        if outcome.note:
            parts.append(outcome.note.capitalize() + ".")
        if parts:
            events.insert(len(events) - 1, " ".join(parts))
    elif outcome.note:
        events.insert(len(events) - 1, outcome.note.capitalize() + ".")

    return ActionResult(events=events)


def _try_hand_in_quest(state: dict, role_key: str) -> ActionResult | None:
    """§18: hand in a finished quest of this role. None if not possible."""
    hidden = state.get("hidden", {})
    visible = state.setdefault("visible", {})

    for entry in hidden.get("quests_raw", []):
        if entry.get("status") != "active":
            continue
        if entry.get("giver_role") != role_key:
            continue
        quest_id = entry["id"]
        from burt import quests as quests_mod
        q = quests_mod.quest_get_active(quest_id, state)
        if q is None:
            continue

        if q.type == "deliver":
            if not quests_mod.deliver_ready(quest_id, state):
                continue
        elif q.type in ("kill", "visit", "talk", "help", "deceive", "chain"):
            if (q.progress or 0) < (q.required or 0):
                continue
        else:
            continue

        ok, message = quests_mod.quest_complete(quest_id, state)
        if not ok:
            continue

        # §16: quest completed +1 for the giver's role.
        reputation.change(state, role_key, reputation.QUEST_DELTA_OK)
        # §36: completed quests count for "help" quests of the same role.
        supporting = quests_mod.on_quest_completed(role_key, state)
        # §33: K2 paladin counts closed role quests only (not chains).
        faith.on_help_completed(state, is_chain=bool(q.chain))

        events = [f"Quest complete: {q.title}.", message]
        for other in supporting:
            events.append(f"Quest ready to report: {_quest_title(other)}.")
        events.append(sensory.format_sensory_report(visible))
        return ActionResult(events=events)

    return None


def _issue_role_quest(state: dict, rng,
                      engine: DialogueEngine) -> ActionResult:
    """Give the NPC's role quest to Burt (§36).

    The role is taken from dialog_state. Deadline is rolled 1d6 -> 3/5/7
    (quests.roll_deadline). When the pool is empty, the dialog still plays
    its "no work" line.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state")
    role_key = (ds or {}).get("role_key", "")

    # §33: cleric / necromancer hand out faith chains, not role quests.
    if role_key in faith.FAITH_ROLES:
        chain_id = faith.next_chain_step(role_key, state)
        if chain_id is None:
            ds = hidden.setdefault("dialog_state", {})
            ds["quest_state"] = "none"
            return execute_dialog(
                Action(key="dialog_quest", label="Quest"), state, engine, rng,
                category="quest",
            )
        ok, _message = quests.quest_give(
            chain_id, role_key, state, force=True,
        )
        if ok:
            faith.on_chain_issued(chain_id, state)
            ds["quest_state"] = "in_progress"
        result = execute_dialog(
            Action(key="dialog_quest", label="Quest"), state, engine, rng,
            category="quest",
        )
        if ok:
            title = _quest_title(chain_id)
            result.events.insert(
                0, f"The {role_key} gives you work: {title}.",
            )
        return result

    quest_id = quests.pick_quest_for_role(role_key, state, rng)
    if quest_id is None:
        ds = hidden.setdefault("dialog_state", {})
        ds["quest_state"] = "none"
        return execute_dialog(
            Action(key="dialog_quest", label="Quest"), state, engine, rng,
            category="quest",
        )

    ok, message = quests.quest_give(quest_id, role_key, state)
    if ok:
        _apply_quest_deadline(quest_id, state, rng)
        ds["quest_state"] = "in_progress"

    result = execute_dialog(
        Action(key="dialog_quest", label="Quest"), state, engine, rng,
        category="quest",
    )
    if ok:
        title = _quest_title(quest_id)
        result.events.insert(0, f"The {role_key} gives you work: {title}.")
    return result


def _apply_quest_deadline(quest_id: str, state: dict, rng) -> None:
    """§36: deadline = 1d6 -> 3/5/7 days from today."""
    hidden = state.setdefault("hidden", {})
    day = hidden.get("day", 1)
    try:
        days = quests.roll_deadline(rng)
    except ValueError:
        days = 5
    for d in hidden.get("quests_raw", []):
        if d.get("id") == quest_id and d.get("status") == "active":
            d["deadline_day"] = day + days
            break


def format_scroll(state: dict) -> str:
    """§18: quest scroll text. The giver stays hidden.

    Format per quest:
        Fangs of the Wolves — fangs 2/5, 4 days left
    """
    hidden = state.get("hidden", {})
    day = hidden.get("day", 1)
    active = [d for d in hidden.get("quests_raw", [])
              if d.get("status") == "active"]

    if not active:
        return "[SCROLL]\nNo open quests.\n"

    lines = ["[SCROLL]"]
    for entry in active:
        title = entry.get("title", entry.get("id", "?"))
        items = entry.get("deliver_items") or []
        if items:
            req = items[0]
            have, need = quests.deliver_progress(entry["id"], state)
            progress = f"{req['name']} {have}/{need}"
        else:
            required = entry.get("required") or 0
            done = entry.get("progress", 0)
            progress = f"{done}/{required}"

        tag = entry.get("tag")
        name = f"{tag} {title}" if tag else title
        deadline = entry.get("deadline_day")
        if deadline is None:
            left = "no deadline"
        else:
            days_left = max(0, deadline - day)
            left = f"{days_left} days left"

        lines.append(f"{name} — {progress}, {left}")
    return "\n".join(lines) + "\n"


def _quest_title(quest_id: str) -> str:
    try:
        templates = quests._load_templates()
    except (OSError, ValueError):
        return quest_id
    return templates.get(quest_id, {}).get("title", quest_id)


def execute_dialog(action: Action, state: dict, engine: DialogueEngine, rng,
                   *, category: str | None = None,
                   roll: int | None = None,
                   second_roll: int | None = None) -> ActionResult:
    """Execute one dialogue turn.

    Rebuilds Session from dialog_state + visible, calls Session.say(),
    applies Result back to state.

    roll / second_roll may be supplied by the caller (faith K2 needs the
    same first roll for the reply and for the quest count).
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state")
    if ds is None:
        return error_result("no active dialog")

    cat = category or action.key[len("dialog_"):]
    if roll is None:
        roll = rng()
    # second_roll: deterministic default for tests (4 = no bonus)
    if second_roll is None:
        second_roll = rng()

    # Rebuild session from persisted state
    role_key = ds.get("role_key", "")
    rep_role = ds.get("rep_role") or _rep_role(role_key)
    hp = visible.get("hp", 10)
    coins = visible.get("wallet", {}).get("coin", 100)
    reputation_bonus = hidden.get("reputation", {}).get(rep_role, 0)

    session = engine.start(
        role_key, hp=hp, coins=coins,
        reputation_bonus=reputation_bonus
    )
    # Restore anger state
    if ds.get("is_angry", False):
        session.is_angry = True
        session.anger_lock_until = ds.get("anger_lock_until")
    # Restore turn
    session.turn = ds.get("turn", 0)
    # Restore bonus_used
    session.bonus_used = ds.get("bonus_used", False)
    # Restore quest_state
    session.quest_state = ds.get("quest_state", "available")

    result = session.say(
        cat, roll=roll, second_roll=second_roll,
        modifier=events.modifier(hidden),
    )

    # Apply result back to state
    visible["hp"] = session.hp
    hidden["hp_raw"] = session.hp
    visible["wallet"]["coin"] = session.coins

    # Update dialog_state
    ds["is_angry"] = session.is_angry
    ds["turn"] = session.turn
    ds["anger_lock_until"] = session.anger_lock_until
    ds["bonus_used"] = session.bonus_used
    ds["quest_state"] = session.quest_state
    # §35: the trade bonus of this reply must survive into the shop mode.
    ds["last_bonus"] = result.bonus
    # §33: the insult check needs the reply outcome.
    ds["last_outcome"] = result.outcome.name

    # new_bug §1: a dialogue reply is part of the single dialogue action;
    # the step is advanced only by _finish_dialog (dialog_exit).

    # §16: one reputation change per dialogue, on the first reply only.
    if cat not in ("exit", "quest"):
        delta = reputation.dialogue_delta(result.outcome, result.became_angry)
        reputation.apply_dialog_rep(state, rep_role, delta)

    result_events = [result.text]
    if result.bonus is not None:
        _apply_bonus_effects(result.bonus, visible)
        text = bonus_text(result.bonus)
        if text:
            result_events.append(text)
    result_events.append(sensory.format_sensory_report(visible))

    return ActionResult(events=result_events)


def _enter_new_node(graph: dict, node_id: str, rng) -> None:
    """Generate a new node per §17."""
    roll_count = rng()
    roll_dirs = rng()
    roll_type = rng()
    if roll_type == 5:
        roll_size = (rng() - 1) % 3 + 1  # 1..3
    else:
        roll_size = rng()  # 1..6 or ignored
    world.enter_node(
        graph, node_id, roll_count, roll_dirs, roll_type, roll_size,
    )


# ─── Pending encounter helpers (TZ-9) ─────────────────────────


def _clear_pending_encounter(hidden: dict) -> None:
    """Clear pending encounter state."""
    hidden["pending_encounter"] = None
    hidden["encounter_revealed"] = False


def _is_pending_encounter_valid(hidden: dict) -> bool:
    """Check if pending_encounter is active and valid for current location."""
    pe = hidden.get("pending_encounter")
    if not isinstance(pe, dict):
        return False
    if hidden.get("combat") is not None:
        return False
    if hidden.get("current_mode") == "combat":
        return False
    micro = hidden.get("micro_location")
    if micro and micro.get("active"):
        return False
    enemy_keys = pe.get("enemy_keys")
    if not enemy_keys:
        return False
    if pe.get("node_id") != hidden.get("current_node_id"):
        return False
    current_type = _current_location_type(hidden)
    if current_type not in _ENCOUNTER_LOCATIONS:
        return False
    if current_type == _AMBUSH_LOCATION:
        return False
    return True


def _preview_pending_enemies(enemy_keys: list[str]) -> list[dict]:
    """Preview enemy IDs by running combat.start_combat as a dry run.

    Returns list of dicts with keys: id, key, display.
    If start_combat raises, returns empty list (bit encounter).
    """
    try:
        preview = combat.start_combat(enemy_keys, "burt")
        result: list[dict] = []
        for e in preview.enemies:
            template = ENEMIES.get(e.key)
            display = template.name if template is not None else e.key
            result.append({"id": e.id, "key": e.key, "display": display})
        return result
    except (ValueError, KeyError, TypeError):
        return []


def _combat_opening_events(report: str, free_strike: list[str]) -> list[str]:
    """Order the opening step: [COMBAT] header, ambush events, enemy menu.

    Keeps the ambush on the step that opened combat instead of leaking it
    into the first resolve_round. Falls back to "ambush first" if the
    report header ever changes in sensory.
    """
    if not free_strike:
        return [report]
    header, _sep, body = report.partition("\n")
    if header.strip() != _COMBAT_HEADER:
        return list(free_strike) + [report]
    events = [header] + list(free_strike)
    if body:
        events.append(body)
    return events


def _start_combat(
    enemy_keys: list[str],
    initiative: str,
    hidden: dict,
    visible: dict,
    rng,
    opening_text: str = "Ambush!",
) -> CombatStart:
    """Start combat (§23) and resolve the ambush free strike right here.

    The free strike is step 0 of combat opening, not part of round 1:
    it is resolved on the step that triggered combat, so the log reads
    "[COMBAT] / Ambush! / wolf hits you." before the menu is injected.
    HP/MP are synced immediately, so the combat report and the LLM prompt
    already reflect the damage taken. No round is consumed.
    """
    # TZ-10: lvl < 5 -> single monster, not a pack.
    if visible.get("level", 1) < 5 and len(enemy_keys) > 1:
        enemy_keys = enemy_keys[:1]

    combat_state = combat.start_combat(enemy_keys, initiative)
    burt = _build_burt_stats(visible, hidden)

    # §23 step 0: enemy initiative -> free strike, no block allowed.
    opening = combat.resolve_free_strike(
        combat_state, burt, rng, opening_text,
    )
    combat_state = opening.combat
    burt = opening.burt

    visible["hp"] = max(0, burt.hp)
    visible["mp"] = max(0, burt.mp)
    hidden["hp_raw"] = visible["hp"]
    hidden["mp_raw"] = visible["mp"]

    # TZ-9: clear encounter state on any combat start
    _clear_pending_encounter(hidden)

    if opening.outcome == "burt_died":
        # Ambush killed Burt: no combat menu, death on this same step.
        hidden["combat"] = None
        hidden["current_mode"] = "exploring"
        return CombatStart(
            events=[_COMBAT_HEADER] + list(opening.events_llm),
            game_over=True,
        )

    hidden["combat"] = combat_state.to_dict()
    hidden["current_mode"] = "combat"
    report = sensory.format_combat_report(combat_state, burt)
    return CombatStart(
        events=_combat_opening_events(report, opening.events_llm),
    )


def _remove_fleeing_residents(hidden: dict, node_id: str) -> list[str]:
    """§34: children and peasants run away from a killer."""
    events: list[str] = []
    for role_key in list(hidden.get("npcs_here") or []):
        if role_key in faith.FLEE_ROLES:
            npc_spawn.remove_npc(hidden, node_id, role_key)
            events.append(f"The {role_key} runs away.")
    return events


def _start_npc_fight(role_key: str, state: dict, rng) -> CombatStart:
    """§34: a hostile resident attacks.

    The cleric serves the queued god's wrath first (once, paladin ->
    killer). If the punishment kills Burt, no combat is started.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    events: list[str] = []

    if role_key == "cleric":
        damage = faith.take_punishment(state)
        if damage > 0:
            visible["hp"] = max(0, visible.get("hp", 0) - int(damage))
            hidden["hp_raw"] = visible["hp"]
            events.append(
                f"The gods demand a price. You take {damage} damage."
            )
            if visible["hp"] <= 0:
                hidden["death_cause_override"] = "god_wrath"
                hidden["combat"] = None
                hidden["combat_npc_role"] = None
                hidden["current_mode"] = "exploring"
                hidden["dialog_state"] = None
                events.append(sensory.format_sensory_report(visible))
                return CombatStart(events=events, game_over=True)

    enemy = npc_combat.enemy_key(role_key)
    if enemy is None:
        return CombatStart(events=events)

    started = _start_combat(
        [enemy], "enemy", hidden, visible, rng,
        opening_text=f"The {role_key} attacks!",
    )
    if started.game_over:
        hidden["combat_npc_role"] = None
        if hidden.get("death_cause_override") is None:
            hidden["death_cause_override"] = "combat"
    else:
        hidden["combat_npc_role"] = role_key
    return CombatStart(
        events=events + list(started.events),
        game_over=started.game_over,
    )


def _start_npc_hostility_if_any(state: dict, rng) -> CombatStart | None:
    """§34: start combat with the first hostile resident in this node."""
    hidden = state.setdefault("hidden", {})
    if hidden.get("combat") is not None:
        return None
    if hidden.get("current_mode") == "combat":
        return None
    role_key = npc_combat.hostile_role(
        list(hidden.get("npcs_here") or []), state,
    )
    if role_key is None:
        return None
    return _start_npc_fight(role_key, state, rng)


def _maybe_start_combat_on_enter(
    location_type: str,
    hidden: dict,
    visible: dict,
    rng,
) -> CombatStart | None:
    """Roll encounter on entering a location (O1: on-entry roll).

    TZ-9: non-ambush locations create pending_encounter instead of
    starting combat immediately. Only thicket (ambush) starts combat.
    """
    if hidden.get("combat") is not None:
        return None

    level = visible.get("level", 1)

    if location_type == _AMBUSH_LOCATION:
        enemies = spawn.ambush_for_level(level, rng(), rng())
        return _start_combat(enemies, "enemy", hidden, visible, rng)

    spawn_key = _ENCOUNTER_LOCATIONS.get(location_type)
    if spawn_key is None:
        return None

    roll = rng()
    if roll <= 2:
        enemies = spawn.spawn_for_level(
            spawn_key, level, rng(), rng(),
        )
        if enemies:
            enemy_keys = list(enemies)
            # TZ-10: lvl < 5 -> capped to single enemy, matching combat.
            if visible.get("level", 1) < 5 and len(enemy_keys) > 1:
                enemy_keys = enemy_keys[:1]
            # TZ-9: create pending encounter instead of starting combat
            hidden["pending_encounter"] = {
                "node_id": hidden.get("current_node_id", "start"),
                "enemy_keys": enemy_keys,
            }
            hidden["encounter_revealed"] = False
    return None


def _current_location_type(hidden: dict) -> str:
    graph = hidden.get("location_graph", {})
    node_id = hidden.get("current_node_id", "start")
    node = graph.get(node_id, {})
    return node.get("type", "")


def _handle_movement_failure(
    direction: str,
    move_result: str,
    hidden: dict,
    visible: dict,
    rng,
) -> ActionResult:
    """Movement failure (§11) — micro-location with 2 exits.

    One failure = strictly one event:
      fail    → only micro_event (lightning/tree/stone/god_wrath).
      fail_bad → only bad_movement_event (trap/sprain/ambush), micro skipped.
    """
    hidden["step"] = hidden.get("step", 0) + 1

    current_node = hidden.get("current_node_id", "start")
    graph = hidden.get("location_graph", {})
    current_node_data = graph.get(current_node, {})
    next_id = None
    if "exits" in current_node_data:
        next_id = current_node_data["exits"].get(direction)
    else:
        next_id = current_node_data.get(direction)

    # ── fail: only micro_event ──────────────────────────────
    if move_result == "fail":
        event_roll = rng()
        level = visible.get("level", 1)
        micro_event = resolve_micro_event(event_roll, level)
        damage = calculate_micro_damage(micro_event, rng)

        new_hp = visible.get("hp", 10) - damage
        if new_hp < 0:
            new_hp = 0
        visible["hp"] = new_hp
        hidden["hp_raw"] = new_hp

        if damage > 0:
            event_msg = (
                f"Failed to move {direction}. "
                f"Micro-event: {micro_event.event_type}. "
                f"Took {damage} damage."
            )
        else:
            event_msg = (
                f"Failed to move {direction}. "
                f"Micro-event: {micro_event.event_type}."
            )

        # ВАЖНО: Записываем микролокацию ДО проверки на смерть,
        # чтобы _determine_death_cause в main.py увидел причину
        hidden["micro_location"] = {
            "active": True,
            "source_node": current_node,
            "target_node": next_id,
            "direction": direction,
            "event_type": micro_event.event_type,
            "damage": damage,
        }

        inject = _MICRO_EVENT_TEXT.get(
            micro_event.event_type, "You stumble.",
        )

        if visible.get("hp", 0) <= 0:
            return ActionResult(events=[event_msg], game_over=True)

        return ActionResult(events=[event_msg], inject=inject)

    # ── fail_bad: only bad_movement_event (micro skipped) ───
    # move_result == "fail_bad"
    location_type = current_node_data.get("type") or ""
    is_dangerous = location_type in _ENCOUNTER_LOCATIONS

    bad_roll = rng()
    level = visible.get("level", 1)
    ev = resolve_bad_movement_event(
        bad_roll, level=level, rng=rng, is_dangerous=is_dangerous,
    )

    # Always include the base message so the log doesn't look empty
    events_list: list[str] = [f"Failed to move {direction}."]

    if ev.event_type != "nothing" and ev.description:
        events_list.append(ev.description)

    if ev.extra_damage > 0:
        events_list.append(f"Took {ev.extra_damage} extra damage.")
        new_hp = visible.get("hp", 10) - ev.extra_damage
        if new_hp < 0:
            new_hp = 0
        visible["hp"] = new_hp
        hidden["hp_raw"] = new_hp

    # ВАЖНО: записываем микролокацию ДО проверки на бой,
    # чтобы после боя Бурт остался в ловушке (с меню go_back/go_forward)
    hidden["micro_location"] = {
        "active": True,
        "source_node": current_node,
        "target_node": next_id,
        "direction": direction,
        "event_type": ev.event_type,
        "damage": ev.extra_damage,
    }

    inject = _BAD_EVENT_TEXT.get(ev.event_type)

    if visible.get("hp", 0) <= 0:
        return ActionResult(events=events_list, game_over=True)

    if ev.starts_combat:
        inject = _AMBUSH_TEXT
        spawn_key = _ENCOUNTER_LOCATIONS.get(location_type)
        if spawn_key is not None:
            enemies = spawn.spawn_for_level(
                spawn_key, visible.get("level", 1), rng(), rng(),
            )
            if enemies:
                started = _start_combat(
                    enemies, "enemy", hidden, visible, rng,
                )
                events_list.extend(started.events)
                return ActionResult(
                    events=events_list, game_over=started.game_over,
                    inject=inject,
                )

    return ActionResult(events=events_list, inject=inject)


def _arrive_at_node(
    node_id: str,
    graph: dict,
    hidden: dict,
    visible: dict,
    rng,
) -> tuple[str, "CombatStart | None"]:
    """Single arrival point for every way of entering a node.

    Used by go_*, go_forward and go_away_to_*. It:
      1. initializes an unentered node (§17),
      2. refreshes visible location name + exits,
      3. spawns NPCs of this node (§32) — see npc_spawn.ensure_npcs,
      4. rolls the encounter on entry (TZ-9).

    Returns (location_type, combat_started_or_None).
    """
    node = graph[node_id]
    if not node.get("entered", False):
        _enter_new_node(graph, node_id, rng)
        node = graph[node_id]

    loc_type = node.get("type") or ""
    visible["location"]["name"] = _resolve_location_name(loc_type, node_id)
    if "exits" in node:
        visible["location"]["exits"] = [
            d for d, t in node["exits"].items() if t
        ]
    else:
        visible["location"]["exits"] = [
            d for d in DIRECTIONS if node.get(d)
        ]

    # TZ-9: encounter roll must consume its dice first (tests rely on the
    # exact rng sequence), so NPC spawn runs after it.
    started = _maybe_start_combat_on_enter(loc_type, hidden, visible, rng)

    # §36: "visit" quests complete on entering the target location.
    quests.on_enter_location(loc_type, {"hidden": hidden, "visible": visible})

    # §32: who stands here (cached per node, never regenerated).
    if loc_type in npc_spawn.ROLE_SPAWN:
        npc_spawn.ensure_npcs(hidden, loc_type, node_id, rng)
    else:
        hidden["npcs_here"] = []

    # §9: the wandering mage may join the fixed role in temple / dungeon.
    # Runs last: its dice never shift the movement or NPC spawn order.
    npc_spawn.maybe_add_mage(hidden, loc_type, node_id, rng)

    state = {"hidden": hidden, "visible": visible}

    # §34: children and peasants run away from a killer.
    if faith.is_killer(state):
        _remove_fleeing_residents(hidden, node_id)

    # §34: a hostile resident attacks on meeting (arrival). Encounter
    # combat, if already started above, keeps priority.
    if started is None:
        started = _start_npc_hostility_if_any(state, rng)

    return loc_type, started


def _resolve_location_name(loc_type: str, node_id: str) -> str:
    """Resolve a location type to a human-readable name."""
    return _LOCATION_NAMES.get(loc_type, node_id)