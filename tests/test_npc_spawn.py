"""Tests for burt/npc_spawn.py — spec §32 (spawn by location).

Rules:
- village: 1-3 roles from its pool, no duplicates
- temple / dungeon: exactly one fixed role, always
- river / road: one role, plus a rare role when d6 >= 5
- other locations: empty
- spawn is cached per node: re-entering never regenerates
- bandit is a monster (§21), never an NPC role
"""
from __future__ import annotations

import pytest

from burt import npc_spawn


ALL_ROLES = frozenset({
    "elder", "peasant", "peasant_woman", "blacksmith", "merchant",
    "child", "guard", "fisherman", "veteran", "cleric", "necromancer",
    "tavernkeeper",
})


def _rng_seq(*values):
    """rng stub: returns the values in order, then repeats the last one."""
    seq = list(values)
    if not seq:
        raise ValueError("_rng_seq needs at least one value")

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


# ---------------------------------------------------------------------
# Pools (§32)
# ---------------------------------------------------------------------

class TestPools:
    def test_village_pool(self):
        assert set(npc_spawn.ROLE_SPAWN["village"]) == {
            "elder", "peasant", "peasant_woman", "blacksmith",
            "merchant", "child", "guard", "tavernkeeper",
        }

    def test_river_pool(self):
        assert set(npc_spawn.ROLE_SPAWN["river"]) == {"fisherman", "merchant"}

    def test_road_pool(self):
        assert set(npc_spawn.ROLE_SPAWN["road"]) == {"merchant"}

    def test_forest_pool_is_empty(self):
        assert npc_spawn.ROLE_SPAWN["forest"] == ()

    def test_veteran_is_not_in_any_pool(self):
        # The veteran is spawned only by maybe_add_veteran in the village.
        for pool in npc_spawn.ROLE_SPAWN.values():
            assert npc_spawn.VETERAN_ROLE not in pool

    def test_temple_always_cleric(self):
        assert npc_spawn.ROLE_SPAWN["temple"] == ("cleric",)

    def test_dungeon_always_necromancer(self):
        assert npc_spawn.ROLE_SPAWN["dungeon"] == ("necromancer",)

    def test_bandit_is_not_a_role(self):
        for pool in npc_spawn.ROLE_SPAWN.values():
            assert "bandit" not in pool

    def test_all_pool_roles_exist(self):
        for pool in npc_spawn.ROLE_SPAWN.values():
            for role in pool:
                assert role in ALL_ROLES, role

    def test_religious_roles_are_rare(self):
        assert npc_spawn.RARE_ROLES == frozenset({"cleric", "necromancer"})

    def test_empty_locations_have_no_roles(self):
        for loc in ("crossroads", "thicket", "field", "steppe", "swamp"):
            assert npc_spawn.ROLE_SPAWN.get(loc, ()) == ()


# ---------------------------------------------------------------------
# Village: 1-3 roles, no duplicates
# ---------------------------------------------------------------------

class TestVillageSpawn:
    @pytest.mark.parametrize("roll,expected", [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3)])
    def test_count_by_roll(self, roll, expected):
        roles = npc_spawn.roll_npcs(
            "village", _rng_seq(roll, 1), _rng_seq(roll, 1),
        )
        assert len(roles) == expected

    def test_no_duplicates(self):
        roles = npc_spawn.roll_npcs("village", _rng_seq(3), _rng_seq(6, 6, 6))
        assert len(roles) == len(set(roles))

    def test_roles_within_pool(self):
        roles = npc_spawn.roll_npcs("village", _rng_seq(5, 2, 6), _rng_seq(4, 3, 1))
        for role in roles:
            assert role in npc_spawn.ROLE_SPAWN["village"]

    def test_deterministic(self):
        a = npc_spawn.roll_npcs("village", _rng_seq(4, 2, 5), _rng_seq(2, 5, 1))
        b = npc_spawn.roll_npcs("village", _rng_seq(4, 2, 5), _rng_seq(2, 5, 1))
        assert a == b


# ---------------------------------------------------------------------
# Temple / dungeon: always exactly one
# ---------------------------------------------------------------------

class TestFixedLocations:
    def test_temple_is_cleric(self):
        assert npc_spawn.roll_npcs("temple", _rng_seq(1), _rng_seq(1)) == ("cleric",)

    def test_dungeon_is_necromancer(self):
        assert npc_spawn.roll_npcs("dungeon", _rng_seq(6), _rng_seq(6)) == ("necromancer",)

    def test_single_regardless_of_roll(self):
        for roll in range(1, 7):
            assert npc_spawn.roll_npcs("temple", _rng_seq(roll), _rng_seq(roll)) == ("cleric",)


# ---------------------------------------------------------------------
# River / road: one role, rare role on d6 >= 5
# ---------------------------------------------------------------------

