"""Тесты loop.py — §26, синхронное ядро игрового цикла.

Покрывают build_menu, parse_choice, execute_action, should_sleep,
error_result, _resolve_location_name.

Боевой стык с combat.resolve_round — отдельно в test_loop_combat.py,
здесь только меню боя (что visible -> Action[]).

Восстановлен после случайной перезаписи (HANDOFF-8).
"""

import pytest

from burt.loop import (
    Action, ActionResult,
    build_menu, parse_choice, execute_action,
    should_sleep, error_result, _resolve_location_name,
    DIRECTIONS, SLEEP_THRESHOLD, CRITICAL_HP_RATIO,
)
from burt.combat import start_combat
from burt.bestiary import ENEMIES


# ─── Общий помощник ────────────────────────────────────────

def make_state(mode="exploring", with_meta=True):
    """Базовое state: exploring, 4 выхода, world-граф старта."""
    from burt import world
    state = {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [
                {"name": "bread", "count": 2},
                {"name": "water", "count": 1},
            ],
            "wallet": {"gold": 0, "silver": 5, "copper": 0},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": mode,
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 0, "day": 1,
        },
    }
    if with_meta:
        state["meta"] = {
            "life": 1, "day": 1, "step": 0,
            "session_uuid": "test", "session_started": "2026-01-01T00:00:00",
            "config_hash": "v0.7.0",
        }
    return state


def _keys(actions):
    return [a.key for a in actions]


def _combat_key():
    """Любой враг из bestiary."""
    return next(iter(ENEMIES))


# ─── build_menu: exploring ─────────────────────────────────

class TestBuildMenuExploring:
    def test_has_osmotret(self):
        st = make_state()
        assert "osmotret" in _keys(build_menu(st["visible"], st))

    def test_has_go_for_each_exit(self):
        st = make_state()
        keys = _keys(build_menu(st["visible"], st))
        for d in st["visible"]["location"]["exits"]:
            assert f"go_{d}" in keys

    def test_no_go_for_direction_not_in_exits(self):
        st = make_state()
        st["visible"]["location"]["exits"] = ["north"]
        keys = _keys(build_menu(st["visible"], st))
        assert "go_north" in keys
        assert "go_east" not in keys
        assert "go_south" not in keys
        assert "go_west" not in keys

    def test_has_search(self):
        st = make_state()
        assert "search" in _keys(build_menu(st["visible"], st))

    def test_sleep_absent_at_step_0(self):
        st = make_state()
        st["hidden"]["step"] = 0
        assert "sleep" not in _keys(build_menu(st["visible"], st))

    def test_sleep_present_at_step_19(self):
        st = make_state()
        st["hidden"]["step"] = 19
        assert "sleep" in _keys(build_menu(st["visible"], st))

    def test_sleep_present_at_critical_hp(self):
        st = make_state()
        st["visible"]["hp"] = 2
        st["visible"]["hp_max"] = 10
        assert "sleep" in _keys(build_menu(st["visible"], st))

    def test_eat_food_present_with_bread(self):
        st = make_state()
        st["visible"]["inventory"] = [{"name": "bread", "count": 1}]
        assert "eat_food" in _keys(build_menu(st["visible"], st))

    def test_drink_water_present_with_water(self):
        st = make_state()
        st["visible"]["inventory"] = [{"name": "water", "count": 1}]
        assert "drink_water" in _keys(build_menu(st["visible"], st))

    def test_no_eat_food_without_bread(self):
        st = make_state()
        st["visible"]["inventory"] = [{"name": "sword", "count": 1}]
        keys = _keys(build_menu(st["visible"], st))
        assert "eat_food" not in keys
        assert "drink_water" not in keys


# ─── build_menu: dialog ────────────────────────────────────

class TestBuildMenuDialog:
    def test_only_exit_dialog(self):
        st = make_state("dialog")
        actions = build_menu(st["visible"], st)
        assert _keys(actions) == ["exit_dialog"]


# ─── build_menu: combat ────────────────────────────────────

