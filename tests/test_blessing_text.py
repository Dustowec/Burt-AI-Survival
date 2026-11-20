"""Blessing text depends on the REAL HP/MP delta (new_bug §3)."""
from __future__ import annotations

import main
from burt import loop
from burt.dice import MovementEventResult
from burt.loop import (
    Action, BLESSING_RESTORES, BLESSING_WASHES, _apply_movement_event,
)


def _visible(hp: int, mp: int, hp_max: int = 10, mp_max: int = 3) -> dict:
    return {
        "hp": hp, "hp_max": hp_max, "mp": mp, "mp_max": mp_max,
        "eat": True, "sleep_counter": 0, "date": "1 day", "effects": [],
        "inventory": [], "wallet": {"coin": 0}, "skills_visible": [],
        "location": {"name": "Crossroads", "exits": ["north"]},
    }


def _blessing(hp_restore: int = 3, mp_restore: int = 2) -> MovementEventResult:
    return MovementEventResult(
        event_type="blessing",
        description="A blessing restores your vitality.",
        hp_restore=hp_restore,
        mp_restore=mp_restore,
    )


class TestHelper:
    def test_full_hp_mp_washes_over(self):
        visible = _visible(10, 3)
        hidden = {}
        text = _apply_movement_event(_blessing(), visible, hidden)
        assert text == BLESSING_WASHES
        assert visible["hp"] == 10
        assert visible["mp"] == 3

    def test_hp_grows_restores(self):
        visible = _visible(5, 3)
        hidden = {}
        text = _apply_movement_event(_blessing(), visible, hidden)
        assert text == BLESSING_RESTORES
        assert visible["hp"] == 8
        assert visible["mp"] == 3
        assert hidden["hp_raw"] == 8

    def test_mp_grows_restores(self):
        visible = _visible(10, 1)
        hidden = {}
        text = _apply_movement_event(_blessing(), visible, hidden)
        assert text == BLESSING_RESTORES
        assert visible["mp"] == 3
        assert hidden["mp_raw"] == 3

    def test_caps_at_max(self):
        visible = _visible(9, 2)
        hidden = {}
        _apply_movement_event(_blessing(5, 5), visible, hidden)
        assert visible["hp"] == 10
        assert visible["mp"] == 3


def _movement_state() -> dict:
    st = main.make_new_state(life=1)
    st["hidden"]["location_graph"] = {
        "start": {"type": "crossroads", "entered": True,
                  "exits": {"north": "n1", "east": None,
                            "south": None, "west": None}},
        "n1": {"type": "crossroads", "entered": True,
               "exits": {"south": "start", "north": None,
                         "east": None, "west": None}},
    }
    st["hidden"]["current_node_id"] = "start"
    st["visible"]["location"]["exits"] = ["north"]
    return st


class TestMovementWiring:
    def test_full_hp_movement_says_washes_over(self, monkeypatch):
        st = _movement_state()
        st["visible"]["hp"] = 10
        st["visible"]["mp"] = 3
        monkeypatch.setattr(
            loop, "resolve_movement_event", lambda *a, **kw: _blessing(),
        )
        result = loop.execute_action(
            Action("go_north", "Go north"), st, rng=lambda: 6,
        )
        assert result.events[0] == BLESSING_WASHES
        assert st["visible"]["hp"] == 10

    def test_wounded_movement_says_restores(self, monkeypatch):
        st = _movement_state()
        st["visible"]["hp"] = 5
        st["visible"]["mp"] = 3
        monkeypatch.setattr(
            loop, "resolve_movement_event", lambda *a, **kw: _blessing(),
        )
        result = loop.execute_action(
            Action("go_north", "Go north"), st, rng=lambda: 6,
        )
        assert result.events[0] == BLESSING_RESTORES
        assert st["visible"]["hp"] == 8
