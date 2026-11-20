"""Loop integration for §7: XP at the end of combat and dynamic TZ-10 cap."""

from unittest.mock import patch

from burt import progression
from burt.combat import BurtStats, start_combat
from burt.loop import Action, execute_action, _start_combat
from burt.loot import LootDrop


def make_state(mode="combat"):
    from burt import world
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "level": 1, "xp": 0,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [],
            "wallet": {"coin": 50},
            "skills_visible": [],
            "state": mode,
        },
        "hidden": {
            "current_mode": mode,
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": None, "alignment": None},
            "step": 0, "day": 1,
        },
    }


class _FakeCombatResult:
    def __init__(self, burt, outcome, combat_state, events_llm=None):
        self.burt = burt
        self.events_llm = events_llm or []
        self.outcome = outcome
        self.combat = combat_state


def _dead_combat(enemy_keys):
    cs = start_combat(enemy_keys, "burt")
    for e in cs.enemies:
        e.alive = False
        e.hp = 0
    return cs


class TestAwardCombatXp:
    def test_two_kills_level_up(self):
        from burt.loop import _award_combat_xp
        st = make_state()
        events = []
        _award_combat_xp(st["visible"], st["hidden"], 2, events)
        assert st["visible"]["level"] == 2
        assert st["visible"]["xp"] == 10
        assert st["visible"]["hp_max"] == 12
        assert st["visible"]["mp_max"] == 4
        assert st["hidden"]["hp_raw"] == 12
        assert st["hidden"]["mp_raw"] == 4
        assert any("10 XP" in e for e in events)
        assert any("level 2" in e for e in events)

    def test_no_kills_no_change(self):
        from burt.loop import _award_combat_xp
        st = make_state()
        events = []
        _award_combat_xp(st["visible"], st["hidden"], 0, events)
        assert st["visible"]["xp"] == 0
        assert events == []


class TestExecuteCombatXp:
    def _run(self, outcome, enemy_keys):
        st = make_state("combat")
        live = start_combat(enemy_keys, "burt")
        st["hidden"]["combat"] = live.to_dict()
        fake = _FakeCombatResult(
            burt=BurtStats(hp=10, hp_max=10, mp=3, mp_max=3),
            outcome=outcome,
            combat_state=_dead_combat(enemy_keys),
            events_llm=["Done."],
        )
        with patch("burt.loop.combat.resolve_round", return_value=fake), \
             patch("burt.loop.loot.collect_loot",
                   return_value=LootDrop()) as mock_loot:
            result = execute_action(
                Action("attack_" + live.enemies[0].id, "Attack",
                       target_id=live.enemies[0].id),
                st, rng=lambda: 4,
            )
        return st, result

    def test_victory_awards_xp(self):
        st, result = self._run("burt_won", ["wolf", "goblin"])
        assert st["visible"]["level"] == 2
        assert st["visible"]["xp"] == 10
        assert any("10 XP" in e for e in result.events)
        assert any("level 2" in e for e in result.events)

    def test_death_awards_nothing(self):
        st, _ = self._run("burt_died", ["wolf"])
        assert st["visible"]["level"] == 1
        assert st["visible"]["xp"] == 0

    def test_flee_still_awards_for_dead_enemies(self):
        st, _ = self._run("burt_fled", ["wolf", "goblin"])
        assert st["visible"]["xp"] == 10


class TestTz10UnlocksWithLevel:
    def test_level_five_allows_pack(self):
        st = make_state()
        progression.award_kills(st["visible"], 17)   # level 5
        assert st["visible"]["level"] == 5
        _start_combat(
            ["wolf", "wolf", "wolf"], "enemy",
            st["hidden"], st["visible"], lambda: 1,
        )
        assert len(st["hidden"]["combat"]["enemies"]) == 3

    def test_level_four_still_caps(self):
        st = make_state()
        progression.award_kills(st["visible"], 10)   # level 4
        assert st["visible"]["level"] == 4
        _start_combat(
            ["wolf", "wolf", "wolf"], "enemy",
            st["hidden"], st["visible"], lambda: 1,
        )
        assert len(st["hidden"]["combat"]["enemies"]) == 1
