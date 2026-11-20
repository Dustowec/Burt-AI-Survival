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
from burt import reputation
from burt import loot
from burt import search as search_mod
from burt import items
from burt.combat import CombatState, BurtStats
from burt.bestiary import ENEMIES
from burt.dice import (
    resolve_micro_event, calculate_micro_damage,
    resolve_movement_event, resolve_bad_movement_event,
)
from burt.npc import DialogueEngine, Outcome


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
}


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
    hp = visible.get("hp", 10)
    hp_max = visible.get("hp_max", 10)
    if step >= 19 or (hp_max > 0 and hp * 100 < hp_max * 25):
        actions.append(Action(key="sleep", label="Sleep"))
        if step >= 19:
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
    return actions


def _build_dialog_menu(visible: dict, state: dict,
                       engine: DialogueEngine | None) -> list[Action]:
    """Build dialog menu from engine.available_categories(role_key)."""
    if engine is None:
        return [Action(key="dialog_exit", label="Leave conversation")]
    hidden = state.get("hidden", {})
    ds = hidden.get("dialog_state")
    if ds is None:
        return []
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
    return actions


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
        if ev.event_type == "loot":
            visible["wallet"]["coin"] += ev.coin
        elif ev.event_type == "blessing":
            current_hp = visible.get("hp", 10)
            new_hp = min(current_hp + ev.hp_restore,
                         visible.get("hp_max", 10))
            visible["hp"] = new_hp
            hidden["hp_raw"] = new_hp
            current_mp = visible.get("mp", 3)
            new_mp = min(current_mp + ev.mp_restore,
                         visible.get("mp_max", 3))
            visible["mp"] = new_mp
            hidden["mp_raw"] = new_mp
        if ev.description:
            events_list = [sensory.format_sensory_report(visible)]
            events_list.insert(0, ev.description)
            return ActionResult(
                events=events_list,
                direction_moved=direction,
            )

    return ActionResult(
        events=[sensory.format_sensory_report(visible)],
        direction_moved=direction,
    )


