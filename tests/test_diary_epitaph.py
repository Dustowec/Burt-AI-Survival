"""Tests for diary action, punishment injection, epitaph, context reset.

HANDOFF-12 #3. Design: diary is a menu action at step >= 19; if skipped,
diary cleared and next morning injects punishment; context resets on sleep;
epitaph written on death.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import main
from burt.loop import Action, ActionResult, build_menu, execute_action


def _state(day=1, step=0, mode="exploring", diary=None,
           written_today=False, skipped_today=False, injected_day=0):
    from burt import world
    return {
        "meta": {"life": 1, "day": day, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": f"{day} day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [],
            "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": mode,
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": step, "day": day,
            "diary": diary,
            "day_log": [],
            "diary_written_today": written_today,
            "diary_skipped_today": skipped_today,
            "injected_day": injected_day,
        },
    }


# ─── build_menu ────────────────────────────────────────────


class TestBuildMenuDiary:
    def test_write_diary_at_step_19(self):
        st = _state(step=19)
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "sleep" in keys
        assert "write_diary_and_go_sleep" in keys

    def test_no_write_diary_at_step_5(self):
        st = _state(step=5)
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "write_diary_and_go_sleep" not in keys

    def test_no_write_diary_at_critical_hp_before_19(self):
        st = _state(step=5)
        st["visible"]["hp"] = 1
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "sleep" in keys
        assert "write_diary_and_go_sleep" not in keys


# ─── execute_action sleep ──────────────────────────────────


class TestSleepClearsDiary:
    def test_sleep_clears_diary_if_not_written_today(self):
        st = _state(diary="old text", written_today=False)
        execute_action(Action("sleep", "Sleep"), st, rng=lambda: 4)
        assert st["hidden"]["diary"] is None
        assert st["hidden"]["diary_skipped_today"] is True

    def test_sleep_preserves_diary_if_written_today(self):
        st = _state(diary="fresh text", written_today=True)
        execute_action(Action("sleep", "Sleep"), st, rng=lambda: 4)
        assert st["hidden"]["diary"] == "fresh text"
        assert st["hidden"]["diary_skipped_today"] is False

    def test_sleep_clears_day_log(self):
        st = _state()
        st["hidden"]["day_log"] = [{"step": 0, "location": "x",
                                     "llm_message": "y", "action": "z"}]
        execute_action(Action("sleep", "Sleep"), st, rng=lambda: 4)
        assert st["hidden"]["day_log"] == []

    def test_write_diary_and_go_sleep_behaves_like_sleep(self):
        st = _state(step=19, diary="fresh", written_today=True)
        result = execute_action(
            Action("write_diary_and_go_sleep", "Diary+sleep"), st,
            rng=lambda: 4,
        )
        assert st["hidden"]["day"] == 2
        assert st["hidden"]["step"] == 0
        assert st["hidden"]["diary"] == "fresh"


# ─── _format_day_log ───────────────────────────────────────


class TestFormatDayLog:
    def test_empty(self):
        assert main._format_day_log([]) == "(no events)"

    def test_single_entry(self):
        log = [{"step": 3, "location": "Forest",
                "llm_message": "I walked.", "action": "go_north"}]
        text = main._format_day_log(log)
        assert "Step 3" in text
        assert "Forest" in text
        assert "I walked." in text
        assert "go_north" in text


# ─── _write_diary ──────────────────────────────────────────


class TestWriteDiary:
    def test_stores_diary_and_sets_flag(self):
        st = _state(day=3)
        log = [{"step": 1, "location": "Forest",
                "llm_message": "walked", "action": "go_north"}]
        with patch(
            "burt.llm_client.call_llm",
            new=AsyncMock(return_value=("Day three.", [])),
        ):
            asyncio.run(main._write_diary(st, log))
        assert st["hidden"]["diary"] == "Day three."
        assert st["hidden"]["diary_written_today"] is True

    def test_passes_previous_diary_in_user_msg(self):
        st = _state(day=3, diary="yesterday text")
        mock = AsyncMock(return_value=("new", []))
        with patch("burt.llm_client.call_llm", new=mock):
            asyncio.run(main._write_diary(st, []))
        user_msg = mock.call_args[0][1]
        assert "yesterday text" in user_msg

    def test_passes_day_log_in_user_msg(self):
        st = _state(day=3)
        log = [{"step": 2, "location": "Swamp",
                "llm_message": "I searched.", "action": "search"}]
        mock = AsyncMock(return_value=("new", []))
        with patch("burt.llm_client.call_llm", new=mock):
            asyncio.run(main._write_diary(st, log))
        user_msg = mock.call_args[0][1]
        assert "Swamp" in user_msg
        assert "search" in user_msg


# ─── _write_epitaph ────────────────────────────────────────


class TestWriteEpitaph:
    def test_stores_epitaph(self):
        st = _state(day=5, diary="lived well")
        with patch(
            "burt.llm_client.call_llm",
            new=AsyncMock(return_value=("I lived.", [])),
        ):
            asyncio.run(main._write_epitaph(st, "combat"))
        assert st["meta"]["memory"] == "I lived."
        assert st["meta"]["memory_cause"] == "combat"

    def test_includes_diary_in_user_msg(self):
        st = _state(day=5, diary="last words here")
        mock = AsyncMock(return_value=("epitaph", []))
        with patch("burt.llm_client.call_llm", new=mock):
            asyncio.run(main._write_epitaph(st, "combat"))
        user_msg = mock.call_args[0][1]
        assert "last words here" in user_msg


# ─── run_turn integration ──────────────────────────────────


class TestRunTurnInjection:
    def test_diary_injected_at_start_of_new_day(self):
        st = _state(day=2, injected_day=1, diary="yesterday I walked.")
        mock = AsyncMock(return_value=("CHOICE: 0", []))
        with patch.object(main.llm_client, "call_llm", new=mock), \
                patch.object(main.loop, "execute_action",
                             return_value=ActionResult(events=[], game_over=False)):
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))
        user_msg = mock.call_args[0][1]
        assert "yesterday I walked" in user_msg

    def test_punishment_injected_when_skipped(self):
        st = _state(day=2, injected_day=1, skipped_today=True)
        mock = AsyncMock(return_value=("CHOICE: 0", []))
        with patch.object(main.llm_client, "call_llm", new=mock), \
                patch.object(main.loop, "execute_action",
                             return_value=ActionResult(events=[], game_over=False)):
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))
        user_msg = mock.call_args[0][1]
        assert "punished by the gods of oblivion" in user_msg
        assert st["hidden"]["diary_skipped_today"] is False


class TestRunTurnDayLog:
    def test_day_log_appended(self):
        st = _state(day=1, step=0)
        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action",
            return_value=ActionResult(events=[], game_over=False),
        ):
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))
        assert len(st["hidden"]["day_log"]) == 1
        entry = st["hidden"]["day_log"][0]
        assert entry["step"] == 0
        assert entry["location"] == "Crossroads"
        assert "action" in entry


class TestRunTurnHistoryReset:
    def test_history_reset_on_sleep(self):
        st = _state(day=1, step=19)
        fake = ActionResult(events=["You sleep."], game_over=False)

        def fake_execute(action, state, rng=None):
            state["hidden"]["day"] = state["hidden"].get("day", 1) + 1
            state["hidden"]["step"] = 0
            return fake

        history = [{"role": "user", "content": "old"},
                   {"role": "assistant", "content": "old"}]
        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action", side_effect=fake_execute,
        ):
            _, new_history = asyncio.run(
                main.run_turn(st, history, rng=lambda: 4, dry_run=False)
            )
        assert new_history == []


class TestRunTurnEpitaph:
    def test_epitaph_on_game_over(self):
        st = _state(day=3)
        fake = ActionResult(events=["You died."], game_over=True)
        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action", return_value=fake,
        ), patch.object(
            main, "_write_epitaph", new=AsyncMock(),
        ) as mock_ep:
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))
        assert mock_ep.called

    def test_epitaph_on_final_hunger_death(self):
        st = _state(day=3, step=18)
        st["visible"]["eat"] = False
        fake = ActionResult(events=["ok"], game_over=False)
        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action", return_value=fake,
        ), patch.object(
            main, "_check_hunger_death", return_value="final_death",
        ), patch.object(
            main, "_write_epitaph", new=AsyncMock(),
        ) as mock_ep:
            asyncio.run(main.run_turn(st, [], rng=lambda: 1, dry_run=False))
        assert mock_ep.called

    def test_no_epitaph_on_resurrection(self):
        st = _state(day=3, step=18)
        fake = ActionResult(events=["ok"], game_over=False)
        with patch.object(
            main.llm_client, "call_llm",
            new=AsyncMock(return_value=("CHOICE: 0", [])),
        ), patch.object(
            main.loop, "execute_action", return_value=fake,
        ), patch.object(
            main, "_check_hunger_death", return_value="resurrected",
        ), patch.object(
            main, "_write_epitaph", new=AsyncMock(),
        ) as mock_ep:
            asyncio.run(main.run_turn(st, [], rng=lambda: 4, dry_run=False))
        assert not mock_ep.called