class TestBuildMenuCombat:
    def test_attack_line_per_live_enemy(self):
        st = make_state("combat")
        cs = start_combat([_combat_key()], "burt")
        st["hidden"]["combat"] = cs.to_dict()
        keys = _keys(build_menu(st["visible"], st))
        assert f"attack_{cs.enemies[0].id}" in keys

    def test_block_and_flee_present(self):
        st = make_state("combat")
        cs = start_combat([_combat_key()], "burt")
        st["hidden"]["combat"] = cs.to_dict()
        keys = _keys(build_menu(st["visible"], st))
        assert "block" in keys
        assert "flee" in keys

    def test_no_attack_for_dead_enemy(self):
        st = make_state("combat")
        cs = start_combat([_combat_key()], "burt")
        cs.enemies[0].alive = False
        st["hidden"]["combat"] = cs.to_dict()
        keys = _keys(build_menu(st["visible"], st))
        assert f"attack_{cs.enemies[0].id}" not in keys
        assert "block" not in keys
        assert "flee" not in keys

    def test_empty_when_combat_missing(self):
        st = make_state("combat")
        st["hidden"]["combat"] = None
        assert build_menu(st["visible"], st) == []


# ─── parse_choice (базовые) ────────────────────────────────

class TestParseChoice:
    def _two(self):
        return [Action("a", "A"), Action("b", "B")]

    def test_numbered_zero(self):
        assert parse_choice("CHOICE: 0", self._two()).key == "a"

    def test_numbered_one(self):
        assert parse_choice("CHOICE: 1", self._two()).key == "b"

    def test_prefix_match_by_label(self):
        actions = [Action("special", "Secret passage")]
        assert parse_choice(
            "I take the Secret passage now", actions,
        ).key == "special"

    def test_fallback_first_on_unknown(self):
        assert parse_choice("qwerty", self._two()).key == "a"

    def test_empty_menu_returns_osmotret(self):
        assert parse_choice("CHOICE: 0", []).key == "osmotret"

    def test_invalid_number_fallback(self):
        assert parse_choice("CHOICE: 99", self._two()).key == "a"


# ─── parse_choice: синонимы + rfind (П.1) ──────────────────

class TestParseChoiceSynonyms:
    """П.1: text fallback with verb synonyms; last mention wins."""

    def _menu(self):
        return [
            Action("osmotret", "Look around"),
            Action("go_north", "Go north"),
            Action("go_east", "Go east"),
            Action("search", "Search"),
        ]

    def test_walk_north_synonym(self):
        assert parse_choice("I walk north.", self._menu()).key == "go_north"

    def test_step_north_synonym(self):
        assert parse_choice("I step north.", self._menu()).key == "go_north"

    def test_head_north_synonym(self):
        assert parse_choice("I head north.", self._menu()).key == "go_north"

    def test_look_around_synonym(self):
        assert parse_choice("I look around.", self._menu()).key == "osmotret"

    def test_check_surroundings_synonym(self):
        assert parse_choice(
            "I check my surroundings.", self._menu(),
        ).key == "osmotret"

    def test_last_mention_wins(self):
        text = "I look around. Then I walk north."
        assert parse_choice(text, self._menu()).key == "go_north"

    def test_last_mention_wins_reverse(self):
        text = "I walk north. Then I look around."
        assert parse_choice(text, self._menu()).key == "osmotret"

    def test_rummage_for_search(self):
        assert parse_choice("I rummage.", self._menu()).key == "search"

    def test_look_for_is_search_not_osmotret(self):
        assert parse_choice("I look for food.", self._menu()).key == "search"

    def test_eat_synonym(self):
        menu = [
            Action("osmotret", "Look around"),
            Action("eat_food", "Eat food"),
        ]
        assert parse_choice("I eat the bread.", menu).key == "eat_food"

    def test_choice_number_wins_over_text(self):
        # CHOICE: 0 wins even though text mentions walk north.
        text = "I walk north.\nCHOICE: 0"
        assert parse_choice(text, self._menu()).key == "osmotret"

    def test_empty_choice_falls_to_text(self):
        # "CHOICE:" with nothing after -> text fallback.
        text = "CHOICE:\nI walk north."
        assert parse_choice(text, self._menu()).key == "go_north"


# ─── execute_action: мирные действия ───────────────────────

