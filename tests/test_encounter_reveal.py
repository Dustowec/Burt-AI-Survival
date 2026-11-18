"""TZ-9: encounter reveal via osmotret; ambush only in thicket.

Contract tests for the encounter-pending flow:
- entering non-ambush encounter location creates pending_encounter (no combat)
- thicket still starts combat immediately (enemy initiative, Ambush!)
- osmotret reveals a valid pending encounter ("You see:" once)
- build_menu restricts to attack_* / go_away_to_* after reveal
- attack_{enemy_id} starts combat with burt initiative, one step, no free strike
- go_away_to_{direction} leaves clearing pending, normal movement
- invalid targets/directions keep pending and error
- stale pending self-heals (no soft-lock)
- search in forest still works while encounter is unrevealed

All helpers/docs in English. No Cyrillic literals.
"""

from burt.loop import (
    Action, build_menu, execute_action,
)
from burt.combat import start_combat
from burt import world


# ---- Helpers ---------------------------------------------------

def make_start_state():
    """State at the world start node (crossroads), ready for go_."""
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": "exploring",
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "combat": None,
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 0, "day": 1,
            "pending_encounter": None,
            "encounter_revealed": False,
        },
    }



def make_forest_state():
    """State with Burt inside the south node (forest, an encounter
    location). pending_encounter is valid only in such nodes."""
    st = make_start_state()
    h = st["hidden"]
    nid = h["location_graph"]["start"]["exits"]["south"]
    h["current_node_id"] = nid
    st["visible"]["location"]["name"] = "Forest"
    return st


def set_pending(hidden, enemy_keys, node_id=None):
    """Set a pending encounter (unrevealed) for the current node."""
    if node_id is None:
        node_id = hidden.get("current_node_id", "start")
    hidden["pending_encounter"] = {
        "node_id": node_id,
        "enemy_keys": list(enemy_keys),
    }
    hidden["encounter_revealed"] = False


def _seq_rng(values):
    """Deterministic cycling rng (last value repeats)."""
    values = list(values)
    if not values:
        raise ValueError("_seq_rng needs at least one value")
    holder = {"i": 0}

    def _rng():
        i = min(holder["i"], len(values) - 1)
        holder["i"] += 1
        return values[i]

    return _rng


def _current_type(state):
    h = state["hidden"]
    node = h["location_graph"].get(h["current_node_id"], {})
    return node.get("type", "")


# 1-4: on-entry spawn behavior -----------------------------------

class TestOnEntryEncounter:
    def test_enter_encounter_location_creates_pending_not_combat(self):
        st = make_start_state()
        # go_south -> forest. move=4, node rolls 4,4,4,4, enc=1,
        # spawn_type=4 (wolf), spawn_size=6 (1 wolf).
        rng = _seq_rng([4, 4, 4, 4, 4, 1, 4, 6])
        execute_action(Action("go_south", "Go"), st, rng=rng)
        h = st["hidden"]
        assert h["current_mode"] == "exploring"
        assert h["combat"] is None
        pe = h["pending_encounter"]
        assert isinstance(pe, dict)
        assert pe["node_id"] == h["current_node_id"]
        assert pe["enemy_keys"] == ["wolf"]
        assert h["encounter_revealed"] is False

    def test_enter_encounter_location_no_spawn_no_pending(self):
        st = make_start_state()
        # enc roll=3 (>2) -> no spawn.
        rng = _seq_rng([4, 4, 4, 4, 4, 3, 4, 6])
        execute_action(Action("go_south", "Go"), st, rng=rng)
        h = st["hidden"]
        assert h["current_mode"] == "exploring"
        assert h["combat"] is None
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False

    def test_enter_encounter_location_empty_spawn_no_pending(self, monkeypatch):
        from burt import loop
        monkeypatch.setattr(loop.spawn, "spawn_random", lambda *a: [])
        st = make_start_state()
        # enc roll=1 means spawn attempted, but returns empty.
        rng = _seq_rng([4, 4, 4, 4, 4, 1, 4, 6])
        execute_action(Action("go_south", "Go"), st, rng=rng)
        h = st["hidden"]
        assert h["current_mode"] == "exploring"
        assert h["combat"] is None
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False

    def test_thicket_ambush_starts_combat_enemy_no_pending(self):
        st = make_start_state()
        # go_east -> thicket (ambush). move=4, node rolls 4,4,4,4,
        # ambush_type=1 (wolf), ambush_size=1.
        rng = _seq_rng([4, 4, 4, 4, 4, 1, 1])
        execute_action(Action("go_east", "Go"), st, rng=rng)
        h = st["hidden"]
        assert h["current_mode"] == "combat"
        assert h["combat"] is not None
        assert h["combat"]["initiative"] == "enemy"
        assert h["combat"]["free_strike_done"] is False
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False


# 5-7: osmotret reveal -------------------------------------------

