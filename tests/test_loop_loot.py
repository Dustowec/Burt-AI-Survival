"""Tests for loot collection after combat victory (loop._execute_combat).

KNOWN ISSUES #1 from HANDOFF-12: loot after combat was not collected.
"""

from unittest.mock import patch

from burt.combat import start_combat, BurtStats
from burt.loot import LootDrop
from burt.loop import Action, execute_action


def make_state(mode="exploring"):
    """Minimal state for combat tests."""
    from burt import world
    return {
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 5, "date": "1 day",
            "effects": [],
            "location": {
                "name": "Crossroads",
                "exits": ["north", "east", "south", "west"],
            },
            "inventory": [
                {"name": "bread", "count": 2},
                {"name": "water", "count": 1},
            ],
            "wallet": {"coin": 50},
            "skills_visible": [],
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
    """Stand-in for combat.resolve_round return value."""

    def __init__(self, burt, events_llm, outcome, combat_state):
        self.burt = burt
        self.events_llm = events_llm
        self.outcome = outcome
        self.combat = combat_state


def _make_victory_result(combat_state):
    return _FakeCombatResult(
        burt=BurtStats(
            hp=10, hp_max=10, mp=3, mp_max=3, spells_available=False,
        ),
        events_llm=["Enemy defeated."],
        outcome="burt_won",
        combat_state=combat_state,
    )


def _setup_victory_state(enemy_keys=None):
    """Return (state, enemy_id, cs_dead)."""
    if enemy_keys is None:
        enemy_keys = ["wolf"]
    st = make_state("combat")
    cs_live = start_combat(enemy_keys, "burt")
    enemy_id = cs_live.enemies[0].id
    st["hidden"]["combat"] = cs_live.to_dict()

    cs_dead = start_combat(enemy_keys, "burt")
    for e in cs_dead.enemies:
        e.alive = False
    return st, enemy_id, cs_dead


def test_loot_collected_on_victory():
    st, enemy_id, cs_dead = _setup_victory_state(["wolf"])
    fake = _make_victory_result(cs_dead)
    fake_drop = LootDrop(
        items=[{"name": "wolf_pelt", "count": 1}], coins=7,
    )

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot",
               return_value=fake_drop) as mock_collect:
        result = execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    assert mock_collect.called
    names = [i["name"] for i in st["visible"]["inventory"]]
    assert "wolf_pelt" in names
    assert st["visible"]["wallet"]["coin"] == 57
    assert any("Loot:" in e for e in result.events)


def test_collect_loot_called_with_enemy_keys_and_rolls():
    st, enemy_id, cs_dead = _setup_victory_state(["wolf"])
    fake = _make_victory_result(cs_dead)

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot",
               return_value=LootDrop()) as mock_collect:
        execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    enemy_keys, rolls = mock_collect.call_args[0]
    assert enemy_keys == ["wolf"]
    assert rolls == [4]


def test_loot_from_multiple_dead_enemies():
    st, enemy_id, cs_dead = _setup_victory_state(["wolf", "goblin"])
    fake = _make_victory_result(cs_dead)
    fake_drop = LootDrop(
        items=[
            {"name": "pelt", "count": 1},
            {"name": "goblin_dagger", "count": 1},
        ],
        coins=0,
    )

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot",
               return_value=fake_drop) as mock_collect:
        execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    enemy_keys, rolls = mock_collect.call_args[0]
    assert set(enemy_keys) == {"wolf", "goblin"}
    assert len(rolls) == 2


def test_loot_merges_with_existing_inventory():
    st, enemy_id, cs_dead = _setup_victory_state(["wolf"])
    st["visible"]["inventory"] = [{"name": "wolf_pelt", "count": 2}]
    fake = _make_victory_result(cs_dead)
    fake_drop = LootDrop(items=[{"name": "wolf_pelt", "count": 1}])

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot", return_value=fake_drop):
        execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    assert st["visible"]["inventory"] == [
        {"name": "wolf_pelt", "count": 3},
    ]


def test_no_loot_on_ongoing_combat():
    st = make_state("combat")
    cs = start_combat(["wolf"], "burt")
    enemy_id = cs.enemies[0].id
    st["hidden"]["combat"] = cs.to_dict()

    fake = _FakeCombatResult(
        burt=BurtStats(
            hp=10, hp_max=10, mp=3, mp_max=3, spells_available=False,
        ),
        events_llm=["Round continues."],
        outcome="ongoing",
        combat_state=cs,
    )

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot") as mock_collect:
        execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    assert not mock_collect.called


def test_no_loot_on_death():
    st = make_state("combat")
    cs = start_combat(["wolf"], "burt")
    enemy_id = cs.enemies[0].id
    st["hidden"]["combat"] = cs.to_dict()

    fake = _FakeCombatResult(
        burt=BurtStats(
            hp=0, hp_max=10, mp=0, mp_max=3, spells_available=False,
        ),
        events_llm=["You died."],
        outcome="burt_died",
        combat_state=cs,
    )

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot") as mock_collect:
        result = execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    assert not mock_collect.called
    assert result.game_over is True


def test_empty_drop_adds_nothing_message():
    st, enemy_id, cs_dead = _setup_victory_state(["wolf"])
    fake = _make_victory_result(cs_dead)

    with patch("burt.loop.combat.resolve_round", return_value=fake), \
         patch("burt.loop.loot.collect_loot",
               return_value=LootDrop()):
        result = execute_action(
            Action(f"attack_{enemy_id}", "Attack", target_id=enemy_id),
            st, rng=lambda: 4,
        )

    assert any("Loot: nothing" in e for e in result.events)