class TestExecuteActionExploring:
    def test_osmotret_returns_report_and_increments_step(self):
        st = make_state()
        result = execute_action(Action("osmotret", "Look"), st)
        assert isinstance(result, ActionResult)
        assert st["hidden"]["step"] == 1
        assert len(result.events) >= 1

    def test_go_north_moves_and_increments_step(self):
        st = make_state()
        result = execute_action(Action("go_north", "Go"), st,
                                rng=lambda: 4)
        assert st["hidden"]["current_node_id"] != "start"
        assert st["hidden"]["step"] == 1
        assert st["visible"]["location"]["name"] == "Road"
        assert isinstance(result, ActionResult)

    def test_go_invalid_direction_returns_error(self):
        st = make_state()
        result = execute_action(Action("go_up", "Go"), st)
        assert any("error" in ev.lower() for ev in result.events)
        assert st["hidden"]["step"] == 0

    def test_sleep_restores_hp_and_mp(self):
        st = make_state()
        st["visible"]["hp"] = 3
        st["visible"]["mp"] = 1
        st["hidden"]["hp_raw"] = 3
        st["hidden"]["mp_raw"] = 1
        result = execute_action(Action("sleep", "Sleep"), st)
        assert st["visible"]["hp"] == st["visible"]["hp_max"]
        assert st["visible"]["mp"] == st["visible"]["mp_max"]
        assert st["hidden"]["hp_raw"] == st["visible"]["hp_max"]
        assert st["hidden"]["mp_raw"] == st["visible"]["mp_max"]
        assert st["hidden"]["day"] == 2
        assert st["hidden"]["step"] == 0
        assert isinstance(result, ActionResult)

    def test_sleep_resets_effects(self):
        st = make_state()
        st["visible"]["effects"] = ["blessed", "cursed"]
        execute_action(Action("sleep", "Sleep"), st)
        assert st["visible"]["effects"] == []

    def test_unknown_action_returns_error(self):
        st = make_state()
        result = execute_action(Action("teleport", "TP"), st)
        assert any("error" in ev.lower() for ev in result.events)


# ─── should_sleep ──────────────────────────────────────────

class TestShouldSleep:
    def test_true_at_sleep_threshold(self):
        st = make_state()
        st["visible"]["sleep_counter"] = SLEEP_THRESHOLD
        assert should_sleep(st["visible"], st) is True

    def test_false_when_fresh(self):
        st = make_state()
        st["visible"]["sleep_counter"] = 5
        assert should_sleep(st["visible"], st) is False

    def test_true_at_critical_hp(self):
        st = make_state()
        st["visible"]["hp"] = 1
        st["visible"]["hp_max"] = 10
        assert should_sleep(st["visible"], st) is True

    def test_false_when_healthy(self):
        st = make_state()
        st["visible"]["hp"] = 8
        st["visible"]["hp_max"] = 10
        assert should_sleep(st["visible"], st) is False


# ─── error_result ──────────────────────────────────────────

class TestErrorResult:
    def test_returns_action_result(self):
        r = error_result("boom")
        assert isinstance(r, ActionResult)

    def test_events_contain_message_with_prefix(self):
        r = error_result("boom")
        assert len(r.events) == 1
        assert "boom" in r.events[0]
        assert "error" in r.events[0].lower()


# ─── _resolve_location_name ────────────────────────────────

class TestResolveLocationName:
    def test_known_type_crossroads(self):
        assert _resolve_location_name("crossroads", "start") == "Crossroads"

    def test_known_type_forest(self):
        assert _resolve_location_name("forest", "forest_1") == "Forest"

    def test_unknown_type_falls_back_to_node_id(self):
        assert _resolve_location_name("zxc", "node_42") == "node_42"

    def test_empty_type_falls_back(self):
        assert _resolve_location_name("", "abc") == "abc"


# ─── osmotret repeat punishment (§25.1) ────────────────────

