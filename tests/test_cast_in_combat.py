"""Tests for cast action in combat (spec §9, KNOWN ISSUES #2).

Cast: 1 MP, damage 3-6, all spells identical. No target selection
in menu; hits first living enemy. No self-penalty from magic.
"""

import pytest

from burt import combat
from burt.combat import (
    BurtStats, CombatState, start_combat, resolve_round,
)
from burt.loop import Action, build_menu, execute_action


def _burt(mp=3, spells_available=True):
    return BurtStats(
        hp=10, hp_max=10, mp=mp, mp_max=3,
        spells_available=spells_available,
    )


def _state_with_combat(enemy_keys=None, mode="combat",
                       spells_available=True, mp=3):
    if enemy_keys is None:
        enemy_keys = ["wolf"]
    from burt import world
    cs = start_combat(enemy_keys, "burt")
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": mp, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [],
            "wallet": {"coin": 50},
            "skills_visible": [],
        },
        "hidden": {
            "current_mode": mode,
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": mp,
            "spells": {
                "element": "fire" if spells_available else None,
                "alignment": None,
            },
            # §9: a staff and a found teacher are the other two conditions.
            "has_staff": spells_available,
            "teacher_found": spells_available,
            "step": 0, "day": 1,
            "combat": cs.to_dict() if mode == "combat" else None,
        },
    }


# ─── _burt_cast unit tests ─────────────────────────────────


class TestBurtCast:
    def test_cast_costs_one_mp(self):
        cs = start_combat(["wolf"], "burt")
        burt = _burt(mp=3)
        result = combat._burt_cast(
            cs, burt, rng=lambda: 6, events_llm=[], events_tech=[],
        )
        assert result.mp == 2

    def test_cast_deals_damage_on_hit(self):
        cs = start_combat(["wolf"], "burt")
        enemy = cs.enemies[0]
        hp_before = enemy.hp
        burt = _burt(mp=3)
        combat._burt_cast(
            cs, burt, rng=lambda: 6, events_llm=[], events_tech=[],
        )
        assert enemy.hp < hp_before

    def test_cast_kills_enemy(self):
        cs = start_combat(["wolf"], "burt")
        enemy = cs.enemies[0]
        enemy.hp = 1
        burt = _burt(mp=3)
        events_llm = []
        combat._burt_cast(
            cs, burt, rng=lambda: 6,
            events_llm=events_llm, events_tech=[],
        )
        assert enemy.alive is False
        assert any("kills" in e.lower() for e in events_llm)

    def test_cast_raises_without_spells(self):
        cs = start_combat(["wolf"], "burt")
        burt = _burt(mp=3, spells_available=False)
        with pytest.raises(ValueError):
            combat._burt_cast(
                cs, burt, rng=lambda: 6, events_llm=[], events_tech=[],
            )

    def test_cast_raises_without_mp(self):
        cs = start_combat(["wolf"], "burt")
        burt = _burt(mp=0)
        with pytest.raises(ValueError):
            combat._burt_cast(
                cs, burt, rng=lambda: 6, events_llm=[], events_tech=[],
            )


# ─── resolve_round with action="cast" ─────────────────────


class TestResolveRoundCast:
    def test_cast_reduces_burt_mp(self):
        cs = start_combat(["wolf"], "burt")
        burt = _burt(mp=3)
        result = resolve_round(
            cs, burt, "cast", None, rng=lambda: 6,
        )
        assert result.burt.mp == 2

    def test_cast_adds_event_llm(self):
        cs = start_combat(["wolf"], "burt")
        burt = _burt(mp=3)
        result = resolve_round(
            cs, burt, "cast", None, rng=lambda: 6,
        )
        joined = " ".join(result.events_llm).lower()
        assert "spell" in joined

    def test_cast_can_win_combat(self):
        cs = start_combat(["wolf"], "burt")
        cs.enemies[0].hp = 1
        burt = _burt(mp=3)
        result = resolve_round(
            cs, burt, "cast", None, rng=lambda: 6,
        )
        assert result.outcome == "burt_won"


# ─── Menu integration ─────────────────────────────────────


class TestCastMenu:
    def test_cast_in_menu_with_spells(self):
        st = _state_with_combat(spells_available=True)
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "cast" in keys

    def test_cast_absent_without_spells(self):
        st = _state_with_combat(spells_available=False)
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "cast" not in keys


# ─── execute_action integration ───────────────────────────


class TestCastViaExecuteAction:
    def test_cast_action_reduces_mp_and_damages_enemy(self):
        st = _state_with_combat(spells_available=True, mp=3)
        cs = CombatState.from_dict(st["hidden"]["combat"])
        # Set enemy HP high enough to survive rng=6 (damage=12)
        cs.enemies[0].hp = 15
        cs.enemies[0].hp_max = 15
        st["hidden"]["combat"] = cs.to_dict()
        enemy_hp_before = cs.enemies[0].hp
        result = execute_action(
            Action("cast", "Cast"), st, rng=lambda: 6,
        )
        assert st["visible"]["mp"] == 2
        cs_after = CombatState.from_dict(st["hidden"]["combat"])
        assert cs_after.enemies[0].hp < enemy_hp_before
        assert any("spell" in e.lower() for e in result.events)
