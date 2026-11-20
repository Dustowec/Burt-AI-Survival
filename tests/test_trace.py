"""Tests for burt/trace.py — spec §38, §39.

Trace owns the tracing identifiers of one plugin run:

- session_uuid: one per run (§38)
- turn_uuid:    one per floor = one game turn (§38)
- call_uuid:    one per call inside a floor (LLM call, tool call) (§38)
- seq:          monotonic global counter used to sort async writes (§38)

One turn may contain several tool calls: one turn_uuid, many call_uuid.
"""
from __future__ import annotations

import uuid

import pytest

from burt.trace import Trace, TurnTrace


# ---------------------------------------------------------------------
# session_uuid
# ---------------------------------------------------------------------

class TestSessionUuid:
    def test_auto_generated(self):
        tr = Trace()
        assert isinstance(tr.session_uuid, str)
        uuid.UUID(tr.session_uuid)

    def test_stable_across_turns(self):
        tr = Trace()
        first = tr.session_uuid
        tr.new_turn()
        tr.new_turn()
        assert tr.session_uuid == first

    def test_explicit_session_uuid(self):
        tr = Trace(session_uuid="fixed-session")
        assert tr.session_uuid == "fixed-session"

    def test_two_traces_differ(self):
        assert Trace().session_uuid != Trace().session_uuid


# ---------------------------------------------------------------------
# turn_uuid / floor
# ---------------------------------------------------------------------

class TestTurn:
    def test_first_floor_is_one(self):
        turn = Trace().new_turn()
        assert isinstance(turn, TurnTrace)
        assert turn.floor == 1

    def test_floor_increments(self):
        tr = Trace()
        assert [tr.new_turn().floor for _ in range(3)] == [1, 2, 3]

    def test_turn_uuid_unique(self):
        tr = Trace()
        assert len({tr.new_turn().turn_uuid for _ in range(50)}) == 50

    def test_turn_uuid_is_valid_uuid(self):
        uuid.UUID(Trace().new_turn().turn_uuid)

    def test_current_turn_before_any(self):
        assert Trace().current_turn is None

    def test_current_turn_after_new_turn(self):
        tr = Trace()
        turn = tr.new_turn()
        assert tr.current_turn == turn

    def test_turn_trace_is_frozen(self):
        turn = Trace().new_turn()
        with pytest.raises(Exception):
            turn.floor = 99  # type: ignore[misc]

    def test_turn_trace_carries_session_uuid(self):
        tr = Trace()
        assert tr.new_turn().session_uuid == tr.session_uuid


# ---------------------------------------------------------------------
# call_uuid
# ---------------------------------------------------------------------

class TestCall:
    def test_call_uuid_unique(self):
        tr = Trace()
        tr.new_turn()
        assert len({tr.new_call() for _ in range(50)}) == 50

    def test_call_uuid_is_valid_uuid(self):
        tr = Trace()
        tr.new_turn()
        uuid.UUID(tr.new_call())

    def test_call_without_turn(self):
        # Defensive: a call outside a floor must not raise.
        uuid.UUID(Trace().new_call())

    def test_many_calls_same_turn(self):
        # §38: three tools in one turn -> one turn_uuid, three call_uuid.
        tr = Trace()
        turn = tr.new_turn()
        calls = [tr.new_call() for _ in range(3)]
        assert tr.current_turn == turn
        assert len(set(calls)) == 3


# ---------------------------------------------------------------------
# seq
# ---------------------------------------------------------------------

class TestSeq:
    def test_first_seq(self):
        assert Trace().next_seq() == 1

    def test_seq_monotonic(self):
        tr = Trace()
        assert [tr.next_seq() for _ in range(5)] == [1, 2, 3, 4, 5]

    def test_seq_shared_across_turns_and_calls(self):
        tr = Trace()
        tr.new_turn()
        a = tr.next_seq()
        tr.new_call()
        b = tr.next_seq()
        tr.new_turn()
        c = tr.next_seq()
        assert (a, b, c) == (1, 2, 3)

    def test_two_traces_are_independent(self):
        a, b = Trace(), Trace()
        assert a.next_seq() == 1
        assert b.next_seq() == 1