class TestOsmotretPunishment:
    """3rd+ osmotret in a row costs 1 HP (scared behavior)."""

    def test_first_osmotret_normal(self):
        st = make_state()
        r = execute_action(Action("osmotret", "Look"), st)
        assert st["visible"]["hp"] == 10
        assert not any("branch" in e.lower() for e in r.events)

    def test_second_osmotret_warns(self):
        st = make_state()
        execute_action(Action("osmotret", "Look"), st)
        r = execute_action(Action("osmotret", "Look"), st)
        assert st["visible"]["hp"] == 10
        assert any("nothing has changed" in e.lower() for e in r.events)

    def test_third_osmotret_damages(self):
        st = make_state()
        execute_action(Action("osmotret", "Look"), st)
        execute_action(Action("osmotret", "Look"), st)
        r = execute_action(Action("osmotret", "Look"), st)
        assert st["visible"]["hp"] == 9
        assert st["hidden"]["hp_raw"] == 9
        assert any("branch" in e.lower() for e in r.events)

    def test_fourth_osmotret_damages_again(self):
        st = make_state()
        for _ in range(3):
            execute_action(Action("osmotret", "Look"), st)
        r = execute_action(Action("osmotret", "Look"), st)
        assert st["visible"]["hp"] == 8
        assert any("branch" in e.lower() for e in r.events)

    def test_other_action_resets_counter(self):
        st = make_state()
        execute_action(Action("osmotret", "Look"), st)
        execute_action(Action("osmotret", "Look"), st)
        execute_action(Action("search", "Search"), st, rng=lambda: 3)
        r = execute_action(Action("osmotret", "Look"), st)
        assert st["visible"]["hp"] == 10
        assert not any("nothing has changed" in e.lower() for e in r.events)

    def test_osmotret_can_kill(self):
        st = make_state()
        st["visible"]["hp"] = 1
        st["hidden"]["hp_raw"] = 1
        execute_action(Action("osmotret", "Look"), st)
        execute_action(Action("osmotret", "Look"), st)
        r = execute_action(Action("osmotret", "Look"), st)
        assert st["visible"]["hp"] == 0
        assert r.game_over is True

    class TestLethalMovement:
        """Проверка, что смертельный урон от микро-события вызывает game_over (даже при обычном fail)."""

        def test_movement_fail_can_kill(self):
            st = make_state()
            st["visible"]["hp"] = 1
            st["hidden"]["hp_raw"] = 1
            
            # rng side_effect:
            # 1. move_roll (2 -> fail)
            # 2. event_roll (6 -> lightning)
            # 3+. damage_roll (6 -> max damage)
            rolls = [2, 6, 6, 6, 6, 6, 6, 6, 6]
            def rng():
                return rolls.pop(0) if rolls else 6

            result = execute_action(Action("go_north", "Go"), st, rng=rng)
            
            assert st["visible"]["hp"] == 0
            assert result.game_over is True, "Должен быть game_over, если HP упало до 0 от молнии"

        def test_movement_fail_lightning_sets_micro_location_before_death(self):
            st = make_state()
            st["visible"]["hp"] = 10
            st["hidden"]["hp_raw"] = 10
            
            # rng: move_roll=2 (fail), event_roll=3 (lightning), damage_roll=6 (max 3d6)
            rolls = [2, 3, 6, 6, 6]
            def rng():
                return rolls.pop(0) if rolls else 6

            result = execute_action(Action("go_north", "Go"), st, rng=rng)
            
            assert st["visible"]["hp"] == 0
            assert result.game_over is True
            # ГЛАВНОЕ: micro_location должен быть записан, чтобы main.py увидел причину
            assert st["hidden"]["micro_location"]["active"] is True
            assert st["hidden"]["micro_location"]["event_type"] == "lightning"
            assert st["hidden"]["micro_location"]["damage"] > 0


# ─── Save/Load Integrity (TZ_for_GigaCode.md — пункт 2) ─────────

from burt.combat import start_combat, CombatState
from burt.state import create_initial_state
from burt.state_io import save_state, load_state


def _full_state(mode="exploring", combat_dict=None):
    """Создать полное state, проходящее validate_state."""
    st = create_initial_state(
        life=1,
        session_uuid="test",
        config_hash="v0.7.0",
        session_started="2026-01-01T00:00:00",
    )
    st["hidden"]["current_mode"] = mode
    if combat_dict is not None:
        st["hidden"]["combat"] = combat_dict
    return st


