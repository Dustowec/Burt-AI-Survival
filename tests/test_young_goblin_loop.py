"""Tutorial monster: young_goblin only at level 1, club at level 2.

Contract:
- level < 2: every wild spawn is exactly one young_goblin (forest,
  dungeon, field, steppe, swamp, thicket ambush); empty locations stay
  empty; NPC hostility is not touched;
- level >= 2: young_goblin can never spawn; the normal tables return;
- two young_goblin kills = 10 XP = level 2, and the level-up grants one
  club as a simulated drop (not in loot.py); the club is a normal item
  and can be sold;
- old saves already at level 2 get nothing retroactively.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from burt import economy, progression, spawn
from burt.combat import BurtStats, start_combat
from burt.loop import (
    Action, _award_combat_xp, _handle_movement_failure,
    _maybe_start_combat_on_enter, execute_action,
)
from burt.loot import LootDrop


def _seq_rng(values):
    values = list(values)
    state = {"i": 0}

    def _rng():
        i = min(state["i"], len(values) - 1)
        state["i"] += 1
        return values[i]

    return _rng


def make_state(level: int = 1, mode: str = "exploring") -> dict:
    from burt import world
    st = {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "level": level, "xp": 0,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [], "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": mode,
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "combat": None,
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 0, "day": 1,
        },
    }
    return st


def _dead_combat(enemy_keys):
    cs = start_combat(enemy_keys, "burt")
    for enemy in cs.enemies:
        enemy.alive = False
        enemy.hp = 0
    return cs


class _FakeCombatResult:
    def __init__(self, burt, outcome, combat_state, events_llm=None):
        self.burt = burt
        self.events_llm = events_llm or []
        self.outcome = outcome
        self.combat = combat_state


def _has_club(visible: dict) -> bool:
    return any(item.get("name") == "club" for item in visible["inventory"])


# ---------------------------------------------------------------------
# Spawn gate: level 1 -> young_goblin only
# ---------------------------------------------------------------------

class TestSpawnGateInLoop:
    def test_level_one_forest_pending_is_young_goblin(self):
        st = make_state(level=1)
        h = st["hidden"]
        h["current_node_id"] = "f1"
        h["location_graph"]["f1"] = {
            "type": "forest", "entered": True,
            "exits": {"south": "start", "north": None,
                      "east": None, "west": None},
        }
        _maybe_start_combat_on_enter(
            "forest", h, st["visible"], _seq_rng([1, 1, 1]),
        )
        pe = h["pending_encounter"]
        assert isinstance(pe, dict)
        assert pe["enemy_keys"] == [spawn.YOUNG_GOBLIN_KEY]

    def test_level_one_thicket_ambush_is_young_goblin(self):
        st = make_state(level=1)
        h = st["hidden"]
        started = _maybe_start_combat_on_enter(
            "thicket", h, st["visible"], _seq_rng([4, 4, 1]),
        )
        assert started is not None
        assert h["combat"]["enemies"][0]["key"] == spawn.YOUNG_GOBLIN_KEY

    def test_level_one_bad_movement_ambush_is_young_goblin(self):
        st = make_state(level=1)
        h = st["hidden"]
        h["location_graph"]["start"]["type"] = "forest"
        result = _handle_movement_failure(
            "north", "fail_bad", h, st["visible"],
            _seq_rng([3, 1, 1, 1]),
        )
        assert h["current_mode"] == "combat"
        assert h["combat"]["enemies"][0]["key"] == spawn.YOUNG_GOBLIN_KEY

    def test_level_two_forest_restores_normal_table(self):
        st = make_state(level=2)
        h = st["hidden"]
        h["current_node_id"] = "f1"
        h["location_graph"]["f1"] = {
            "type": "forest", "entered": True,
            "exits": {"south": "start", "north": None,
                      "east": None, "west": None},
        }
        _maybe_start_combat_on_enter(
            "forest", h, st["visible"], _seq_rng([1, 1, 1]),
        )
        assert h["pending_encounter"]["enemy_keys"] == ["goblin_shaman"]

    def test_level_two_thicket_restores_normal_ambush(self):
        st = make_state(level=2)
        started = _maybe_start_combat_on_enter(
            "thicket", st["hidden"], st["visible"],
            _seq_rng([1, 1, 1]),
        )
        assert started is not None
        key = st["hidden"]["combat"]["enemies"][0]["key"]
        assert key != spawn.YOUNG_GOBLIN_KEY
        assert key == "wolf"

    def test_level_one_empty_location_stays_empty(self):
        st = make_state(level=1)
        started = _maybe_start_combat_on_enter(
            "road", st["hidden"], st["visible"], _seq_rng([1, 1, 1]),
        )
        assert started is None
        assert st["hidden"].get("pending_encounter") is None


# ---------------------------------------------------------------------
# Level 2 reward: one club, simulated young-goblin drop
# ---------------------------------------------------------------------

class TestLevelTwoClub:
    def test_two_young_goblin_kills_grant_club(self):
        st = make_state(level=1)
        events: list[str] = []
        _award_combat_xp(
            st["visible"], st["hidden"], 2, events,
            dead_keys=[spawn.YOUNG_GOBLIN_KEY, spawn.YOUNG_GOBLIN_KEY],
        )
        assert st["visible"]["level"] == 2
        assert st["visible"]["xp"] == 10
        assert _has_club(st["visible"])
        assert any("club" in e.lower() for e in events)
        assert any("young goblin" in e.lower() for e in events)

    def test_one_kill_no_club(self):
        st = make_state(level=1)
        events: list[str] = []
        _award_combat_xp(
            st["visible"], st["hidden"], 1, events,
            dead_keys=[spawn.YOUNG_GOBLIN_KEY],
        )
        assert st["visible"]["level"] == 1
        assert not _has_club(st["visible"])
        assert events

    def test_already_level_two_no_retroactive_club(self):
        st = make_state(level=2)
        st["visible"]["xp"] = 10
        events: list[str] = []
        _award_combat_xp(
            st["visible"], st["hidden"], 1, events,
            dead_keys=[spawn.YOUNG_GOBLIN_KEY],
        )
        assert st["visible"]["level"] == 2
        assert not _has_club(st["visible"])

    def test_jump_to_level_three_grants_one_club(self):
        st = make_state(level=1)
        events: list[str] = []
        _award_combat_xp(
            st["visible"], st["hidden"], 6, events,
            dead_keys=[spawn.YOUNG_GOBLIN_KEY] * 6,
        )
        assert st["visible"]["level"] == 3
        clubs = [i for i in st["visible"]["inventory"] if i["name"] == "club"]
        assert len(clubs) == 1
        assert clubs[0]["count"] == 1

    def test_generic_text_for_non_young_goblin_kill(self):
        st = make_state(level=1)
        events: list[str] = []
        _award_combat_xp(
            st["visible"], st["hidden"], 2, events,
            dead_keys=["wolf", "wolf"],
        )
        assert _has_club(st["visible"])
        assert any("club" in e.lower() for e in events)

    def test_club_is_a_normal_sellable_item(self):
        st = make_state(level=1)
        events: list[str] = []
        _award_combat_xp(
            st["visible"], st["hidden"], 2, events,
            dead_keys=[spawn.YOUNG_GOBLIN_KEY, spawn.YOUNG_GOBLIN_KEY],
        )
        assert economy.has_item(st["visible"], "club") is True
        assert economy.remove_item(st["visible"], "club") is True
        assert economy.has_item(st["visible"], "club") is False


class TestClubThroughCombat:
    def _run(self, enemy_keys, dead_keys):
        st = make_state(level=1, mode="combat")
        live = start_combat([enemy_keys[0]], "burt")
        st["hidden"]["combat"] = live.to_dict()
        fake = _FakeCombatResult(
            burt=BurtStats(hp=10, hp_max=10, mp=3, mp_max=3),
            outcome="burt_won",
            combat_state=_dead_combat(dead_keys),
            events_llm=["Done."],
        )
        with patch("burt.loop.combat.resolve_round", return_value=fake), \
             patch("burt.loop.loot.collect_loot", return_value=LootDrop()):
            result = execute_action(
                Action(
                    "attack_" + live.enemies[0].id, "Attack",
                    target_id=live.enemies[0].id,
                ),
                st, rng=lambda: 4,
            )
        return st, result

    def test_combat_victory_grants_club(self):
        key = spawn.YOUNG_GOBLIN_KEY
        st, result = self._run([key], [key, key])
        assert st["visible"]["level"] == 2
        assert _has_club(st["visible"])
        assert any("club" in e.lower() for e in result.events)
        # The simulated drop must not be followed by "Loot: nothing."
        assert "Loot: nothing." not in result.events

