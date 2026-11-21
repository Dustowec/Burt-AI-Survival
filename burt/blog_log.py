"""Blog log — a human-readable markdown chronicle of one run.

Not a copy of the console: only what a reader wants to see.

Per turn:
    status at the start, the world event (micro-event / ambush / trap),
    Burt's own words, the choice, status at the end.

Plus: combat blocks (ambush or not, status before/after), diary entries
and epitaphs of every life.

The file is markdown on purpose: headings, block quotes and bold read
well both in a terminal and in a blog editor.

Pure I/O: no game logic, no LLM, no asyncio. Every block is flushed, so
Ctrl+C never eats the tail of a long run.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from burt.trace import Trace

logger = logging.getLogger(__name__)

# Tool actions are folded into one line: the reader does not care which
# menu item was pressed, only that Burt stopped to look at his things.
FOLDED_TOOLS = frozenset({
    "scroll", "inventory", "status", "remember", "diary",
})

_ACTION_WORDS = {
    "osmotret": "looked around",
    "search": "searched the place",
    "eat_food": "ate",
    "drink_water": "drank water",
    "sleep": "slept",
    "write_diary_and_go_sleep": "wrote in his diary and slept",
    "go_back": "went back",
    "go_forward": "went forward",
    "block": "blocked",
    "flee": "ran away",
    "cast": "cast a spell",
    # tools (folded into one line)
    "scroll": "read the quest scroll",
    "inventory": "checked his belongings",
    "status": "checked himself",
    "remember": "searched his memory",
    "diary": "read his diary",
}


def _now(clock: Callable[[], datetime] | None = None) -> datetime:
    return clock() if clock is not None else datetime.now()


def _stamp(moment: datetime) -> str:
    """2026-11-22 22:54:21."""
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _action_words(key: str) -> str:
    """Plain words for a menu key, e.g. go_north -> walked north."""
    if key in _ACTION_WORDS:
        return _ACTION_WORDS[key]
    if key.startswith("go_away_to_"):
        return "walked away to " + key[len("go_away_to_"):]
    if key.startswith("go_"):
        return "walked " + key[len("go_"):]
    if key.startswith("attack_"):
        return "attacked"
    return key.replace("_", " ")


def split_narrative(response: str) -> tuple[str, str]:
    """Split the model answer into (narrative, choice value).

    Burt writes prose, then a CHOICE line. The choice is rendered
    separately, so it is not quoted twice.
    """
    narrative: list[str] = []
    choice = ""
    for line in (response or "").splitlines():
        if line.strip().upper().startswith("CHOICE:"):
            choice = line.strip()[len("CHOICE:"):].strip()
            continue
        narrative.append(line)
    return "\n".join(narrative).strip(), choice


def _compact(status: str) -> str:
    """Only the [STATE] section, one line: HP, MP, level, food, date."""
    parts: list[str] = []
    in_state = False
    for line in status.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_state = line.startswith("[STATE]")
            continue
        if in_state and line:
            parts.append(line)
    return " | ".join(parts)


def _quote(text: str) -> str:
    """Block quote; keeps the model's own line breaks."""
    lines = [f"> {line}" if line.strip() else ">" for line in text.splitlines()]
    return "\n".join(lines)


