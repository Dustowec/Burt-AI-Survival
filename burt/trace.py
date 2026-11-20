"""Tracing identifiers — §38 spec v0.7.0.

One plugin run produces a tree of identifiers:

    session_uuid            one per run
      └── turn_uuid         one per floor (one full game turn)
            └── call_uuid   one per call inside the floor (LLM, tool)

`seq` is a monotonic global counter. It lets the reader restore the order
of events even when the plugin log is written asynchronously (§38, §39).

Pure core: no I/O, no asyncio, no LLM, no logging.
"""
from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TurnTrace:
    """Identifiers of one floor (one full game turn)."""

    floor: int
    turn_uuid: str
    session_uuid: str


class Trace:
    """Tracing state of a single plugin run.

    Usage:
        trace = Trace()
        turn = trace.new_turn()        # start of a game turn
        call = trace.new_call()        # any call inside this turn
        seq = trace.next_seq()         # for every emitted log line
    """

    def __init__(self, session_uuid: str | None = None) -> None:
        self._session_uuid = session_uuid or str(uuid.uuid4())
        self._floor = 0
        self._current: TurnTrace | None = None
        self._seq = itertools.count(1)

    @property
    def session_uuid(self) -> str:
        """Identifier of the whole run; never changes."""
        return self._session_uuid

    @property
    def current_turn(self) -> TurnTrace | None:
        """The open floor, or None before the first new_turn()."""
        return self._current

    def new_turn(self) -> TurnTrace:
        """Open a new floor: floor + 1, fresh turn_uuid."""
        self._floor += 1
        self._current = TurnTrace(
            floor=self._floor,
            turn_uuid=str(uuid.uuid4()),
            session_uuid=self._session_uuid,
        )
        return self._current

    def new_call(self) -> str:
        """Fresh call_uuid for a call inside the current floor."""
        return str(uuid.uuid4())

    def next_seq(self) -> int:
        """Monotonic global counter, starts at 1."""
        return next(self._seq)
