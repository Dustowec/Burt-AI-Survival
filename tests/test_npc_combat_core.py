"""NPC hostility core — §34: enemy mapping, reaction selection, dialogue gate.

These tests are the contract for the NPC-combat wiring:

    guard / cleric fight a killer;
    the necromancer fights only a paladin;
    the cleric fights a heretic;
    children and peasants flee;
    residents stop talking after a crime, except the necromancer
    (the only chain giver a killer can still reach).

Pure core: no loop, no combat rounds here.
"""
from __future__ import annotations

import pytest

from burt import faith
from burt import npc_combat
from burt.bestiary import ENEMIES
import main


def make_state() -> dict:
    return main.make_new_state(life=1)


def with_status(status: str, killer_from: str | None = None) -> dict:
    st = make_state()
    faith.set_status(st, status, killer_from)
    return st


class TestBestiaryNpcEnemies:
    def test_npc_enemies_present(self):
        assert {"guard", "cleric", "necromancer"} <= set(ENEMIES)

    def test_guard_stats(self):
        e = ENEMIES["guard"]
        assert e.hp_max == 15
        assert (e.damage_min, e.damage_max) == (2, 4)
        assert e.weapon == "sword"
        assert e.spell_damage_min is None
        assert "npc" in e.tags

    def test_cleric_stats(self):
        e = ENEMIES["cleric"]
        assert e.hp_max == 25
        assert e.mp_max == 50
        assert (e.damage_min, e.damage_max) == (1, 3)
        assert (e.spell_damage_min, e.spell_damage_max) == (5, 8)
        assert e.spell_cost == 1
        assert e.weapon == "staff"
        assert "npc" in e.tags

    def test_necromancer_stats(self):
        e = ENEMIES["necromancer"]
        assert e.hp_max == 25
        assert e.mp_max == 50
        assert (e.damage_min, e.damage_max) == (1, 3)
        assert (e.spell_damage_min, e.spell_damage_max) == (5, 8)
        assert e.spell_cost == 1
        assert e.weapon == "staff"
        assert "npc" in e.tags


class TestEnemyKey:
    @pytest.mark.parametrize("role", ["guard", "cleric", "necromancer"])
    def test_npc_roles_map_to_themselves(self, role):
        assert npc_combat.enemy_key(role) == role
        assert npc_combat.is_npc_enemy(role) is True

    @pytest.mark.parametrize(
        "role", ["merchant", "child", "peasant", "mage_event", "wolf"],
    )
    def test_other_roles_have_no_key(self, role):
        assert npc_combat.enemy_key(role) is None
        assert npc_combat.is_npc_enemy(role) is False


class TestHostileRole:
    def test_killer_guard_fights(self):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert npc_combat.hostile_role(["merchant", "guard"], st) == "guard"

    def test_killer_cleric_fights(self):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert npc_combat.hostile_role(["merchant", "cleric"], st) == "cleric"

    def test_killer_child_flees_not_fights(self):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert npc_combat.hostile_role(["child", "merchant"], st) is None

    def test_paladin_necromancer_fights(self):
        st = with_status(faith.STATUS_PALADIN)
        assert npc_combat.hostile_role(["necromancer"], st) == "necromancer"

    def test_heretic_cleric_fights(self):
        st = with_status(faith.STATUS_HERETIC)
        assert npc_combat.hostile_role(["cleric"], st) == "cleric"

    def test_neutral_nobody_fights(self):
        st = make_state()
        assert npc_combat.hostile_role(
            ["guard", "cleric", "necromancer"], st,
        ) is None

    def test_killer_from_paladin_does_not_aggro_necromancer(self):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_PALADIN)
        assert npc_combat.hostile_role(["necromancer"], st) is None

    def test_empty_list(self):
        assert npc_combat.hostile_role([], make_state()) is None

    def test_first_hostile_in_order_wins(self):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert npc_combat.hostile_role(["cleric", "guard"], st) == "cleric"

    def test_is_hostile_matches_predicate(self):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert npc_combat.is_hostile(st, "guard") is True
        assert npc_combat.is_hostile(st, "merchant") is False
        assert npc_combat.is_hostile(make_state(), "guard") is False


class TestCanTalkTo:
    def test_neutral_residents_talk(self):
        st = make_state()
        for role in ("merchant", "guard", "cleric", "necromancer"):
            assert faith.can_talk_to(st, role) is True

    @pytest.mark.parametrize(
        "role", ["merchant", "child", "guard", "cleric", "peasant"],
    )
    def test_killer_residents_do_not_talk(self, role):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert faith.can_talk_to(st, role) is False

    def test_killer_necromancer_still_talks(self):
        # The killer may take K3 from the necromancer, even though the
        # cleric step is unreachable by design (murder = execution).
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert faith.can_talk_to(st, "necromancer") is True

    @pytest.mark.parametrize("role", ["mage_event", "preacher_event"])
    def test_killer_non_residents_talk(self, role):
        st = with_status(faith.STATUS_KILLER, faith.STATUS_NEUTRAL)
        assert faith.can_talk_to(st, role) is True

    def test_paladin_necromancer_does_not_talk(self):
        st = with_status(faith.STATUS_PALADIN)
        assert faith.can_talk_to(st, "necromancer") is False
        assert faith.can_talk_to(st, "cleric") is True

    def test_heretic_cleric_does_not_talk(self):
        st = with_status(faith.STATUS_HERETIC)
        assert faith.can_talk_to(st, "cleric") is False
        assert faith.can_talk_to(st, "necromancer") is True


class TestNoTalkAfterCrime:
    def test_cleric_is_blocked(self):
        assert faith.cannot_talk_after_crime("cleric") is True

    def test_necromancer_is_not_blocked(self):
        assert faith.cannot_talk_after_crime("necromancer") is False

    def test_non_resident_is_not_blocked(self):
        assert faith.cannot_talk_after_crime("mage_event") is False
