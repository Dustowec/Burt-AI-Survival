"""Game logger — JSON per turn, day-based directory rotation.

Structure:
    LOGS/
        day_001/
            turn_000001.json
            turn_000002.json
            ...
        day_002/
            turn_000003.json
            ...

Each file contains a full snapshot of start/end state, LLM interaction,
action, result, and optional error info.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class GameLogger:
    """Thread-safe JSON logger for game turns."""

    def __init__(self, logs_dir: Optional[Path] = None) -> None:
        self._logs_dir = logs_dir or Path("LOGS")
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._turn_counter: int = 0
        self._current_day: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_turn(
        self,
        day: int,
        start_state: dict[str, Any],
        sensory_report: str,
        llm_prompt: str,
        llm_response: str,
        action_key: str,
        action_label: str,
        result_events: list[str],
        result_game_over: bool,
        result_new_hp: Optional[int] = None,
        result_search_result: Optional[str] = None,
        result_direction_moved: Optional[str] = None,
        end_state: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Path | None:
        """Write a single turn log file. Returns path or None on failure."""
        with self._lock:
            self._turn_counter += 1
            turn = self._turn_counter

            # Rotate day directory
            if day != self._current_day:
                self._current_day = day

            try:
                entry = self._build_entry(
                    turn=turn,
                    day=day,
                    start_state=start_state,
                    sensory_report=sensory_report,
                    llm_prompt=llm_prompt,
                    llm_response=llm_response,
                    action_key=action_key,
                    action_label=action_label,
                    result_events=result_events,
                    result_game_over=result_game_over,
                    result_new_hp=result_new_hp,
                    result_search_result=result_search_result,
                    result_direction_moved=result_direction_moved,
                    end_state=end_state,
                    error=error,
                )
                return self._save(entry)
            except Exception:
                return None

    def log_special_event(
        self,
        day: int,
        event_type: str,
        description: str,
        state: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Path | None:
        """Log a special event (death, diary, epitaph, etc.)."""
        with self._lock:
            self._turn_counter += 1
            turn = self._turn_counter

            if day != self._current_day:
                self._current_day = day

            try:
                entry = {
                    "turn": turn,
                    "day": day,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "special_event",
                    "event_type": event_type,
                    "description": description,
                    "state": state,
                    "error": error,
                }
                return self._save(entry)
            except Exception:
                return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_entry(
        self,
        turn: int,
        day: int,
        start_state: dict[str, Any],
        sensory_report: str,
        llm_prompt: str,
        llm_response: str,
        action_key: str,
        action_label: str,
        result_events: list[str],
        result_game_over: bool,
        result_new_hp: Optional[int],
        result_search_result: Optional[str],
        result_direction_moved: Optional[str],
        end_state: Optional[dict[str, Any]],
        error: Optional[str],
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "turn": turn,
            "day": day,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "start_state": start_state,
            "sensory_report": sensory_report,
            "llm_prompt": llm_prompt,
            "llm_response": llm_response,
            "action": {
                "key": action_key,
                "label": action_label,
            },
            "result": {
                "events": result_events,
                "game_over": result_game_over,
            },
        }

        if result_new_hp is not None:
            entry["result"]["new_hp"] = result_new_hp
        if result_search_result is not None:
            entry["result"]["search_result"] = result_search_result
        if result_direction_moved is not None:
            entry["result"]["direction_moved"] = result_direction_moved
        if end_state is not None:
            entry["end_state"] = end_state
        if error is not None:
            entry["error"] = error

        return entry

    def _ensure_day_dir(self, day: int) -> Path:
        """Create day_NNN directory if it doesn't exist."""
        day_dir = self._logs_dir / f"day_{day:03d}"
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir

    def _save(self, entry: dict[str, Any]) -> Path:
        """Write entry to JSON file."""
        day = entry["day"]
        turn = entry["turn"]

        day_dir = self._ensure_day_dir(day)
        file_path = day_dir / f"turn_{turn:06d}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

        return file_path
