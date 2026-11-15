"""Tests for real hunger mechanics on a fresh life (HANDOFF-12 #4).

Burt starts hungry (eat=False) but with bread and water in inventory.
The old crutch (eat=True on start) is removed.
"""

import pytest

from burt import hunger
from burt.state import create_initial_state


def _fresh_state():
    return create_initial_state(
        life=1,
        session_uuid="test",
        config_hash="v0.7.0",
        session_started="2026-01-01T00:00:00",
    )


class TestFreshStateHunger:
    def test_eat_is_false_on_start(self):
        st = _fresh_state()
        assert st["visible"]["eat"] is False

    def test_starts_with_food_and_water(self):
        st = _fresh_state()
        names = [i["name"] for i in st["visible"]["inventory"]]
        assert "bread" in names
        assert "water" in names

    def test_should_inject_hunger_at_step_zero(self):
        assert hunger.should_inject_hunger(0, False) is True

    def test_no_hunger_inject_when_eat_true(self):
        assert hunger.should_inject_hunger(0, True) is False

    def test_fresh_state_validates(self):
        from burt.state import validate_state
        validate_state(_fresh_state())