def _tmp_state_path():
    import tempfile
    import pathlib
    return pathlib.Path(tempfile.mkdtemp()) / "sl_test.json"


class TestSaveLoadIntegrity:
    """Проверка сохранения и загрузки критических полей.

    Баги из живого прогона:
    - После save+load Бурт в другой локации.
    - После загрузки боя срабатывает повторный триггер засады.
    - Волк наносит лишний удар (free_strike_done сбрасывается).
    """

    def test_current_node_id_preserved(self):
        """current_node_id должен сохраняться после save+load."""
        st = _full_state()
        st["hidden"]["current_node_id"] = "node_5"
        st["hidden"]["location_graph"]["node_5"] = {
            "type": "forest",
            "entered": True,
            "exits": {"north": None, "south": "start", "east": None, "west": None},
        }
        tmp = _tmp_state_path()
        try:
            save_state(tmp, st)
            loaded = load_state(tmp)
            assert loaded["hidden"]["current_node_id"] == "node_5"
        finally:
            if tmp.exists():
                tmp.unlink()
                tmp.parent.rmdir()

    def test_location_graph_preserved(self):
        """location_graph должен сохраняться полностью."""
        st = _full_state()
        custom_graph = {
            "start": {"type": "crossroads", "entered": True,
                       "exits": {"north": "node_1", "south": None, "east": None, "west": None}},
            "node_1": {"type": "forest", "entered": False,
                        "exits": {"north": None, "south": "start", "east": None, "west": None}},
        }
        st["hidden"]["location_graph"] = custom_graph
        st["hidden"]["current_node_id"] = "node_1"
        tmp = _tmp_state_path()
        try:
            save_state(tmp, st)
            loaded = load_state(tmp)
            assert loaded["hidden"]["location_graph"] == custom_graph
            assert loaded["hidden"]["current_node_id"] == "node_1"
        finally:
            if tmp.exists():
                tmp.unlink()
                tmp.parent.rmdir()

    def test_current_mode_combat_preserved(self):
        """current_mode='combat' должен сохраняться после save+load."""
        st = _full_state("combat")
        tmp = _tmp_state_path()
        try:
            save_state(tmp, st)
            loaded = load_state(tmp)
            assert loaded["hidden"]["current_mode"] == "combat"
        finally:
            if tmp.exists():
                tmp.unlink()
                tmp.parent.rmdir()

    def test_combat_state_preserved(self):
        """CombatState (включая free_strike_done) должен сохраняться."""
        cs = start_combat(["wolf"], "enemy")
        cs.free_strike_done = True
        st = _full_state("combat", combat_dict=cs.to_dict())
        tmp = _tmp_state_path()
        try:
            save_state(tmp, st)
            loaded = load_state(tmp)
            loaded_cs = CombatState.from_dict(loaded["hidden"]["combat"])
            assert loaded_cs.free_strike_done is True
        finally:
            if tmp.exists():
                tmp.unlink()
                tmp.parent.rmdir()

    def test_no_ambush_on_move_during_combat(self):
        """Движение во время боя НЕ должно перезапускать бой.

        Если current_mode == 'combat' и hidden['combat'] не None,
        _maybe_start_combat_on_enter должен вернуть None.
        """
        st = make_state("combat")
        cs = start_combat(["wolf"], "burt")
        cs.free_strike_done = True
        cs.round = 3
        st["hidden"]["combat"] = cs.to_dict()
        st["hidden"]["current_mode"] = "combat"
        st["hidden"]["current_node_id"] = "start"
        st["hidden"]["location_graph"]["start"]["type"] = "crossroads"
        st["hidden"]["location_graph"]["start"]["entered"] = True
        # Road node (north of start) — not an encounter location
        road_node = st["hidden"]["location_graph"]["start"]["exits"]["north"]
        if road_node and road_node in st["hidden"]["location_graph"]:
            st["hidden"]["location_graph"][road_node]["type"] = "road"

        result = execute_action(Action("go_north", "Go north"), st, rng=lambda: 4)

        # Бой НЕ должен перезапуститься
        assert st["hidden"]["current_mode"] == "combat", (
            f"current_mode should stay 'combat' after move; got {st['hidden']['current_mode']}"
        )
        assert st["hidden"]["combat"] is not None, (
            "combat state should not be None after move during combat"
        )
        loaded_cs = CombatState.from_dict(st["hidden"]["combat"])
        assert loaded_cs.free_strike_done is True, (
            "free_strike_done should remain True after move during combat"
        )

    def test_no_spawn_on_enter_during_combat_forest(self):
        """Вход в ОПАСНУЮ локацию (forest) во время боя не должен спавнить врагов.

        Это ключевой баг из ТЗ: после save+load, при движении Бурта в лес/болото/подземелье
        может сработать _maybe_start_combat_on_enter и перезапустить бой.

        RNG sequence:
          1. move_roll = 4 → success (not fail)
          2. encounter_roll = 1 → spawn (<=2) → BUG: should NOT spawn during combat
        """
        st = make_state("combat")
        cs = start_combat(["wolf"], "burt")
        cs.free_strike_done = True
        cs.round = 3
        st["hidden"]["combat"] = cs.to_dict()
        st["hidden"]["current_mode"] = "combat"
        st["hidden"]["current_node_id"] = "start"
        st["hidden"]["location_graph"]["start"]["type"] = "crossroads"
        st["hidden"]["location_graph"]["start"]["entered"] = True

        # Настроим граф: north -> forest (encounter location — spawn roll <= 2)
        north_node = "forest_bugfix"
        st["hidden"]["location_graph"]["start"]["exits"]["north"] = north_node
        st["hidden"]["location_graph"][north_node] = {
            "type": "forest",
            "entered": False,
            "exits": {"north": None, "south": "start", "east": None, "west": None},
        }

        # RNG: move_roll=4 (success), encounter_roll=1 (<=2 → spawn)
        call_count = [0]
        def rng():
            call_count[0] += 1
            if call_count[0] == 1:
                return 4  # move success
            return 1  # encounter spawn (triggers bug)

        result = execute_action(Action("go_north", "Go north"), st, rng=rng)

        # Бой НЕ должен перезапуститься даже при входе в dangerous location
        assert st["hidden"]["current_mode"] == "combat", (
            f"current_mode should stay 'combat' after entering forest during combat; "
            f"got {st['hidden']['current_mode']}"
        )
        assert st["hidden"]["combat"] is not None, (
            "combat state should NOT be None after entering forest during combat"
        )
        loaded_cs = CombatState.from_dict(st["hidden"]["combat"])
        assert loaded_cs.free_strike_done is True, (
            f"free_strike_done should remain True; got {loaded_cs.free_strike_done}"
        )
        assert loaded_cs.round == 3, (
            f"combat round should be preserved at 3; got {loaded_cs.round}"
        )

    def test_free_strike_done_not_reset_on_load(self):
        """После save+load free_strike_done должен остаться True."""
        cs = start_combat(["wolf"], "enemy")
        cs.free_strike_done = True
        cs.round = 2
        st = _full_state("combat", combat_dict=cs.to_dict())

        tmp = _tmp_state_path()
        try:
            save_state(tmp, st)
            loaded = load_state(tmp)
            loaded_cs = CombatState.from_dict(loaded["hidden"]["combat"])
            assert loaded_cs.free_strike_done is True
            assert loaded_cs.round == 2
        finally:
            if tmp.exists():
                tmp.unlink()
                tmp.parent.rmdir()

    def test_no_free_strike_on_load_with_active_combat(self):
        """После загрузки состояния с active combat волк НЕ должен бить бесплатно.

        Это проверяет что free_strike_done=True сохраняется и
        resolve_round не запускает ambush-секцию.
        """
        from burt import combat

        st = make_state("combat")
        cs = start_combat(["wolf"], "enemy")
        cs.free_strike_done = True
        cs.round = 5
        st["hidden"]["combat"] = cs.to_dict()

        # Симулируем round: Burt attacks
        burt_stats = combat.BurtStats(hp=8, hp_max=10, mp=2, mp_max=3)
        enemy = cs.enemies[0]

        result = combat.resolve_round(
            cs, burt_stats, "attack", enemy.id,
            rng=lambda: 4,  # hit
        )

        # free_strike_done должен остаться True (не должен сброситься)
        assert cs.free_strike_done is True
        # Бой должен продолжаться (burt не умер)
        assert result.outcome == "ongoing"
        assert result.combat.free_strike_done is True