class TestSparseLocations:
    def test_river_common_role(self):
        roles = npc_spawn.roll_npcs("river", _rng_seq(1), _rng_seq(1))
        assert roles == ("fisherman",)

    def test_road_common_role(self):
        roles = npc_spawn.roll_npcs("road", _rng_seq(1), _rng_seq(1))
        assert roles == ("merchant",)

    @pytest.mark.parametrize("rare_roll", [5, 6])
    def test_rare_role_added(self, rare_roll):
        roles = npc_spawn.roll_npcs("river", _rng_seq(1), _rng_seq(rare_roll))
        assert len(roles) == 2
        assert len(set(roles) & npc_spawn.RARE_ROLES) == 1

    @pytest.mark.parametrize("rare_roll", [1, 2, 3, 4])
    def test_no_rare_role_below_5(self, rare_roll):
        roles = npc_spawn.roll_npcs("river", _rng_seq(1), _rng_seq(rare_roll))
        assert roles == ("fisherman",)


# ---------------------------------------------------------------------
# Empty locations
# ---------------------------------------------------------------------

class TestEmptyLocations:
    @pytest.mark.parametrize("loc", ["crossroads", "thicket", "field", "steppe", "swamp"])
    def test_no_roles(self, loc):
        assert npc_spawn.roll_npcs(loc, _rng_seq(3), _rng_seq(6)) == ()

    def test_unknown_location(self):
        assert npc_spawn.roll_npcs("nowhere", _rng_seq(3), _rng_seq(6)) == ()


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

class TestValidation:
    @pytest.mark.parametrize("bad", [0, 7, -1])
    def test_invalid_count_roll(self, bad):
        with pytest.raises(ValueError):
            npc_spawn.roll_npcs("village", _rng_seq(bad), _rng_seq(1))

    @pytest.mark.parametrize("bad", [0, 7, -1])
    def test_invalid_rare_roll(self, bad):
        with pytest.raises(ValueError):
            npc_spawn.roll_npcs("village", _rng_seq(1), _rng_seq(bad))


# ---------------------------------------------------------------------
# ensure_npcs: cache per node (§32, no regeneration)
# ---------------------------------------------------------------------

class TestEnsureNpcs:
    def _hidden(self, **kw):
        return {"npcs_here": [], "npcs_by_node": {}, **kw}

    def test_fills_npcs_here(self):
        hidden = self._hidden()
        changed = npc_spawn.ensure_npcs(hidden, "village", "node_5", _rng_seq(3))
        assert changed is True
        assert hidden["npcs_here"]
        assert all(r in npc_spawn.ROLE_SPAWN["village"] for r in hidden["npcs_here"])

    def test_caches_by_node(self):
        hidden = self._hidden()
        npc_spawn.ensure_npcs(hidden, "village", "node_5", _rng_seq(3))
        assert "node_5" in hidden["npcs_by_node"]

    def test_reentry_does_not_regenerate(self):
        hidden = self._hidden()
        npc_spawn.ensure_npcs(hidden, "village", "node_5", _rng_seq(6, 1, 2, 3))
        first = list(hidden["npcs_here"])
        npc_spawn.ensure_npcs(hidden, "village", "node_5", _rng_seq(1, 4, 5, 6))
        assert hidden["npcs_here"] == first

    def test_reentry_returns_false(self):
        hidden = self._hidden()
        npc_spawn.ensure_npcs(hidden, "village", "node_5", _rng_seq(3))
        assert npc_spawn.ensure_npcs(hidden, "village", "node_5", _rng_seq(3)) is False

    def test_empty_location_clears_npcs(self):
        hidden = self._hidden(npcs_here=["elder"])
        npc_spawn.ensure_npcs(hidden, "field", "node_9", _rng_seq(3))
        assert hidden["npcs_here"] == []

    def test_moving_between_nodes_swaps_npcs(self):
        hidden = self._hidden()
        npc_spawn.ensure_npcs(hidden, "temple", "n1", _rng_seq(1))
        assert hidden["npcs_here"] == ["cleric"]
        npc_spawn.ensure_npcs(hidden, "dungeon", "n2", _rng_seq(1))
        assert hidden["npcs_here"] == ["necromancer"]

    def test_returns_roles_copy(self):
        hidden = self._hidden()
        npc_spawn.ensure_npcs(hidden, "temple", "n1", _rng_seq(1))
        roles = npc_spawn.npcs_for(hidden, "n1")
        assert roles == ("cleric",)

    def test_npc_without_quest_slot_has_no_quests(self):
        # Bandit is a monster, so no NPC role can be a monster in the cache.
        hidden = self._hidden()
        for loc in npc_spawn.ROLE_SPAWN:
            npc_spawn.ensure_npcs(hidden, loc, f"x_{loc}", _rng_seq(6))
            assert "bandit" not in hidden["npcs_here"]


