"""Integration tests: logging inside run_turn — spec §38, §39.

Checks that one turn produces the full tracing chain
(session -> turn -> call), the three layers, alert transitions,
gameplay log lines, and that dry_run writes nothing.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import main
from burt.game_session import GameSessionLog
from burt.plugin_log import LEVEL_INFO, LEVEL_WARN, PluginLogger
from burt.trace import Trace

FIXED = datetime(2026, 10, 11, 21, 40, 0, 123000)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _fresh_state() -> dict:
    st = main.make_new_state(life=1)
    main._sync_hidden_from_meta(st)
    main._ensure_runtime_fields(st)
    return st


class Rig:
    """Plugin + gameplay log + trace wired into a temp directory."""

    def __init__(self, tmp_path: Path, **kwargs) -> None:
        self.trace = Trace(session_uuid="it-session")
        self.plugin = PluginLogger(
            log_dir=tmp_path / "logs",
            crash_dir=tmp_path / "crashes",
            trace=self.trace,
            level=0,
            clock=lambda: FIXED,
            **kwargs,
        )
        self.plugin.start()
        self.session = GameSessionLog(
            tmp_path / "game_session.jsonl", trace=self.trace, clock=lambda: FIXED,
        )
        self.tmp_path = tmp_path

    def plugin_records(self) -> list[dict]:
        self._drain_queue()
        files = sorted((self.tmp_path / "logs").glob("plugin_*.jsonl"))
        out: list[dict] = []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def session_records(self) -> list[dict]:
        path = self.tmp_path / "game_session.jsonl"
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _drain_queue(self) -> None:
        """Drain whatever the logger queued, whether or not a loop is running."""
        self.plugin.flush_sync()

    def events(self) -> list[str]:
        return [r["event"] for r in self.plugin_records()]

    def flush(self) -> None:
        """Drain the async queue so the file matches what was emitted."""
        self.plugin._flush_sync()


async def _fake_llm(answer="I walk north.\nCHOICE: 0"):
    async def call(system_msg, user_msg, history=None):
        return answer, []
    return call


# ---------------------------------------------------------------------
# Turn chain (§38)
# ---------------------------------------------------------------------

class TestTurnChain:
    @pytest.mark.asyncio
    async def test_turn_opens_floor(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        assert rig.trace.current_turn is not None
        assert rig.trace.current_turn.floor == 1
        assert "turn_start" in rig.events()

    @pytest.mark.asyncio
    async def test_three_layers_present(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        layers = {r["layer"] for r in rig.plugin_records() if r["layer"]}
        if not layers:
            raise AssertionError(
                f"collected={rig.plugin.counters} ring={len(rig.plugin.ring)} "
                f"queue={rig.plugin._queue} started={rig.plugin._started} "
                f"closed={rig.plugin._closed}"
            )
        assert layers == {"react", "tool", "interaction"}

    @pytest.mark.asyncio
    async def test_one_turn_uuid_many_call_uuids(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        records = [r for r in rig.plugin_records() if r["turn_uuid"]]
        turn_ids = {r["turn_uuid"] for r in records}
        call_ids = {r["call_uuid"] for r in records if r["call_uuid"]}
        assert len(turn_ids) == 1
        assert len(call_ids) >= 2  # llm call + tool call

    @pytest.mark.asyncio
    async def test_floor_increments_between_turns(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            for _ in range(2):
                await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                    plugin=rig.plugin, trace=rig.trace,
                                    game_session=rig.session)
        assert rig.trace.current_turn.floor == 2


# ---------------------------------------------------------------------
# React payload policy (§38)
# ---------------------------------------------------------------------

class TestReactPayload:
    @pytest.mark.asyncio
    async def test_preview_when_debug_off(self, tmp_path):
        rig = Rig(tmp_path, debug=False)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        rig.flush()
        request = next(r for r in rig.plugin_records() if r["event"] == "llm_request")
        assert "prompt" not in request["data"]
        assert request["data"]["prompt_chars"] > 0
        assert len(request["data"]["prompt_preview"]) == 80
        assert len(request["data"]["prompt_hash"]) == 64

    @pytest.mark.asyncio
    async def test_full_prompt_when_debug_on(self, tmp_path):
        rig = Rig(tmp_path, debug=True)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        rig.flush()
        request = next(r for r in rig.plugin_records() if r["event"] == "llm_request")
        assert "[STATE]" in request["data"]["prompt"]


# ---------------------------------------------------------------------
# Parse warning (§39)
# ---------------------------------------------------------------------

class TestParse:
    @pytest.mark.asyncio
    async def test_parse_ok_on_choice(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm("I walk.\nCHOICE: 0")
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        rig.flush()
        record = next(r for r in rig.plugin_records() if r["event"] == "parse_ok")
        assert record["level"] == LEVEL_INFO

    @pytest.mark.asyncio
    async def test_parse_warn_without_choice(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm("I walk north without a choice line.")
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        rig.flush()
        record = next(r for r in rig.plugin_records() if r["event"] == "parse_warn")
        assert record["level"] == LEVEL_WARN
        assert record["data"]["fallback_used"] is True


# ---------------------------------------------------------------------
# State alerts (§39)
# ---------------------------------------------------------------------

class TestStateAlerts:
    @pytest.mark.asyncio
    async def test_waiting_llm_alert(self, tmp_path):
        # §39: running -> waiting_llm is a DEBUG-level alert.
        rig = Rig(tmp_path, debug=True)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        transitions = [
            (r["data"].get("from"), r["data"].get("to"))
            for r in rig.plugin_records() if r["event"] == "state_change"
        ]
        assert ("running", "waiting_llm") in transitions
        assert ("waiting_llm", "running") in transitions


# ---------------------------------------------------------------------
# Errors (§39)
# ---------------------------------------------------------------------

class TestErrors:
    @pytest.mark.asyncio
    async def test_llm_exception_writes_crash(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()

        async def boom(system_msg, user_msg, history=None):
            raise RuntimeError("llm down")

        with patch.object(main.llm_client, "call_llm", side_effect=boom):
            with pytest.raises(RuntimeError):
                await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                    plugin=rig.plugin, trace=rig.trace,
                                    game_session=rig.session)

        assert "llm_error" in rig.events()
        crashes = list((tmp_path / "crashes").glob("crash_*.log"))
        assert len(crashes) == 1
        assert "llm down" in crashes[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# Gameplay log and dry run (§2)
# ---------------------------------------------------------------------

class TestGameplayLog:
    @pytest.mark.asyncio
    async def test_turn_appended_to_session(self, tmp_path):
        rig = Rig(tmp_path)
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            await main.run_turn(st, [], rng=lambda: 4, dry_run=False,
                                plugin=rig.plugin, trace=rig.trace,
                                game_session=rig.session)
        records = rig.session_records()
        assert len(records) == 1
        assert records[0]["action_key"]
        assert records[0]["session_uuid"] == "it-session"

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, tmp_path, capsys):
        rig = Rig(tmp_path)
        st = _fresh_state()
        await main.run_turn(st, [], rng=lambda: 4, dry_run=True,
                            plugin=rig.plugin, trace=rig.trace,
                            game_session=rig.session)
        capsys.readouterr()
        assert rig.session_records() == []
        assert rig.trace.current_turn is None


# ---------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------

class TestBackwards:
    @pytest.mark.asyncio
    async def test_run_turn_without_logging(self):
        st = _fresh_state()
        fake = await _fake_llm()
        with patch.object(main.llm_client, "call_llm", side_effect=fake):
            result = await main.run_turn(st, [], rng=lambda: 4, dry_run=False)
        assert result.game_over is False

    def test_game_loop_accepts_plugin_kwargs(self):
        import inspect
        params = inspect.signature(main.game_loop).parameters
        for name in ("plugin", "trace", "game_session"):
            assert name in params


