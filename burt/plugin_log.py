"""Plugin technical logger — §38, §39 spec v0.7.0.

The game has two independent sinks:

- game_session.jsonl    gameplay, append-only, synchronous (burt/game_session.py)
- logs/plugin_*.jsonl   technical, JSONL, asynchronous      (this module)

Record format (§38) — one line = one event:

    {"seq", "ts", "level", "session_uuid", "turn_uuid", "call_uuid",
     "floor", "layer", "event", "data"}

Levels (§39):

    0 DEBUG  raw prompt/response, dice rolls (DEBUG=True only)
    1 INFO   turn finished, tool called, previews (always)
    2 WARN   CHOICE not parsed, tool not found, retry (always)
    3 ERROR  crash, broken JSON, LLM down (always + crash report)

Behaviour:

- Rotation every LOG_ROTATE_HOURS (12h): plugin_YYYY-MM-DD_HH.jsonl.
  Old files are never deleted, they just stop receiving new lines (§39).
- Ring buffer (deque, maxlen=RING_BUFFER_SIZE) is synchronous, always up to
  date, and is the source of the crash report (§39).
- All events go through asyncio.Queue.put_nowait; a writer task drains it.
  Without a running loop the logger writes synchronously (sync mode).
- On ERROR: synchronous queue drain + crash report, no await (§39).
- atexit / SIGINT / SIGTERM: flush the queue and dump the ring buffer (§39).
- Final line of a session is "session_summary" with counters (§39).

No game logic here: no state, no dice, no LLM.
"""
from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import signal
import threading
import traceback as tb_module
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from burt.trace import Trace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Levels (§39)
# ---------------------------------------------------------------------

LEVEL_DEBUG = 0
LEVEL_INFO = 1
LEVEL_WARN = 2
LEVEL_ERROR = 3

LEVEL_NAMES: dict[int, str] = {
    LEVEL_DEBUG: "DEBUG",
    LEVEL_INFO: "INFO",
    LEVEL_WARN: "WARN",
    LEVEL_ERROR: "ERROR",
}

VALID_LAYERS: frozenset[str] = frozenset({"react", "tool", "interaction"})

DEFAULT_VERSION = "v0.7.0"


# ---------------------------------------------------------------------
# Ring buffer (§39)
# ---------------------------------------------------------------------

class RingBuffer:
    """Last N log lines of the current floor. Synchronous, no await."""

    def __init__(self, maxlen: int = 20) -> None:
        if not isinstance(maxlen, int) or maxlen <= 0:
            raise ValueError(f"maxlen must be int > 0, got {maxlen!r}")
        self._maxlen = maxlen
        self._lines: deque[str] = deque(maxlen=maxlen)

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def __len__(self) -> int:
        return len(self._lines)

    def append(self, line: str) -> None:
        self._lines.append(line)

    def dump(self) -> list[str]:
        return list(self._lines)

    def clear(self) -> None:
        self._lines.clear()


# ---------------------------------------------------------------------
# Helpers: time, file names, payload previews
# ---------------------------------------------------------------------

def _now(clock: Callable[[], datetime] | None = None) -> datetime:
    return clock() if clock is not None else datetime.now()