class BlogLog:
    """Markdown chronicle of one run (see module docstring)."""

    def __init__(
        self,
        path: Path | str,
        trace: Trace | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        fsync: bool = False,
        title: str = "BURT",
    ) -> None:
        self._path = Path(path)
        self._trace = trace or Trace()
        self._clock = clock
        self._fsync = fsync
        self._title = title
        self._closed = False
        self._started = False

    @property
    def path(self) -> Path:
        return self._path

    # -- public API ------------------------------------------------

    def start(self, *, life: int = 1, max_steps: int | None = None,
              model: str | None = None) -> None:
        """Header of the run: one block, written once."""
        if self._started:
            return
        self._started = True
        moment = _now(self._clock)
        lines = [
            f"# {self._title} — run {_stamp(moment)}",
            "",
            f"- life: **{life}**",
            f"- session: `{self._trace.session_uuid}`",
        ]
        if max_steps is not None:
            lines.append(f"- planned steps: {max_steps}")
        if model:
            lines.append(f"- model: `{model}`")
        lines.append("")
        self._write("\n".join(lines))

    def turn(
        self,
        *,
        day: int,
        step: int,
        mode: str,
        location: str,
        status_before: str,
        status_after: str,
        response: str,
        action_key: str,
        action_label: str,
        event: str | None = None,
        combat: str | None = None,
        folded: bool = False,
    ) -> None:
        """One turn: status, event, Burt's words, choice, status after."""
        moment = _now(self._clock)
        head = f"## {_stamp(moment)} · day {day} · step {step} · {location}"
        if mode == "combat":
            head += " · COMBAT"
        lines = [head, ""]

        if status_before:
            lines.append(f"**Status:** {_compact(status_before)}")
        if event:
            lines.append(f"**Event:** {event}")
        if combat:
            lines.append(f"**Combat:** {combat}")
        lines.append("")

        narrative, choice = split_narrative(response)
        if narrative:
            lines.append(_quote(narrative))
            lines.append("")

        if folded:
            lines.append(f"**Action:** _{_action_words(action_key)}_")
        else:
            label = action_label or _action_words(action_key)
            lines.append(f"**Choice:** `{action_key}` — {label}")
            if choice:
                lines.append(f"**Model said:** `{choice}`")
        if status_after:
            lines.append(f"**After:** {_compact(status_after)}")
        lines.append("")
        self._write("\n".join(lines))

    def combat_start(
        self,
        *,
        ambush: bool,
        enemies: str,
        initiative: str,
        status: str,
    ) -> None:
        """Combat opening: the fight itself is a headline of the run."""
        lines = [
            f"### ⚔ Combat — {'ambush' if ambush else 'encounter'}",
            "",
            f"- enemies: {enemies}",
            f"- initiative: {initiative}",
            f"- status: {_compact(status)}",
            "",
        ]
        self._write("\n".join(lines))

    def diary(self, *, day: int, text: str) -> None:
        lines = [f"### 📖 Diary — day {day}", "", _quote((text or "").strip()), ""]
        self._write("\n".join(lines))

    def death(self, *, life: int, day: int, step: int, cause: str,
              location: str) -> None:
        lines = [
            f"## ☠ Death — life {life} · day {day} · step {step}",
            "",
            f"- cause: **{cause}**",
            f"- location: {location}",
            "",
        ]
        self._write("\n".join(lines))

    def epitaph(self, *, life: int, days: int, cause: str, text: str) -> None:
        lines = [
            f"### 🪦 Epitaph — life {life} ({days} days, {cause})",
            "",
            _quote((text or "").strip()),
            "",
        ]
        self._write("\n".join(lines))

    def resurrection(self, *, hp: int) -> None:
        lines = ["### ✨ Resurrected", "", f"- HP: {hp}", ""]
        self._write("\n".join(lines))

    def new_life(self, *, life: int, memory: str | None) -> None:
        lines = [f"## 🔄 New life — {life}", ""]
        lines.append(f"- memory: **{'yes' if memory else 'no'}**")
        lines.append("")
        self._write("\n".join(lines))

    def close(self) -> None:
        """Idempotent: nothing is buffered."""
        self._closed = True

    # -- internal --------------------------------------------------

    def _write(self, block: str) -> None:
        if self._closed:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8", newline="\n") as f:
                f.write(block.rstrip("\n") + "\n\n")
                f.flush()
                if self._fsync:
                    import os
                    os.fsync(f.fileno())
        except OSError:
            # Blog logging must never break the game loop.
            logger.warning("blog log write failed", exc_info=True)


__all__ = ["BlogLog", "split_narrative", "FOLDED_TOOLS"]