def parse_choice(user_text: str, actions: list[Action]) -> Action:
    """Parse LLM response and return the chosen Action.

    Strategy (in order):
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

            # 1a. numeric index
            try:
                idx = int(choice)
                if 0 <= idx < len(actions):
                    return actions[idx]
            except ValueError:
                pass

            # 1b. action key (e.g. "attack_wolf_1")
            choice_lower = choice.lower()
            for action in actions:
                if action.key.lower() == choice_lower:
                    return action

            # 1c. label match (e.g. "Attack wolf")
            for action in actions:
                if action.label.lower() == choice_lower:
                    return action

            # 1d. substring: choice contains key or label
            for action in actions:
                if action.key.lower() in choice_lower:
                    return action
                if action.label.lower() in choice_lower:
                    return action

    # 2. Fallback: label/key/synonym anywhere in text (LAST match wins)
    text_lower = user_text.lower()
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

    if best_action is not None:
        return best_action

    # 3. Fallback: first action
    return actions[0]


def execute_action(action: Action, state: dict, rng=None,
                   dialogue_engine: DialogueEngine | None = None) -> ActionResult:
    """Execute an action and mutate state. Delegates to sub-modules.

    rng is a callable returning 1..6 (dice roll). Defaults to dice.roll_d6.
    """
    if rng is None:
        rng = dice.roll_d6
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    mode = hidden.get("current_mode", "exploring")

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
        visible["date"] = f"{hidden['day']} day(s)"
        return ActionResult(
            events=[
                f"Return to {source}.",
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
            if ev.event_type == "loot":
                visible["wallet"]["coin"] += ev.coin
            elif ev.event_type == "blessing":
                current_hp = visible.get("hp", 10)
                new_hp = min(current_hp + ev.hp_restore, visible.get("hp_max", 10))
                visible["hp"] = new_hp
                hidden["hp_raw"] = new_hp
                current_mp = visible.get("mp", 3)
                new_mp = min(current_mp + ev.mp_restore, visible.get("mp_max", 3))
                visible["mp"] = new_mp
                hidden["mp_raw"] = new_mp
            if ev.description:
                events_list = [sensory.format_sensory_report(visible)]
                events_list.insert(0, ev.description)
                return ActionResult(
                    events=events_list,
                    direction_moved=direction,
                )
        return ActionResult(
            events=[sensory.format_sensory_report(visible)],
            direction_moved=direction,
        )

    if action.key == "scroll":
        return ActionResult(events=[format_scroll(state)])

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
        hp_max = visible.get("hp_max", 10)
        mp_max = visible.get("mp_max", 3)
        new_hp, new_mp, new_effects = sleep_mod.apply_sleep(hp_max, mp_max)
        visible["hp"] = new_hp
        visible["mp"] = new_mp
        visible["effects"] = new_effects
        hidden["hp_raw"] = new_hp
        hidden["mp_raw"] = new_mp
        eat, res = hunger.reset_hunger_after_sleep()
        visible["eat"] = eat
        visible["sleep_counter"] = 0
        hidden["day"] = hidden.get("day", 1) + 1
        hidden["step"] = 0
        visible["date"] = f"{hidden['day']} day(s)"
        hidden["day_log"] = []
        if not hidden.get("diary_written_today", False):
            hidden["diary"] = None
            hidden["diary_skipped_today"] = True
        hidden["diary_written_today"] = False
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

    if result.outcome == "ongoing":
        hidden["combat"] = result.combat.to_dict()
        hidden["current_mode"] = "combat"
        report = sensory.format_combat_report(result.combat, result.burt)
        events.append(report)
    else:
        hidden["combat"] = None
        hidden["current_mode"] = "exploring"
        if result.outcome == "burt_won":
            dead_enemies = [e for e in result.combat.enemies if not e.alive]
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
                else:
                    events.append("Loot: nothing.")
                for quest_id in ready_quests:
                    events.append(
                        f"Quest ready to report: {_quest_title(quest_id)}."
                    )
        if result.outcome == "burt_died":
            action_result.game_over = True

    return action_result


def _build_burt_stats(visible: dict, hidden: dict) -> BurtStats:
    """Assemble BurtStats from visible + hidden for combat."""
    spells = hidden.get("spells") or {}
    if not isinstance(spells, dict):
        spells = {}
    element = spells.get("element")
    alignment = spells.get("alignment")
    spells_available = (element is not None) or (alignment is not None)

    return BurtStats(
        hp=visible["hp"],
        hp_max=visible["hp_max"],
        mp=visible["mp"],
        mp_max=visible["mp_max"],
        spells_available=spells_available,
    )


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
    """Enter dialog mode with the given NPC role."""
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    hidden["current_mode"] = "dialog"
    hidden["dialog_state"] = {
        "role_key": role_key,
        "is_angry": False,
        "turn": 0,
        "anger_lock_until": None,
        "bonus_used": False,
        "quest_state": quests.quest_state_for_role(role_key, state),
        "rep_applied": False,
    }
    hidden["step"] = hidden.get("step", 0) + 1
    hidden["last_action"] = action.key
    hidden["same_action_count"] = 1
    return ActionResult(
        events=[
            f"You approach the {role_key}.",
            sensory.format_sensory_report(visible),
        ]
    )


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
        hidden["current_mode"] = "exploring"
        hidden["dialog_state"] = None
        hidden["step"] = hidden.get("step", 0) + 1
        # §16: the next talk may change reputation again.
        reputation.reset_dialog_rep(state)
        return ActionResult(
            events=["You leave the conversation.",
                    sensory.format_sensory_report(visible)]
        )

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

    return execute_dialog(action, state, engine, rng, category=category)


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
        elif q.type in ("kill", "visit", "talk", "help"):
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

        deadline = entry.get("deadline_day")
        if deadline is None:
            left = "no deadline"
        else:
            days_left = max(0, deadline - day)
            left = f"{days_left} days left"

        lines.append(f"{title} — {progress}, {left}")
    return "\n".join(lines) + "\n"


def _quest_title(quest_id: str) -> str:
    try:
        templates = quests._load_templates()
    except (OSError, ValueError):
        return quest_id
    return templates.get(quest_id, {}).get("title", quest_id)


def execute_dialog(action: Action, state: dict, engine: DialogueEngine, rng,
                   *, category: str | None = None) -> ActionResult:
    """Execute one dialogue turn.

    Rebuilds Session from dialog_state + visible, calls Session.say(),
    applies Result back to state.
    """
    hidden = state.setdefault("hidden", {})
    visible = state.setdefault("visible", {})
    ds = hidden.get("dialog_state")
    if ds is None:
        return error_result("no active dialog")

    cat = category or action.key[len("dialog_"):]
    roll = rng()
    # second_roll: deterministic default for tests (4 = no bonus)
    second_roll = rng()

    # Rebuild session from persisted state
    role_key = ds.get("role_key", "")
    hp = visible.get("hp", 10)
    coins = visible.get("wallet", {}).get("coin", 100)
    reputation_bonus = hidden.get("reputation", {}).get(role_key, 0)

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

    result = session.say(cat, roll=roll, second_roll=second_roll)

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

    # Advance turn counter
    hidden["step"] = hidden.get("step", 0) + 1

    # §16: one reputation change per dialogue, on the first reply only.
    if cat not in ("exit", "quest"):
        delta = reputation.dialogue_delta(result.outcome, result.became_angry)
        reputation.apply_dialog_rep(state, role_key, delta)

    events = [result.text]
    if result.bonus is not None:
        events.append(f"Bonus: {result.bonus.get('type', '')}")
    events.append(sensory.format_sensory_report(visible))

    return ActionResult(events=events)


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
    opening = combat.resolve_free_strike(combat_state, burt, rng)
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

    if location_type == _AMBUSH_LOCATION:
        enemies = spawn.spawn_ambush(rng(), rng())
        return _start_combat(enemies, "enemy", hidden, visible, rng)

    spawn_key = _ENCOUNTER_LOCATIONS.get(location_type)
    if spawn_key is None:
        return None

    roll = rng()
    if roll <= 2:
        enemies = spawn.spawn_random(spawn_key, rng(), rng())
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

        if visible.get("hp", 0) <= 0:
            return ActionResult(events=[event_msg], game_over=True)

        return ActionResult(events=[event_msg])

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

    if visible.get("hp", 0) <= 0:
        return ActionResult(events=events_list, game_over=True)

    if ev.starts_combat:
        spawn_key = _ENCOUNTER_LOCATIONS.get(location_type)
        if spawn_key is not None:
            enemies = spawn.spawn_random(spawn_key, rng(), rng())
            if enemies:
                started = _start_combat(
                    enemies, "enemy", hidden, visible, rng,
                )
                events_list.extend(started.events)
                return ActionResult(
                    events=events_list, game_over=started.game_over,
                )

    return ActionResult(events=events_list)


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

    return loc_type, started


def _resolve_location_name(loc_type: str, node_id: str) -> str:
    """Resolve a location type to a human-readable name."""
    return _LOCATION_NAMES.get(loc_type, node_id)