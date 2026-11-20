"""
test_npc_integration.py — RED integration tests for burt.npc wiring.

Purpose: verify that burt.npc.DialogueEngine is connected to the existing
runtime blocks (state.py, loop.py, main.py). All tests are RED until the
integration below exists.

Contract to implement
--------------------
state.py:
    - create_initial_state(...) sets hidden["dialog_state"] = None
    - validate_state() accepts dialog_state=None with mode="exploring"
    - validate_state() accepts dialog_state=dict with mode="dialog"
    - validate_state() raises ValueError if mode="dialog" but
      dialog_state is None (broken state)
    - dialog_state survives save/load via state_io
    dialog_state shape:
      {"role_key": str, "is_angry": bool, "turn": int,
       "anger_lock_until": int|None, "bonus_used": bool, "quest_state": str}
    HP / coins live in visible["hp"] / visible["wallet"]["coin"] — dialog
    syncs them at begin/end of each action, not in dialog_state.

loop.py:
    - build_menu(visible, state, *, dialogue_engine=None) builds dialog menu
      from engine.available_categories(role_key), keys:
        dialog_<category> for each available category
        dialog_exit
    - exploring menu offers "talk_to_<role>" when hidden["npcs_here"]
      contains that role (format: list[str] of role keys)
    - execute_action(action, state, rng=None, *, dialogue_engine=None) routes:
        "talk_to_<role>" → enter dialog mode
        "dialog_exit"    → leave dialog mode
        "dialog_<cat>"   → resolve one dialogue turn
    - execute_dialog(action, state, engine, rng) -> ActionResult handles
      one dialogue turn: rebuilds Session from dialog_state + visible,
      calls Session.say(...), applies Result back to state.

main.py:
    - run_turn(..., *, dialogue_engine=None) accepts engine kwarg
    - game_loop(..., *, dialogue_engine=None) accepts and forwards it
    - main() loads replicas.json, creates DialogueEngine, passes it down
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from burt.state import create_initial_state, validate_state
from burt import state_io
from burt.loop import Action, build_menu, parse_choice, execute_action
from burt.npc import DialogueEngine, load_replicas, Outcome

# Soft imports: a missing symbol must not prevent the other tests from running.
try:
    from burt.loop import execute_dialog
    _HAS_EXECUTE_DIALOG = True
except ImportError:  # pragma: no cover
    execute_dialog = None  # type: ignore[assignment]
    _HAS_EXECUTE_DIALOG = False

try:
    import main as main_mod  # main.py lives next to the burt/ package
    _HAS_MAIN = True
except ImportError:  # pragma: no cover
    main_mod = None  # type: ignore[assignment]
    _HAS_MAIN = False


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_REPLICAS_CANDIDATES = [
    _THIS_DIR / "replicas.json",
    _THIS_DIR.parent / "replicas.json",
    Path.cwd() / "replicas.json",
]


def _find_replicas_path() -> Path:
    for p in _REPLICAS_CANDIDATES:
        if p.exists():
            return p
    pytest.skip(
        "replicas.json not found next to tests; "
        f"looked in: {[str(p) for p in _REPLICAS_CANDIDATES]}"
    )


@pytest.fixture(scope="module")
def replicas_path() -> Path:
    return _find_replicas_path()


@pytest.fixture(scope="module")
def engine(replicas_path) -> DialogueEngine:
    return DialogueEngine(load_replicas(str(replicas_path)))


class _SeqRng:
    """Deterministic rng: yields the given values, then a default."""

    def __init__(self, values, default: int = 4):
        self.values = list(values)
        self.default = default

    def __call__(self) -> int:
        return self.values.pop(0) if self.values else self.default


def _base_state() -> dict:
    return create_initial_state(
        life=1,
        session_uuid="00000000-0000-0000-0000-000000000000",
        config_hash="test",
        session_started="2024-01-01T00:00:00+00:00",
    )


def _make_state_in_dialog(
    role_key: str = "elder",
    *,
    hp: int = 10,
    coins: int = 100,
    is_angry: bool = False,
    turn: int = 0,
    anger_lock_until: int | None = None,
    bonus_used: bool = False,
    quest_state: str = "available",
) -> dict:
    state = _base_state()
    state["hidden"]["current_mode"] = "dialog"
    state["hidden"]["dialog_state"] = {
        "role_key": role_key,
        "is_angry": is_angry,
        "turn": turn,
        "anger_lock_until": anger_lock_until,
        "bonus_used": bonus_used,
        "quest_state": quest_state,
    }
    state["visible"]["hp"] = hp
    state["hidden"]["hp_raw"] = hp
    state["visible"]["wallet"]["coin"] = coins
    return state


def _make_state_with_npcs(role_key: str = "elder") -> dict:
    state = _base_state()
    state["hidden"]["npcs_here"] = [role_key]
    return state


def _is_error(result) -> bool:
    return any(str(e).lower().startswith("error") for e in result.events)


# ===========================================================================
# 1. STATE INTEGRATION
# ===========================================================================
class TestStateIntegration:
    def test_initial_state_has_dialog_state_none(self):
        """create_initial_state must seed hidden["dialog_state"]."""
        state = _base_state()
        assert "dialog_state" in state["hidden"], (
            "hidden['dialog_state'] must exist in initial state (None)"
        )
        assert state["hidden"]["dialog_state"] is None

    def test_validate_state_accepts_exploring_without_dialog_state(self):
        """exploring + dialog_state=None is a valid state."""
        state = _base_state()
        assert state["hidden"]["current_mode"] == "exploring"
        assert state["hidden"].get("dialog_state") is None
        validate_state(state)  # must not raise

    def test_validate_state_accepts_active_dialog(self):
        """dialog mode + well-formed dialog_state is valid."""
        state = _make_state_in_dialog("elder")
        validate_state(state)  # must not raise

    def test_validate_state_rejects_dialog_mode_without_state(self):
        """dialog mode but dialog_state is None is inconsistent."""
        state = _base_state()
        state["hidden"]["current_mode"] = "dialog"
        # dialog_state intentionally left as None
        with pytest.raises(ValueError):
            validate_state(state)

    def test_dialog_state_survives_save_load(self, tmp_path):
        """dialog_state must round-trip through state_io."""
        path = tmp_path / "state.json"
        state = _make_state_in_dialog("guard", is_angry=True,
                                      anger_lock_until=3, bonus_used=True)
        state_io.save_state(path, state)
        loaded = state_io.load_state(path)
        ds = loaded["hidden"]["dialog_state"]
        assert ds["role_key"] == "guard"
        assert ds["is_angry"] is True
        assert ds["anger_lock_until"] == 3
        assert ds["bonus_used"] is True


# ===========================================================================
# 2. LOOP — MENU IN EXPLORING WITH NPCS
# ===========================================================================
class TestLoopExploringMenu:
    def test_talk_to_action_offered(self, engine):
        state = _make_state_with_npcs("elder")
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        keys = {a.key for a in menu}
        assert "talk_to_elder" in keys, (
            f"expected talk_to_elder in exploring menu, got {keys}"
        )

    def test_no_talk_when_no_npcs(self, engine):
        state = _base_state()
        state["hidden"]["npcs_here"] = []
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        assert not any(a.key.startswith("talk_to_") for a in menu)

    def test_menu_works_without_engine_kwarg(self):
        """Backward compatibility: dialogue_engine is optional."""
        state = _base_state()
        menu = build_menu(state["visible"], state)  # must not raise
        assert menu  # baseline menu still built


# ===========================================================================
# 3. LOOP — MENU IN DIALOG MODE
# ===========================================================================
class TestLoopDialogMenu:
    def test_dialog_menu_contains_available_categories(self, engine):
        state = _make_state_in_dialog("elder")
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        keys = {a.key for a in menu}
        # elder exposes: truth, polite, lie, threat, charm, trade, quest
        expected = {
            "dialog_truth", "dialog_polite", "dialog_lie",
            "dialog_threat", "dialog_charm", "dialog_trade",
            "dialog_quest", "dialog_exit",
        }
        assert expected <= keys, f"missing: {expected - keys}"

    def test_dialog_menu_child_has_no_lie_or_threat(self, engine):
        state = _make_state_in_dialog("child")
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        keys = {a.key for a in menu}
        assert "dialog_lie" not in keys
        assert "dialog_threat" not in keys
        assert "dialog_charm" in keys

    def test_dialog_menu_guard_has_bribe_no_trade(self, engine):
        state = _make_state_in_dialog("guard")
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        keys = {a.key for a in menu}
        assert "dialog_bribe" in keys
        assert "dialog_trade" not in keys
        assert "dialog_threat" in keys

    def test_dialog_menu_hides_exit_when_angry(self, engine):
        state = _make_state_in_dialog("elder", is_angry=True,
                                      anger_lock_until=2)
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        keys = {a.key for a in menu}
        assert "dialog_exit" not in keys, (
            "exit must be hidden while angry (can_exit() == False)"
        )

    def test_parse_choice_selects_dialog_action(self, engine):
        state = _make_state_in_dialog("elder")
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        idx = next(i for i, a in enumerate(menu) if a.key == "dialog_truth")
        action = parse_choice(f"CHOICE: {idx}", menu)
        assert action.key == "dialog_truth"


# ===========================================================================
# 4. LOOP — EXECUTE DIALOG
# ===========================================================================
class TestExecuteDialog:
    def test_execute_dialog_function_exists(self):
        assert _HAS_EXECUTE_DIALOG, (
            "burt.loop.execute_dialog is missing — required for dialog mode"
        )

    def test_execute_action_accepts_dialogue_engine_kwarg(self):
        sig = inspect.signature(execute_action)
        assert "dialogue_engine" in sig.parameters, (
            "execute_action must accept keyword 'dialogue_engine'"
        )

    def test_enter_dialog_via_talk_to(self, engine):
        state = _make_state_with_npcs("elder")
        action = Action(key="talk_to_elder", label="Talk to elder")
        execute_action(action, state, rng=lambda: 5,
                       dialogue_engine=engine)
        assert state["hidden"]["current_mode"] == "dialog"
        ds = state["hidden"]["dialog_state"]
        assert ds is not None
        assert ds["role_key"] == "elder"

    def test_dialog_exit_returns_to_exploring(self, engine):
        state = _make_state_in_dialog("elder")
        action = Action(key="dialog_exit", label="Leave conversation")
        result = execute_action(action, state, rng=lambda: 5,
                                dialogue_engine=engine)
        assert state["hidden"]["current_mode"] == "exploring"
        assert state["hidden"]["dialog_state"] is None
        assert not _is_error(result)

    def test_dialog_exit_blocked_while_angry(self, engine):
        state = _make_state_in_dialog("elder", is_angry=True,
                                      anger_lock_until=2)
        action = Action(key="dialog_exit", label="Leave conversation")
        result = execute_action(action, state, rng=lambda: 5,
                                dialogue_engine=engine)
        assert state["hidden"]["current_mode"] == "dialog", (
            "exit must be refused while angry (lock still active)"
        )
        assert _is_error(result)

    def test_dialog_exit_reopens_after_lock(self, engine):
        state = _make_state_in_dialog("elder", turn=2, is_angry=True,
                                      anger_lock_until=2)
        action = Action(key="dialog_exit", label="Leave conversation")
        result = execute_action(action, state, rng=lambda: 5,
                                dialogue_engine=engine)
        assert state["hidden"]["current_mode"] == "exploring"
        assert state["hidden"]["dialog_state"] is None

    def test_dialog_truth_success_text_from_success_pool(
        self, engine, replicas_path,
    ):
        replicas = json.loads(replicas_path.read_text(encoding="utf-8"))
        success_pool = set(replicas["roles"]["elder"]["success"])
        state = _make_state_in_dialog("elder")
        rng = _SeqRng([5, 4])  # success, no bonus
        action = Action(key="dialog_truth", label="Ask directly")
        result = execute_action(action, state, rng=rng,
                                dialogue_engine=engine)
        joined = "\n".join(result.events)
        assert any(text in joined for text in success_pool), (
            f"expected one of elder.success in events, got: {result.events!r}"
        )

    def test_dialog_truth_fail_angry_pool(self, engine, replicas_path):
        replicas = json.loads(replicas_path.read_text(encoding="utf-8"))
        angry_pool = set(replicas["roles"]["elder"]["fail_angry"])
        state = _make_state_in_dialog("elder")
        rng = _SeqRng([1, 2])  # fail + penalty
        action = Action(key="dialog_truth", label="Ask directly")
        result = execute_action(action, state, rng=rng,
                                dialogue_engine=engine)
        joined = "\n".join(result.events)
        assert any(text in joined for text in angry_pool), (
            f"expected one of elder.fail_angry in events, got: {result.events!r}"
        )

    def test_dialog_fail_penalty_reduces_visible_hp(self, engine):
        state = _make_state_in_dialog("elder")
        hp_before = state["visible"]["hp"]
        rng = _SeqRng([1, 2])  # fail + penalty
        execute_action(Action(key="dialog_truth", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        assert state["visible"]["hp"] == hp_before - 1
        assert state["hidden"]["hp_raw"] == hp_before - 1

    def test_dialog_fail_penalty_sets_anger_in_state(self, engine):
        state = _make_state_in_dialog("elder")
        rng = _SeqRng([1, 2])
        execute_action(Action(key="dialog_truth", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        ds = state["hidden"]["dialog_state"]
        assert ds["is_angry"] is True
        assert ds["anger_lock_until"] is not None

    def test_dialog_success_no_hp_change(self, engine):
        state = _make_state_in_dialog("elder")
        hp_before = state["visible"]["hp"]
        rng = _SeqRng([5, 4])
        execute_action(Action(key="dialog_truth", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        assert state["visible"]["hp"] == hp_before

    def test_dialog_bribe_spends_coins(self, engine):
        state = _make_state_in_dialog("guard", coins=100)
        rng = _SeqRng([5, 4])  # success, no bonus -> base cost 4
        execute_action(Action(key="dialog_bribe", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        assert state["visible"]["wallet"]["coin"] < 100

    def test_dialog_bribe_fail_keeps_coins(self, engine):
        state = _make_state_in_dialog("guard", coins=100)
        rng = _SeqRng([1, 5])  # fail, no penalty (second=5)
        execute_action(Action(key="dialog_bribe", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        assert state["visible"]["wallet"]["coin"] == 100

    def test_dialog_bonus_used_flag_persists(self, engine):
        state = _make_state_in_dialog("elder")
        rng = _SeqRng([5, 1])  # success + bonus -> consumes bonus_used
        execute_action(Action(key="dialog_truth", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        ds = state["hidden"]["dialog_state"]
        assert ds["bonus_used"] is True, (
            "bonus_used must be persisted in dialog_state"
        )

    def test_dialog_quest_respects_quest_state(self, engine):
        state = _make_state_in_dialog("elder", quest_state="in_progress")
        rng = _SeqRng([5, 4])
        execute_action(Action(key="dialog_quest", label="..."),
                       state, rng=rng, dialogue_engine=engine)
        # текст из quest_already — уже покрыт unit-тестами; здесь
        # важно, что исполнитель не падает и не выходит из диалога
        assert state["hidden"]["current_mode"] == "dialog"


# ===========================================================================
# 5. MAIN INTEGRATION
# ===========================================================================
class TestMainIntegration:
    @pytest.mark.skipif(not _HAS_MAIN, reason="main.py not importable")
    def test_run_turn_accepts_dialogue_engine_kwarg(self):
        sig = inspect.signature(main_mod.run_turn)
        assert "dialogue_engine" in sig.parameters, (
            "run_turn must accept keyword 'dialogue_engine'"
        )

    @pytest.mark.skipif(not _HAS_MAIN, reason="main.py not importable")
    def test_game_loop_accepts_dialogue_engine_kwarg(self):
        sig = inspect.signature(main_mod.game_loop)
        assert "dialogue_engine" in sig.parameters, (
            "game_loop must accept keyword 'dialogue_engine'"
        )

    @pytest.mark.skipif(not _HAS_MAIN, reason="main.py not importable")
    def test_main_exposes_dialogue_engine_builder(self):
        """main must expose a way to build/load the dialogue engine."""
        has_builder = any(
            hasattr(main_mod, name)
            for name in ("load_dialogue_engine", "_load_dialogue_engine",
                         "build_dialogue_engine", "_build_dialogue_engine")
        )
        # Alternatively the engine may be created inline in main(); in that
        # case the module must at least reference burt.npc.
        assert has_builder or hasattr(main_mod, "npc"), (
            "main.py must either expose a dialogue-engine builder "
            "or import burt.npc directly"
        )


# ===========================================================================
# 6. END-TO-END (loop only, no LLM)
# ===========================================================================
class TestEndToEnd:
    def test_full_dialog_cycle(self, engine):
        """enter → truth(success) → exit."""
        state = _make_state_with_npcs("elder")

        # 1. enter dialog
        enter = Action(key="talk_to_elder", label="Talk to elder")
        execute_action(enter, state, rng=lambda: 5,
                       dialogue_engine=engine)
        assert state["hidden"]["current_mode"] == "dialog"

        # 2. menu offers dialog actions
        menu = build_menu(state["visible"], state, dialogue_engine=engine)
        assert any(a.key == "dialog_truth" for a in menu)

        # 3. say truth
        rng = _SeqRng([5, 4])
        result = execute_action(
            Action(key="dialog_truth", label="..."),
            state, rng=rng, dialogue_engine=engine,
        )
        assert not _is_error(result)

        # 4. leave
        leave = Action(key="dialog_exit", label="Leave")
        result = execute_action(leave, state, rng=lambda: 5,
                                dialogue_engine=engine)
        assert state["hidden"]["current_mode"] == "exploring"
        assert state["hidden"]["dialog_state"] is None
        assert not _is_error(result)

    def test_full_dialog_cycle_with_anger(self, engine):
        """enter → fail(penalty) → exit blocked → unlock → exit."""
        state = _make_state_with_npcs("elder")
        execute_action(
            Action(key="talk_to_elder", label="Talk to elder"),
            state, rng=lambda: 5, dialogue_engine=engine,
        )

        # fail with penalty
        rng = _SeqRng([1, 2])
        execute_action(
            Action(key="dialog_truth", label="..."),
            state, rng=rng, dialogue_engine=engine,
        )
        assert state["hidden"]["dialog_state"]["is_angry"] is True
        assert state["hidden"]["current_mode"] == "dialog"

        # exit refused
        res = execute_action(
            Action(key="dialog_exit", label="Leave"),
            state, rng=lambda: 5, dialogue_engine=engine,
        )
        assert state["hidden"]["current_mode"] == "dialog"
        assert _is_error(res)

        # simulate two turns passing
        ds = state["hidden"]["dialog_state"]
        lock = ds["anger_lock_until"]
        assert lock is not None
        ds["turn"] = lock
        ds["is_angry"] = False
        ds["anger_lock_until"] = None

        # exit now works
        execute_action(
            Action(key="dialog_exit", label="Leave"),
            state, rng=lambda: 5, dialogue_engine=engine,
        )
        assert state["hidden"]["current_mode"] == "exploring"


# ===========================================================================
# 7. SANITY — replicas are loadable
# ===========================================================================
class TestReplicasLoadable:
    def test_load_replicas_returns_expected_sections(self, replicas_path):
        data = load_replicas(str(replicas_path))
        assert "roles" in data and "events" in data
        assert "elder" in data["roles"]

    def test_engine_available_categories_for_elder(self, engine):
        cats = engine.available_categories("elder")
        assert {"truth", "polite", "lie", "threat", "charm",
                "trade", "quest", "exit"} <= cats