def _iso(moment: datetime) -> str:
    """ISO timestamp with milliseconds, e.g. 2026-10-11T21:40:00.123."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


def _bucket_hour(moment: datetime, rotate_hours: int) -> str:
    """Rotation bucket: floor(hour / rotate_hours) * rotate_hours."""
    start = (moment.hour // rotate_hours) * rotate_hours
    return f"{start:02d}"


def _plugin_path(log_dir: Path, moment: datetime, rotate_hours: int) -> Path:
    """logs/plugin_<YYYY-MM-DD>_<HH>.jsonl."""
    return log_dir / f"plugin_{moment:%Y-%m-%d}_{_bucket_hour(moment, rotate_hours)}.jsonl"


def _crash_path(crash_dir: Path, moment: datetime, turn_uuid: str | None) -> Path:
    """crashes/crash_<ts>_<turn_uuid>.log."""
    stamp = moment.strftime("%Y%m%d-%H%M%S-") + f"{moment.microsecond // 1000:03d}"
    return crash_dir / f"crash_{stamp}_{turn_uuid or 'no-turn'}.log"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def preview_payload(
    prompt: str | None = None,
    response: str | None = None,
    *,
    chars: int = 80,
    debug: bool = False,
) -> dict[str, Any]:
    """Build the `data` payload of a react record (§38).

    DEBUG=True  -> full prompt and response.
    DEBUG=False -> chars + sha256 hash + first `chars` characters.
    """
    data: dict[str, Any] = {}
    if prompt is not None:
        if debug:
            data["prompt"] = prompt
        else:
            data["prompt_chars"] = len(prompt)
            data["prompt_hash"] = _sha256(prompt)
            data["prompt_preview"] = prompt[:chars]
    if response is not None:
        if debug:
            data["response"] = response
        else:
            data["response_chars"] = len(response)
            data["response_hash"] = _sha256(response)
            data["response_preview"] = response[:chars]
    return data


def _to_json_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)



# ---------------------------------------------------------------------
# Plugin logger
# ---------------------------------------------------------------------

class PluginLogger:
    """Async technical logger (§38, §39).

    Lifecycle:
        start()   -> idempotent; creates the writer task if a loop runs
        stop()    -> async; drains the queue, writes session_summary
        close()   -> sync; same as stop() for atexit and signal handlers
    """

    def __init__(
        self,
        log_dir: Path | str = "logs/",
        crash_dir: Path | str = "crashes/",
        trace: Trace | None = None,
        *,
        level: int = 1,
        debug: bool = False,
        rotate_hours: int = 12,
        ring_size: int = 20,
        preview_chars: int = 80,
        queue_maxsize: int = 1000,
        version: str = DEFAULT_VERSION,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if level not in LEVEL_NAMES:
            raise ValueError(f"level must be 0..3, got {level!r}")
        if not isinstance(rotate_hours, int) or rotate_hours <= 0 or 24 % rotate_hours:
            raise ValueError(f"rotate_hours must divide 24, got {rotate_hours!r}")

        self._log_dir = Path(log_dir)
        self._crash_dir = Path(crash_dir)
        self._trace = trace or Trace()
        self._level = level
        self._debug = bool(debug)
        self._rotate_hours = rotate_hours
        self._preview_chars = preview_chars
        self._queue_maxsize = queue_maxsize
        self._version = version
        self._clock = clock

        self._ring = RingBuffer(ring_size)
        self._queue: asyncio.Queue[str] | None = None
        self._writer_task: asyncio.Task | None = None
        self._lock = threading.Lock()
        self._started = False
        self._closed = False
        self._handle = None
        self._open_path: Path | None = None
        self._in_crash = False
        self._last_seq = 0

        self._warn_count = 0
        self._error_count = 0
        self._floors_total = 0
        self._written = 0

    # -- properties ------------------------------------------------

    @property
    def trace(self) -> Trace:
        return self._trace

    @property
    def ring(self) -> RingBuffer:
        return self._ring

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    @property
    def crash_dir(self) -> Path:
        return self._crash_dir

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def counters(self) -> dict[str, int]:
        return {
            "warn_count": self._warn_count,
            "error_count": self._error_count,
            "floors_total": self._floors_total,
            "written": self._written,
        }

    # -- lifecycle -------------------------------------------------

    def start(self) -> None:
        """Start the writer task. No-op when already started or closed.

        Without a running loop the logger stays in sync mode: every line is
        written straight to disk (this is what unit tests use).
        """
        if self._closed:
            return
        if not self._started:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._crash_dir.mkdir(parents=True, exist_ok=True)
            self._started = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and self._writer_task is None and self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._queue_maxsize)
            self._writer_task = loop.create_task(self._writer())
        if self._queue is None:
            self.event(LEVEL_INFO, "session_start", {
                "version": self._version,
                "debug": self._debug,
                "level": self._level,
                "rotate_hours": self._rotate_hours,
            })

    async def stop(self) -> None:
        """Flush everything and write session_summary. Idempotent."""
        self.close()

    def close(self) -> None:
        """Synchronous shutdown for atexit and signal handlers. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._flush_sync()
        self._write_summary()
        if self._writer_task is not None:
            self._writer_task.cancel()
            self._writer_task = None
        self._queue = None
        self._close_handle()

    def register_atexit(self) -> None:
        atexit.register(self._atexit_hook)

    def install_signal_handlers(self) -> None:
        """Flush on SIGINT/SIGTERM. Best effort: Windows lacks loop signals."""
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._signal_hook)
            except (ValueError, OSError, RuntimeError):
                continue

    # -- public emitters -------------------------------------------

    def event(
        self,
        level: int,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        layer: str | None = None,
        call_uuid: str | None = None,
    ) -> None:
        """Emit one record. The single entry point of the logger."""
        if level not in LEVEL_NAMES:
            raise ValueError(f"level must be 0..3, got {level!r}")
        if layer is not None and layer not in VALID_LAYERS:
            raise ValueError(f"invalid layer: {layer!r}")

        # Late events after shutdown are ignored: the summary is final.
        if self._closed:
            return
        # §39: level 0 is written only when DEBUG=True.
        if level == LEVEL_DEBUG and not self._debug:
            return
        if level < self._level:
            return
        if not self._started:
            self.start()

        if level == LEVEL_WARN:
            self._warn_count += 1
        elif level == LEVEL_ERROR:
            self._error_count += 1

        record = self._build_record(level, event, data or {}, layer, call_uuid)
        line = _to_json_line(record)
        self._ring.append(line)
        self._emit_line(line)

        if level == LEVEL_ERROR and not self._in_crash:
            # ERROR via event() has no traceback; die() owns the crash report.
            self._flush_sync()

    def react(self, event: str, data: dict[str, Any] | None = None,
              *, call_uuid: str | None = None) -> None:
        """Layer 1: LLM exchange. Full payload only when DEBUG=True."""
        payload = dict(data or {})
        level = LEVEL_DEBUG if self._debug else LEVEL_INFO
        self.event(level, event, payload, layer="react", call_uuid=call_uuid)

    def react_exchange(
        self,
        event: str,
        *,
        prompt: str | None = None,
        response: str | None = None,
        call_uuid: str | None = None,
    ) -> None:
        """Layer 1 helper applying the DEBUG policy from §38 by itself."""
        payload = preview_payload(
            prompt=prompt,
            response=response,
            chars=self._preview_chars,
            debug=self._debug,
        )
        self.react(event, payload, call_uuid=call_uuid)

    def tool(self, event: str, data: dict[str, Any] | None = None,
             *, call_uuid: str | None = None) -> None:
        """Layer 2: tool execution (action)."""
        level = LEVEL_DEBUG if self._debug else LEVEL_INFO
        self.event(level, event, dict(data or {}), layer="tool", call_uuid=call_uuid)

    def interaction(self, event: str, data: dict[str, Any] | None = None,
                    *, level: int | None = None,
                    call_uuid: str | None = None) -> None:
        """Layer 3: parsing the answer, finding the tool in the menu."""
        if level is None:
            level = LEVEL_DEBUG if self._debug else LEVEL_INFO
        self.event(level, event, dict(data or {}), layer="interaction", call_uuid=call_uuid)

    def state_change(self, from_state: str, to_state: str, **extra: Any) -> None:
        """§39: alert on loop state transitions."""
        quiet = {("waiting_llm", "running"), ("running", "writing_state")}
        level = LEVEL_INFO
        if (from_state, to_state) in (("waiting_llm", "error"), ("running", "crashed")):
            level = LEVEL_ERROR
        elif (from_state, to_state) == ("running", "waiting_llm"):
            level = LEVEL_DEBUG
        self.event(level, "state_change", {
            "from": from_state, "to": to_state, **extra,
        })
        self._flush_sync()

    def die(self, message: str, exc: BaseException | None = None,
            *, event: str = "crash", layer: str | None = None,
            call_uuid: str | None = None) -> None:
        """ERROR + crash report with the ring buffer and traceback."""
        self._error_count += 1
        if not self._started:
            self.start()
        record = self._build_record(LEVEL_ERROR, event, {"message": message}, layer, call_uuid)
        line = _to_json_line(record)
        self._ring.append(line)
        self._emit_line(line)
        self._flush_sync()
        self._write_crash(
            event, message, exc=exc,
            turn_uuid=record.get("turn_uuid"), call_uuid=call_uuid,
        )

    def error(self, event: str, message: str, exc: BaseException | None = None,
              *, layer: str | None = None, call_uuid: str | None = None) -> None:
        """Alias of die(): an ERROR always implies a crash report (§39)."""
        self.die(message, exc, event=event, layer=layer, call_uuid=call_uuid)

    # -- internal: record building ---------------------------------

    def _build_record(
        self,
        level: int,
        event: str,
        data: dict[str, Any],
        layer: str | None,
        call_uuid: str | None,
    ) -> dict[str, Any]:
        moment = _now(self._clock)
        turn = self._trace.current_turn
        seq = self._trace.next_seq()
        self._last_seq = seq
        return {
            "seq": seq,
            "ts": _iso(moment),
            "level": level,
            "session_uuid": self._trace.session_uuid,
            "turn_uuid": turn.turn_uuid if turn is not None else None,
            "call_uuid": call_uuid,
            "floor": turn.floor if turn is not None else 0,
            "layer": layer,
            "event": event,
            "data": data,
        }

    # -- internal: writing -----------------------------------------

    def _emit_line(self, line: str) -> None:
        queue = self._queue
        if queue is None:
            self._write_line(line)
            return
        try:
            queue.put_nowait(line)
        except asyncio.QueueFull:
            # §39: never lose a line — fall back to a synchronous write.
            self._write_line(line)
            overflow = self._build_record(
                LEVEL_WARN, "log_queue_full", {"size": self._queue_maxsize}, None, None,
            )
            overflow_line = _to_json_line(overflow)
            self._warn_count += 1
            self._ring.append(overflow_line)
            self._write_line(overflow_line)

    def _write_line(self, line: str) -> None:
        try:
            self._ensure_handle()
            if self._handle is None:
                return
            self._handle.write(line)
            self._handle.write("\n")
            self._handle.flush()
            self._written += 1
        except OSError:
            # Logging must never break the game loop.
            logger.warning("plugin log write failed", exc_info=True)

    def _ensure_handle(self) -> None:
        moment = _now(self._clock)
        path = _plugin_path(self._log_dir, moment, self._rotate_hours)
        if self._handle is not None and self._open_path == path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._close_handle()
        self._handle = open(path, "a", encoding="utf-8", newline="\n")
        self._open_path = path

    def _close_handle(self) -> None:
        handle = self._handle
        self._handle = None
        self._open_path = None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass

    def _flush_sync(self) -> None:
        """Drain the async queue right now, without awaiting (§39)."""
        queue = self._queue
        if queue is None:
            return
        try:
            while True:
                line = queue.get_nowait()
                self._write_line(line)
                queue.task_done()
        except asyncio.QueueEmpty:
            return

    def flush_sync(self) -> None:
        """Public wrapper: make everything emitted so far visible on disk."""
        self._flush_sync()

    def event_sync(
        self,
        level: int,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        layer: str | None = None,
        call_uuid: str | None = None,
    ) -> None:
        """event() followed by a synchronous drain (used between layers)."""
        self.event(level, event, data, layer=layer, call_uuid=call_uuid)
        self._flush_sync()

    async def _writer(self) -> None:
        """Writer task: drains the queue to disk. Cancelled by close()."""
        queue = self._queue
        if queue is None:
            return
        try:
            while True:
                line = await queue.get()
                try:
                    self._write_line(line)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            self._flush_sync()
            raise

    # -- internal: crash report (§39) ------------------------------

    def _write_crash(
        self,
        event: str,
        message: str,
        exc: BaseException | None = None,
        turn_uuid: str | None = None,
        call_uuid: str | None = None,
    ) -> None:
        """crash_<ts>_<turn_uuid>.log with the ring buffer and traceback."""
        moment = _now(self._clock)
        turn = self._trace.current_turn
        try:
            self._crash_dir.mkdir(parents=True, exist_ok=True)
            path = _crash_path(
                self._crash_dir, moment, turn_uuid or (turn.turn_uuid if turn else None),
            )
            lines = [
                "=== BURT PLUGIN CRASH ===",
                f"time:     {_iso(moment)}",
                f"version:  {self._version}",
                f"session:  {self._trace.session_uuid}",
                f"turn:     {turn.turn_uuid if turn else 'none'}",
                f"call:     {call_uuid or 'none'}",
                f"floor:    {turn.floor if turn else 0}",
                f"level:    {LEVEL_ERROR}",
                f"event:    {event}",
                f"message:  {message}",
                "",
                f"--- last {self._ring.maxlen} lines (ring buffer) ---",
                *self._ring.dump(),
                "",
                "--- traceback ---",
            ]
            if exc is not None:
                lines.extend(
                    "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
                    .rstrip("\n").split("\n")
                )
            else:
                lines.append("(no exception)")
            lines.extend(["", "=== END ==="])
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            logger.warning("crash report write failed", exc_info=True)

    # -- internal: session summary (§39) ---------------------------

    def _write_summary(self) -> None:
        turn = self._trace.current_turn
        if turn is not None:
            self._floors_total = max(self._floors_total, turn.floor)
        record = self._build_record(
            LEVEL_INFO,
            "session_summary",
            {
                "warn_count": self._warn_count,
                "error_count": self._error_count,
                "floors_total": self._floors_total,
                "session_uuid": self._trace.session_uuid,
                "written": self._written,
            },
            None,
            None,
        )
        self._write_line(_to_json_line(record))

    # -- internal: hooks -------------------------------------------

    def _atexit_hook(self) -> None:
        try:
            self.close()
        except Exception:  # pragma: no cover - shutdown must never raise
            pass

    def _signal_hook(self, signum, _frame) -> None:  # pragma: no cover
        try:
            self.close()
        finally:
            previous = getattr(self, "_previous_signal", None)
            if callable(previous):
                previous(signum, _frame)
            else:
                raise SystemExit(0)


