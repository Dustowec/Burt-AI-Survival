"""§20 + §8 in combat: equipment-driven stats, mastery and strikes."""

from burt import loop
from burt import skills
from burt.combat import CombatState, start_combat, resolve_round, BurtStats
from burt.loop import Action, execute_action, _build_burt_stats


def make_state(inventory=None, skills_raw=None, element=None):
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
            "inventory": inventory or [],
            "wallet": {"coin": 50},
            "skills_visible": [],
            "state": "combat",
        },
        "hidden": {
            "current_mode": "combat",
            "current_node_id": "start",
            "location_graph": world.create_start_graph(),
            "hp_raw": 10, "mp_raw": 3,
            "spells": {"element": element, "alignment": None},
            "has_staff": element is not None,
            "teacher_found": element is not None,
            "skills_raw": skills_raw or [],
            "step": 0, "day": 1,
        },
    }


def _rng(values):
    vals = list(values)
    box = {"i": 0}

    def _roll():
        i = min(box["i"], len(vals) - 1)
        box["i"] += 1
        return vals[i]

    return _roll


class TestStatsFromEquipment:
    def test_empty_inventory_gives_fists(self):
        st = make_state()
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.weapon == "fists"
        assert (burt.damage_min, burt.damage_max) == (0, 1)
        assert burt.master == 0
        assert burt.modifier == 0

    def test_best_weapon_is_used(self):
        st = make_state(inventory=[
            {"name": "club", "count": 1},
            {"name": "ordinary_sword", "count": 1},
        ])
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.weapon == "ordinary_sword"
        assert (burt.damage_min, burt.damage_max) == (2, 4)

    def test_forbidden_weapon_is_not_used(self):
        st = make_state(inventory=[{"name": "goblin_dagger", "count": 1}])
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.weapon == "fists"

    def test_mastery_extends_range_and_roll(self):
        st = make_state(
            inventory=[{"name": "ordinary_sword", "count": 1}],
            skills_raw=[{"name": "Sword", "level": 5}],
        )
        skills.ensure_state(st["hidden"], st["visible"])
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert (burt.damage_min, burt.damage_max) == (4, 6)
        assert burt.master == 5
        assert burt.modifier == 1

    def test_cast_profile_from_magic_skill(self):
        st = make_state(
            element="fire",
            skills_raw=[{"name": "Magic", "level": 5}],
        )
        skills.ensure_state(st["hidden"], st["visible"])
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert (burt.cast_damage_min, burt.cast_damage_max) == (5, 8)
        assert burt.cast_master == 5
        assert burt.cast_modifier == 1


class TestEquipmentDamage:
    def test_club_doubles_max_on_roll_six(self):
        st = make_state(inventory=[{"name": "club", "count": 1}])
        st["hidden"]["combat"] = start_combat(["wolf"], "burt").to_dict()
        execute_action(
            Action("attack_wolf_1", "Attack", target_id="wolf_1"),
            st, rng=_rng([6, 2]),
        )
        # club max 2, roll 6 -> 4 damage; wolf 8 -> 4
        assert st["hidden"]["combat"]["enemies"][0]["hp"] == 4

    def test_forbidden_weapon_falls_back_to_fists(self):
        st = make_state(inventory=[{"name": "goblin_dagger", "count": 1}])
        st["hidden"]["combat"] = start_combat(["wolf"], "burt").to_dict()
        execute_action(
            Action("attack_wolf_1", "Attack", target_id="wolf_1"),
            st, rng=_rng([6, 2]),
        )
        # fists max 1, roll 6 -> 2 damage; wolf 8 -> 6
        assert st["hidden"]["combat"]["enemies"][0]["hp"] == 6


class TestStrikes:
    def test_attack_counts_a_strike_even_on_miss(self):
        st = make_state(inventory=[{"name": "club", "count": 1}])
        st["hidden"]["combat"] = start_combat(["wolf"], "burt").to_dict()
        execute_action(
            Action("attack_wolf_1", "Attack", target_id="wolf_1"),
            st, rng=_rng([2, 2]),
        )
        entry = st["hidden"]["skills_raw"][0]
        assert entry["name"] == "Club"
        assert entry["strikes"] == 1
        assert entry["level"] == 0

    def test_cast_counts_a_magic_strike(self):
        st = make_state(element="fire")
        st["hidden"]["combat"] = start_combat(["wolf"], "burt").to_dict()
        execute_action(Action("cast", "Cast"), st, rng=_rng([3, 2]))
        entry = st["hidden"]["skills_raw"][0]
        assert entry["name"] == "Magic"
        assert entry["strikes"] == 1

    def test_block_counts_no_strike(self):
        st = make_state(inventory=[{"name": "club", "count": 1}])
        st["hidden"]["combat"] = start_combat(["wolf"], "burt").to_dict()
        execute_action(Action("block", "Block"), st, rng=_rng([5]))
        assert st["hidden"]["skills_raw"] == []


class TestBurtActed:
    def test_free_strike_death_means_no_strike(self):
        cs = start_combat(["wolf"], "enemy")
        burt = BurtStats(hp=1, hp_max=10, damage_min=0, damage_max=1)
        result = resolve_round(cs, burt, "attack", "wolf_1", _rng([6]))
        assert result.outcome == "burt_died"
        assert result.burt_acted is False

    def test_normal_action_sets_burt_acted(self):
        cs = start_combat(["wolf"], "burt")
        burt = BurtStats(hp=10, hp_max=10, damage_min=1, damage_max=2)
        result = resolve_round(cs, burt, "attack", "wolf_1", _rng([3, 2]))
        assert result.burt_acted is True

