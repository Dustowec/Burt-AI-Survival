"""One date format everywhere: "N day" (new_bug §2)."""
from __future__ import annotations

from pathlib import Path

import pytest

import main
from burt import loop
from burt import state as state_mod
from burt.loop import Action


def _fresh(day: int = 1) -> dict:
    st = main.make_new_state(life=1)
    st["hidden"]["day"] = day
    st["visible"]["date"] = state_mod.format_date(day)
    return st


class TestHelper:
    def test_format_date(self):
        assert state_mod.format_date(1) == "1 day"
        assert state_mod.format_date(2) == "2 day"
        assert state_mod.format_date(7) == "7 day"

    @pytest.mark.parametrize("raw,expected", [
        ("1 day", "1 day"),
        ("2 day", "2 day"),
        ("3 day(s)", "3 day"),
        (" 5  day(s) ", "5 day"),
        ("someday", "someday"),
    ])
    def test_canonical_date(self, raw, expected):
        assert state_mod.canonical_date(raw) == expected

    def test_initial_state_uses_helper(self):
        st = state_mod.create_initial_state(
            life=1,
            session_uuid="u",
            config_hash="v0.7.0",
            session_started="2026-11-20T00:00:00+00:00",
        )
        assert st["visible"]["date"] == "1 day"


class TestAllPaths:
    def test_sync_meta_from_hidden(self):
        st = _fresh(day=4)
        main._sync_meta_from_hidden(st)
        assert st["visible"]["date"] == "4 day"

    def test_ensure_runtime_fields_normalizes_legacy(self):
        st = _fresh(day=3)
        st["visible"]["date"] = "3 day(s)"
        main._ensure_runtime_fields(st)
        assert st["visible"]["date"] == "3 day"

    def test_voluntary_sleep(self):
        st = _fresh(day=2)
        st["hidden"]["step"] = 19
        loop.execute_action(Action("sleep", "Sleep"), st, rng=lambda: 4)
        assert st["hidden"]["day"] == 3
        assert st["visible"]["date"] == "3 day"

    def test_forced_sleep(self):
        st = _fresh(day=5)
        st["hidden"]["step"] = 20
        main._do_sleep(st)
        assert st["hidden"]["day"] == 6
        assert st["visible"]["date"] == "6 day"


class TestSourceHasNoLegacySuffix:
    def test_no_legacy_suffix_in_game_code(self):
        files = [Path("main.py"), *sorted(Path("burt").glob("*.py"))]
        for path in files:
            text = path.read_text(encoding="utf-8")
            assert "day(s)" not in text, f"legacy date suffix in {path}"