# ─── Movement failure: single event per fail (BUGFIX — Вариант А) ────


class TestMovementFailureSingleEvent:
    """
    One movement failure = strictly one event.
    
    fail → only micro_event (lightning/tree/stone/god_wrath).
    fail_bad → only bad_movement_event (trap/sprain/ambush), micro skipped.
    """

    def test_fail_rolls_only_micro_event(self):
        """При move_result == 'fail' урон наносится ОДИН раз (микро-событие).
        
        fail_bad не должен запускать trap/ambush.
        """
        st = make_state()
        st["visible"]["hp"] = 10
        
        # rng sequence:
        # 1. move_roll = 2 → fail
        # 2. event_roll = 3 → lightning (3d6) [roll 3→lightning, 6→tree]
        # 3-5. damage dice = 1, 1, 1 → минимальный урон от молнии = 3
        rolls = [2, 3, 1, 1, 1]
        def rng():
            return rolls.pop(0) if rolls else 1

        result = execute_action(Action("go_north", "Go"), st, rng=rng)
        
        # Урон только от молнии (3), не должно быть двойного
        assert st["visible"]["hp"] == 7
        assert not result.game_over
        all_events = " ".join(result.events)
        assert "lightning" in all_events.lower() or "micro" in all_events.lower()
        assert "trap" not in all_events.lower()
        assert "ambush" not in all_events.lower()

    def test_fail_bad_rolls_only_bad_event(self):
        """При move_result == 'fail_bad' урон ТОЛЬКО от bad_movement_event.
        
        Микро-событие (молния) НЕ должно срабатывать.
        """
        st = make_state()
        st["visible"]["hp"] = 10
        
        # rng sequence (micro event roll is SKIPPED for fail_bad):
        # 1. move_roll = 1 → fail_bad
        # 2. bad_roll = 1 → trap (extra_damage = rng())
        # 3. trap damage dice = 1 → extra_damage = 1
        rolls = [1, 1, 1]
        def rng():
            return rolls.pop(0) if rolls else 1

        result = execute_action(Action("go_north", "Go"), st, rng=rng)
        
        # Урон только от ловушки (1), HP = 9
        assert st["visible"]["hp"] == 9
        assert not result.game_over
        all_events = " ".join(result.events)
        assert "trap" in all_events.lower()
        assert "lightning" not in all_events.lower()

    def test_fail_bad_can_kill(self):
        """Если extra_damage от ловушки убивает → game_over=True."""
        st = make_state()
        st["visible"]["hp"] = 1
        st["hidden"]["hp_raw"] = 1
        
        # rng sequence (micro event roll is SKIPPED):
        # 1. move_roll = 1 → fail_bad
        # 2. bad_roll = 1 → trap
        # 3. trap damage = 6 (убивает)
        rolls = [1, 1, 6]
        def rng():
            return rolls.pop(0) if rolls else 6

        result = execute_action(Action("go_north", "Go"), st, rng=rng)
        
        assert st["visible"]["hp"] == 0
        assert result.game_over is True

    def test_fail_bad_can_start_combat(self):
        """Если starts_combat=True → бой начинается, mode=combat."""
        st = make_state()
        st["visible"]["hp"] = 10
        # Dangerous location: forest
        st["hidden"]["location_graph"]["start"]["type"] = "forest"
        
        # rng sequence (micro event roll is SKIPPED):
        # 1. move_roll = 1 → fail_bad
        # 2. bad_roll = 3 → ambush (starts_combat=True)
        rolls = [1, 3]
        def rng():
            return rolls.pop(0) if rolls else 3

        result = execute_action(Action("go_north", "Go"), st, rng=rng)
        
        # Бой должен начаться
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat"] is not None
        all_events = " ".join(result.events)
        assert "ambush" in all_events.lower()