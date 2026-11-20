"""Gameplay log — §2, §39 spec v0.7.0.

game_session.jsonl: raw gameplay log, append-only, one line per turn,
written synchronously. Burt never sees it (§2). It lives next to
state.json, so it survives between plugin runs.

This sink is deliberately dumb and synchronous: the spec guarantees
"not lost", therefore no queue, no async, no buffering. Line is written
and flushed on every call.

Record of a normal turn:

    {"ts", "session_uuid", "turn_uuid", "floor", "day", "step", "mode",
     "location", "prompt", "response", "action_key", "action_label",
     "events": [...], "hp", "hp_max", "game_over": false}

Special events (death, resurrection, diary, epitaph) go through
append_special() and carry "event" + "description" instead.

Pure I/O: no game logic, no LLM, no asyncio.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from burt.trace import Trace

logger = logging.getLogger(__name__)


def _now(clock: Callable[[], datetime] | None = None) -> datetime:
    return clock() if clock is not None else datetime.now()


def _iso(moment: datetime) -> str:
    """ISO timestamp with milliseconds, e.g. 2026-10-11T21:40:00.123."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


class GameSessionLog:
    """Append-only gameplay log (§2, §39)."""

    def __init__(
        self,
        path: Path | str,
        trace: Trace | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        fsync: bool = False,
    ) -> None:
        self._path = Path(path)
        self._trace = trace or Trace()
        self._clock = clock
        self._fsync = fsync
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def trace(self) -> Trace:
        return self._trace

    # -- public API ------------------------------------------------

    def append_turn(
        self,
        *,
        day: int,
        step: int,
        mode: str,
        location: str,
        prompt: str,
        response: str,
        action_key: str,
        action_label: str,
        events: list[str],
        hp: int,
        hp_max: int,
        game_over: bool = False,
    ) -> None:
        """Write one gameplay turn. One line, synchronous."""
        turn = self._trace.current_turn
        record = {
            "ts": _iso(_now(self._clock)),
            "session_uuid": self._trace.session_uuid,
            "turn_uuid": turn.turn_uuid if turn is not None else None,
            "floor": turn.floor if turn is not None else 0,
            "day": day,
            "step": step,
            "mode": mode,
            "location": location,
            "prompt": prompt,
            "response": response,
            "action_key": action_key,
            "action_label": action_label,
            "events": list(events),
            "hp": hp,
            "hp_max": hp_max,
            "game_over": bool(game_over),
        }
        self._write(record)

    def append_special(
        self,
        *,
        day: int,
        event: str,
        description: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Write a non-turn event (death, resurrection, diary, epitaph)."""
        turn = self._trace.current_turn
        record: dict[str, Any] = {
            "ts": _iso(_now(self._clock)),
            "session_uuid": self._trace.session_uuid,
            "turn_uuid": turn.turn_uuid if turn is not None else None,
            "floor": turn.floor if turn is not None else 0,
            "day": day,
            "event": event,
            "description": description,
        }
        if data is not None:
            record["data"] = data
        self._write(record)

    def close(self) -> None:
        """Mark the log closed. Idempotent: nothing is buffered."""
        self._closed = True

    # -- internal --------------------------------------------------

    def _write(self, record: dict[str, Any]) -> None:
        if self._closed:
            return
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.write("\n")
                f.flush()
                if self._fsync:
                    import os
                    os.fsync(f.fileno())
        except OSError:
            # Gameplay logging must never break the game loop.
            logger.warning("game_session write failed", exc_info=True)