class TestOsMotretReveal:
    def test_osmotret_reveals_valid_pending(self):
        st = make_forest_state()
        set_pending(st["hidden"], ["wolf"])
        result = execute_action(Action("osmotret", "Look"), st, rng=lambda: 1)
        h = st["hidden"]
        assert h["encounter_revealed"] is True
        assert h["pending_encounter"]["enemy_keys"] == ["wolf"]
        assert any(ev.startswith("You see:") for ev in result.events)

    def test_osmotret_stale_pending_clears_and_no_reveal(self):
        st = make_start_state()
        # pending belongs to another node -> invalid
        set_pending(st["hidden"], ["wolf"], node_id="other_node")
        result = execute_action(Action("osmotret", "Look"), st, rng=lambda: 1)
        h = st["hidden"]
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False
        assert not any(ev.startswith("You see:") for ev in result.events)

    def test_osmotret_no_pending_no_reveal(self):
        st = make_start_state()
        result = execute_action(Action("osmotret", "Look"), st, rng=lambda: 1)
        h = st["hidden"]
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False
        assert not any(ev.startswith("You see:") for ev in result.events)


# 8-10: build_menu ------------------------------------------------

class TestEncounterMenu:
    def test_build_menu_revealed_only_attack_and_go_away(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        menu = build_menu(st["visible"], st)
        keys = [a.key for a in menu]
        # Must contain attack_* and go_away_to_* only.
        assert any(k.startswith("attack_") for k in keys)
        assert any(k.startswith("go_away_to_") for k in keys)
        for a in menu:
            assert a.key.startswith("attack_") or a.key.startswith("go_away_to_")
        for forbidden in ("osmotret", "search", "sleep", "eat_food",
                          "drink_water", "go_north", "go_east",
                          "go_south", "go_west"):
            assert forbidden not in keys

    def test_build_menu_enemy_ids_match_combat_start(self):
        st = make_forest_state()
        h = st["hidden"]
        enemy_keys = ["wolf", "wolf", "goblin"]
        set_pending(h, enemy_keys)
        h["encounter_revealed"] = True
        menu = build_menu(st["visible"], st)
        combat_ids = [e.id for e in start_combat(enemy_keys, "burt").enemies]
        attack_ids = sorted(
            a.target_id for a in menu if a.key.startswith("attack_")
        )
        assert attack_ids == sorted(combat_ids)

    def test_build_menu_invalid_pending_self_heals(self):
        st = make_start_state()
        h = st["hidden"]
        h["pending_encounter"] = None
        h["encounter_revealed"] = True  # stale flag
        menu = build_menu(st["visible"], st)
        assert h["encounter_revealed"] is False
        # Normal exploration menu restored, osmotret present -> no soft-lock.
        assert any(a.key == "osmotret" for a in menu)


# 11-12: attack from revealed encounter ---------------------------

class TestEncounterAttack:
    def test_attack_from_reveal_starts_combat_burt_initiative_only_starts(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        step_before = h["step"]
        result = execute_action(
            Action("attack_wolf_1", "Attack wolf", target_id="wolf_1"),
            st, rng=lambda: 1,
        )
        assert h["current_mode"] == "combat"
        assert h["combat"]["initiative"] == "burt"
        assert h["combat"]["free_strike_done"] is True
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False
        assert h["step"] == step_before + 1
        # Only start - no actual Burt attack, no Ambush.
        assert not any(ev.startswith("You hit") or ev.startswith("You missed")
                       for ev in result.events)
        assert not any("Ambush!" in ev for ev in result.events)

    def test_attack_from_reveal_starts_combat_no_ambush(self):
        # Same flow but verify no "Ambush!" text in the combat report.
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        result = execute_action(
            Action("attack_wolf_1", "Attack wolf", target_id="wolf_1"),
            st, rng=lambda: 1,
        )
        joined = "\n".join(result.events)
        assert "Ambush!" not in joined

    def test_attack_invalid_target_does_not_start_combat(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        step_before = h["step"]
        result = execute_action(
            Action("attack_bogus_1", "Attack bogus", target_id="bogus_1"),
            st, rng=lambda: 1,
        )
        assert any(ev.startswith("Error:") for ev in result.events)
        assert h["current_mode"] == "exploring"
        assert h["combat"] is None
        assert h["step"] == step_before
        assert h["pending_encounter"] is not None
        assert h["encounter_revealed"] is True


# 13-14: go_away_to_ ----------------------------------------------

class TestGoAway:
    def test_go_away_valid_exit_clears_and_moves_once(self):
        st = make_start_state()
        h = st["hidden"]
        # Move to south node (forest) with pending, then go_away back.
        target_id = h["location_graph"]["start"]["exits"]["south"]
        h["current_node_id"] = target_id
        set_pending(h, ["wolf"], node_id=target_id)
        h["encounter_revealed"] = True
        step_before = h["step"]
        rng = _seq_rng([4, 4, 4, 4, 4, 3])
        result = execute_action(
            Action("go_away_to_north", "Go away"), st, rng=rng,
        )
        assert h["current_node_id"] == "start"
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False
        assert h["combat"] is None
        assert h["step"] == step_before + 1
        assert result.direction_moved == "north"

    def test_go_away_move_event_and_last_action_like_normal_go(self):
        st = make_forest_state()
        h = st["hidden"]
        target_id = h["current_node_id"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        h["step"] = 2
        wallet_before = st["visible"]["wallet"]["coin"]
        # move roll=5 (normal -> loot +1 coin), no encounter in target.
        rng = _seq_rng([5, 3])
        result = execute_action(
            Action("go_away_to_north", "Go away"), st, rng=rng,
        )
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False
        assert h["last_action"] == "go_away_to_north"
        assert h["same_action_count"] == 1
        assert st["visible"]["wallet"]["coin"] == wallet_before + 1
        assert result.direction_moved == "north"

    def test_go_away_invalid_exit_keeps_pending(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        step_before = h["step"]
        result = execute_action(
            Action("go_away_to_notadirection", "Go away"), st, rng=lambda: 4,
        )
        assert any(ev.startswith("Error:") for ev in result.events)
        assert h["current_node_id"] == h["pending_encounter"]["node_id"]
        assert h["pending_encounter"]["enemy_keys"] == ["wolf"]
        assert h["encounter_revealed"] is True
        assert h["step"] == step_before


# 15: normal go with unrevealed pending ---------------------------

class TestNormalGoUnrevealed:
    def test_normal_go_clears_pending_on_valid_attempt(self):
        st = make_start_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        # Unrevealed: normal go_* should clear pending on valid attempt.
        step_before = h["step"]
        rng = _seq_rng([4, 4, 4, 4, 4, 6])
        execute_action(Action("go_south", "Go"), st, rng=rng)
        assert h["pending_encounter"] is None
        assert h["encounter_revealed"] is False
        assert h["step"] == step_before + 1

    def test_normal_go_invalid_keeps_pending(self):
        st = make_start_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        step_before = h["step"]
        result = execute_action(
            Action("go_notadirection", "Go"), st, rng=lambda: 4,
        )
        assert any(ev.startswith("Error:") for ev in result.events)
        assert h["pending_encounter"]["enemy_keys"] == ["wolf"]
        assert h["step"] == step_before


# 16: search still works while unrevealed -------------------------

class TestSearchWhilePending:
    def test_search_works_unrevealed_pending_in_forest(self):
        st = make_start_state()
        h = st["hidden"]
        # Move Burt to the south node (forest).
        target_id = h["location_graph"]["start"]["exits"]["south"]
        h["current_node_id"] = target_id
        st["visible"]["location"]["name"] = "Forest"
        set_pending(h, ["wolf"])
        step_before = h["step"]
        # search roll=5 (success), picks rng=1 -> mushrooms.
        rng = _seq_rng([5, 1])
        result = execute_action(Action("search", "Search"), st, rng=rng)
        assert h["pending_encounter"] is not None
        assert h["encounter_revealed"] is False
        assert h["step"] == step_before + 1
        assert any("Found:" in ev for ev in result.events)

    def test_search_blocked_when_revealed(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        step_before = h["step"]
        result = execute_action(
            Action("search", "Search"), st, rng=lambda: 5,
        )
        assert any(ev.startswith("Error:") for ev in result.events)
        assert h["pending_encounter"]["enemy_keys"] == ["wolf"]
        assert h["step"] == step_before


# 16-17: first combat round after encounter attack ----------------

class TestPostEncounterCombat:
    def test_first_combat_round_after_encounter_attack_has_no_ambush(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        execute_action(
            Action("attack_wolf_1", "Attack wolf", target_id="wolf_1"),
            st, rng=lambda: 1,
        )
        assert h["current_mode"] == "combat"
        # First real round: Burt attacks (roll 5 = max dmg 2), wolf stays
        # alive (8 hp); wolf attacks (roll 1 = miss).
        rng = _seq_rng([5, 1])
        result = execute_action(
            Action("attack_wolf_1", "Attack wolf", target_id="wolf_1"),
            st, rng=rng,
        )
        joined = "\n".join(result.events)
        assert "Ambush!" not in joined
        # First LLM event belongs to Burt.
        burt_events = [ev for ev in result.events
                       if ev.startswith("You hit") or ev.startswith("You missed")
                       or ev.startswith("You killed")]
        assert burt_events, result.events

    def test_step_frozen_during_subsequent_combat_actions(self):
        st = make_forest_state()
        h = st["hidden"]
        set_pending(h, ["wolf"])
        h["encounter_revealed"] = True
        execute_action(
            Action("attack_wolf_1", "Attack wolf", target_id="wolf_1"),
            st, rng=lambda: 1,
        )
        step_after_start = h["step"]
        rng = _seq_rng([5, 1])
        execute_action(
            Action("attack_wolf_1", "Attack wolf", target_id="wolf_1"),
            st, rng=rng,
        )
        assert h["step"] == step_after_start
        execute_action(Action("block", "Block"), st, rng=rng)
        assert h["step"] == step_after_start
