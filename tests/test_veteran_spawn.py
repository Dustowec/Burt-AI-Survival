"""Veteran spawn: village only, rare roll, 10-day cooldown."""
from __future__ import annotations

from burt import npc_spawn


def _hidden(day=1, last=0, roles=None):
    return {
        "day": day,
        "veteran_last_spawn_day": last,
        "npcs_here": list(roles or []),
        "npcs_by_node": {},
    }


class TestVeteranSpawn:
    def test_only_village(self):
        hidden = _hidden()
        calls = []

        def rng():
            calls.append(1)
            return 6

        assert npc_spawn.maybe_add_veteran(
            hidden, "forest", "f1", 20, rng,
        ) is False
        assert calls == []

    def test_cooldown_blocks_without_rolling(self):
        hidden = _hidden(day=5, last=1)
        calls = []

        def rng():
            calls.append(1)
            return 6

        assert npc_spawn.maybe_add_veteran(
            hidden, "village", "v1", 5, rng,
        ) is False
        assert calls == []

    def test_spawn_after_cooldown(self):
        hidden = _hidden(day=11, last=1)
        assert npc_spawn.maybe_add_veteran(
            hidden, "village", "v1", 11, lambda: 5,
        ) is True
        assert npc_spawn.VETERAN_ROLE in hidden["npcs_here"]
        assert npc_spawn.VETERAN_ROLE in hidden["npcs_by_node"]["v1"]
        assert hidden["veteran_last_spawn_day"] == 11

    def test_low_roll_does_not_spawn(self):
        hidden = _hidden(day=11, last=1)
        assert npc_spawn.maybe_add_veteran(
            hidden, "village", "v1", 11, lambda: 4,
        ) is False
        assert hidden["npcs_here"] == []
        assert hidden["veteran_last_spawn_day"] == 1

    def test_already_present_does_not_roll_or_reset_cooldown(self):
        hidden = _hidden(day=11, last=1, roles=["veteran"])
        calls = []

        def rng():
            calls.append(1)
            return 6

        assert npc_spawn.maybe_add_veteran(
            hidden, "village", "v1", 11, rng,
        ) is False
        assert calls == []
        assert hidden["veteran_last_spawn_day"] == 1
