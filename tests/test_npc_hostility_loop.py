"""§34/§33 NPC hostility through the loop — arrival, dialogue, combat, crime.

Contract for the blind implementation:

    a hostile resident attacks on arrival;
    the cleric serves god's wrath once, then fights;
    a murder in a dialogue wakes the guard / cleric in the same action;
    winning an NPC fight runs the same crime pipeline as dialog_attack;
    fleeing keeps the NPC alive and applies no crime;
    a killer may take K3 from the necromancer but cannot talk to the
    cleric (the killer status is an execution, not a resettable state).
"""
from __future__ import annotations

import pytest

import main
from burt import combat as combat_mod
from burt import faith
from burt import state_io
from burt.loop import Action, _arrive_at_node, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


def _rng(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(hp: int = 30, level: int = 1) -> dict:
    st = main.make_new_state(life=1)
    st["visible"]["hp"] = hp
    st["visible"]["hp_max"] = hp
    st["hidden"]["hp_raw"] = hp
    st["visible"]["level"] = level
    st["hidden"]["npcs_by_node"] = {}
    return st


def add_node(st: dict, node_type: str = "village") -> dict:
    graph = st["hidden"]["location_graph"]
    graph["n1"] = {
        "type": node_type,
        "entered": True,
        "exits": {"north": None, "east": None, "south": None, "west": None},
    }
    st["hidden"]["current_node_id"] = "n1"
    st["visible"]["location"]["name"] = "Village"
    st["visible"]["location"]["exits"] = []
    return graph


def place(
    st: dict,
    roles: list[str],
    *,
    node_id: str = "n1",
    node_type: str = "village",
) -> dict:
    graph = add_node(st, node_type)
    st["hidden"]["npcs_by_node"][node_id] = list(roles)
    st["hidden"]["npcs_here"] = list(roles)
    return graph


def node_state(
    roles: list[str],
    status: str = faith.STATUS_NEUTRAL,
    killer_from: str | None = None,
    *,
    hp: int = 30,
    level: int = 1,
    node_type: str = "village",
) -> tuple[dict, dict]:
    st = make_state(hp=hp, level=level)
    if status != faith.STATUS_NEUTRAL or killer_from is not None:
        faith.set_status(st, status, killer_from)
    graph = place(st, roles, node_type=node_type)
    return st, graph


def arrive(st: dict, graph: dict, rng=None):
    return _arrive_at_node(
        "n1", graph, st["hidden"], st["visible"], rng or _rng(1),
    )


def talk(st: dict, role: str, engine, rng=None):
    return execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=rng or _rng(1), dialogue_engine=engine,
    )


def act(st: dict, key: str, engine, rng=None):
    return execute_action(
        Action(key, key), st, rng=rng or _rng(1),
        dialogue_engine=engine,
    )


def menu(st: dict, engine) -> list:
    return build_menu(st["visible"], st, dialogue_engine=engine)


def menu_labels(st: dict, engine) -> dict[str, str]:
    return {a.key: a.label for a in menu(st, engine)}


def put_combat(st: dict, role: str, *, hp: int = 1) -> None:
    cs = combat_mod.start_combat([role], "burt")
    cs.enemies[0].hp = hp
    st["hidden"]["combat"] = cs.to_dict()
    st["hidden"]["current_mode"] = "combat"
    st["hidden"]["combat_npc_role"] = role


def active(st: dict, quest_id: str) -> dict | None:
    for entry in st["hidden"]["quests_raw"]:
        if entry.get("id") == quest_id and entry.get("status") == "active":
            return entry
    return None

class TestArrivalHostility:
    def test_killer_guard_fights_on_arrival(self):
        st, graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        _loc, started = arrive(st, graph, _rng(1))

        assert started is not None
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "guard"
        assert st["hidden"]["combat"]["enemies"][0]["key"] == "guard"
        assert "[COMBAT]" in started.events
        assert "The guard attacks!" in started.events

    def test_neutral_guard_no_fight(self):
        st, graph = node_state(["guard"])

        _loc, started = arrive(st, graph, _rng(1))

        assert started is None
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["combat_npc_role"] is None

    def test_killer_cleric_punishment_then_fight(self):
        st = make_state(hp=30, level=3)
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)
        graph = place(st, ["cleric"])

        _loc, started = arrive(st, graph, _rng(1))

        assert started is not None
        assert st["visible"]["hp"] == 27
        assert st["hidden"]["faith"]["punishment_pending"] is False
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "cleric"
        assert "The gods demand a price. You take 3 damage." in started.events
        assert "The cleric attacks!" in started.events

    def test_killer_cleric_punishment_can_kill_without_fight(self):
        st = make_state(hp=5, level=10)
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)
        graph = place(st, ["cleric"])

        _loc, started = arrive(st, graph, _rng(1))

        assert started is not None
        assert started.game_over is True
        assert st["visible"]["hp"] == 0
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["combat"] is None
        assert st["hidden"]["combat_npc_role"] is None
        assert st["hidden"]["death_cause_override"] == "god_wrath"

    def test_paladin_necromancer_fights(self):
        st, graph = node_state(["necromancer"], faith.STATUS_PALADIN)

        _loc, started = arrive(st, graph, _rng(1))

        assert started is not None
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat"]["enemies"][0]["key"] == "necromancer"
        assert "The necromancer attacks!" in started.events

    def test_heretic_cleric_fights(self):
        st, graph = node_state(["cleric"], faith.STATUS_HERETIC)

        _loc, started = arrive(st, graph, _rng(1))

        assert started is not None
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat"]["enemies"][0]["key"] == "cleric"

    def test_paladin_cleric_no_fight(self):
        st, graph = node_state(["cleric"], faith.STATUS_PALADIN)

        _loc, started = arrive(st, graph, _rng(1))

        assert started is None
        assert st["hidden"]["current_mode"] == "exploring"

    def test_heretic_necromancer_no_fight(self):
        st, graph = node_state(["necromancer"], faith.STATUS_HERETIC)

        _loc, started = arrive(st, graph, _rng(1))

        assert started is None
        assert st["hidden"]["current_mode"] == "exploring"

    def test_killer_necromancer_no_fight(self):
        st, graph = node_state(
            ["necromancer"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        _loc, started = arrive(st, graph, _rng(1))

        assert started is None
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["combat_npc_role"] is None

    @pytest.mark.parametrize("role", ["child", "peasant", "peasant_woman"])
    def test_killer_flee_roles_disappear(self, role):
        st, graph = node_state(
            [role], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        _loc, started = arrive(st, graph, _rng(1))

        assert started is None
        assert role not in st["hidden"]["npcs_here"]
        assert role not in st["hidden"]["npcs_by_node"]["n1"]

    def test_killer_child_flees_then_cleric_fights(self):
        st, graph = node_state(
            ["child", "cleric"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        _loc, started = arrive(st, graph, _rng(1))

        assert "child" not in st["hidden"]["npcs_here"]
        assert "child" not in st["hidden"]["npcs_by_node"]["n1"]
        assert started is not None
        assert st["hidden"]["combat_npc_role"] == "cleric"

    def test_killer_merchant_guard_picks_guard(self):
        st, graph = node_state(
            ["merchant", "guard"], faith.STATUS_KILLER,
            faith.STATUS_NEUTRAL,
        )

        _loc, started = arrive(st, graph, _rng(1))

        assert started is not None
        assert st["hidden"]["combat_npc_role"] == "guard"
        assert "merchant" in st["hidden"]["npcs_here"]

    def test_no_restart_when_combat_already_active(self):
        st, graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )
        st["hidden"]["combat"] = {"enemies": [], "initiative": "burt"}

        _loc, started = arrive(st, graph, _rng(1))

        assert started is None
class TestTalkToHostility:
    def test_killer_guard_talk_starts_fight(self, engine):
        st, _graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        result = talk(st, "guard", engine, _rng(1))

        assert result.game_over is False
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "guard"
        assert st["hidden"]["combat"]["enemies"][0]["key"] == "guard"

    def test_paladin_necromancer_talk_starts_fight(self, engine):
        st, _graph = node_state(["necromancer"], faith.STATUS_PALADIN)

        talk(st, "necromancer", engine, _rng(1))

        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "necromancer"

    def test_killer_cleric_talk_serves_punishment_then_fight(self, engine):
        st = make_state(hp=30, level=3)
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)
        place(st, ["cleric"])

        result = talk(st, "cleric", engine, _rng(1))

        assert st["visible"]["hp"] == 27
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "cleric"
        assert any("gods demand a price" in e.lower()
                   for e in result.events)

    def test_killer_cleric_talk_can_die_to_punishment(self, engine):
        st = make_state(hp=5, level=10)
        faith.set_status(st, faith.STATUS_PALADIN)
        faith.on_resident_killed("peasant", "peasant", st)
        place(st, ["cleric"])

        result = talk(st, "cleric", engine, _rng(1))

        assert result.game_over is True
        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["combat"] is None
        assert st["hidden"]["death_cause_override"] == "god_wrath"

    def test_neutral_guard_talk_opens_dialog(self, engine):
        st, _graph = node_state(["guard"])

        talk(st, "guard", engine)

        assert st["hidden"]["current_mode"] == "dialog"
        assert st["hidden"]["dialog_state"]["role_key"] == "guard"
        assert st["hidden"]["combat"] is None

    def test_killer_merchant_talk_is_refused(self, engine):
        st, _graph = node_state(
            ["merchant"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        result = talk(st, "merchant", engine)

        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["dialog_state"] is None
        assert result.events and result.events[0].startswith("Error:")

    def test_killer_necromancer_talk_opens_dialog(self, engine):
        st, _graph = node_state(
            ["necromancer"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        talk(st, "necromancer", engine, _rng(4))

        assert st["hidden"]["current_mode"] == "dialog"
        assert st["hidden"]["dialog_state"]["role_key"] == "necromancer"


class TestMenu:
    def test_killer_menu_approaches_hostiles(self, engine):
        st, _graph = node_state(
            ["merchant", "child", "guard", "cleric", "necromancer"],
            faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        labels = menu_labels(st, engine)

        assert labels.get("talk_to_guard") == "Approach the guard"
        assert labels.get("talk_to_cleric") == "Approach the cleric"
        assert labels.get("talk_to_necromancer") == "Talk to necromancer"
        assert "talk_to_merchant" not in labels
        assert "talk_to_child" not in labels

    def test_neutral_menu_talks_to_guard(self, engine):
        st, _graph = node_state(["guard"])

        labels = menu_labels(st, engine)

        assert labels.get("talk_to_guard") == "Talk to guard"

    def test_paladin_menu_approaches_necromancer(self, engine):
        st, _graph = node_state(["necromancer"], faith.STATUS_PALADIN)

        labels = menu_labels(st, engine)

        assert labels.get("talk_to_necromancer") == "Approach the necromancer"

    def test_heretic_menu_approaches_cleric(self, engine):
        st, _graph = node_state(["cleric"], faith.STATUS_HERETIC)

        labels = menu_labels(st, engine)

        assert labels.get("talk_to_cleric") == "Approach the cleric"

    def test_killer_can_still_reach_the_mage(self, engine):
        st, _graph = node_state(
            ["mage_event"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        labels = menu_labels(st, engine)

        assert labels.get("talk_to_mage_event") == "Talk to mage_event"

class TestMurderTriggersHostility:
    def test_guard_attacks_right_after_murder(self, engine):
        st, _graph = node_state(["merchant", "guard"])

        talk(st, "merchant", engine, _rng(4))
        result = act(st, "dialog_attack", engine, _rng(1))

        assert st["hidden"]["step"] == 1
        assert st["hidden"]["dialog_state"] is None
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "guard"
        assert st["hidden"]["combat"]["enemies"][0]["key"] == "guard"
        combined = "\n".join(result.events)
        assert "You strike the merchant down." in combined
        assert "[COMBAT]" in combined

    def test_flee_roles_run_after_murder(self, engine):
        st, _graph = node_state(["merchant", "child"])

        talk(st, "merchant", engine, _rng(4))
        result = act(st, "dialog_attack", engine, _rng(1))

        assert "child" not in st["hidden"]["npcs_here"]
        assert "child" not in st["hidden"]["npcs_by_node"]["n1"]
        assert st["hidden"]["current_mode"] == "exploring"
        assert any("runs away" in event for event in result.events)

    def test_paladin_murder_with_cleric_punishes_then_fights(self, engine):
        st = make_state(hp=30, level=3)
        faith.set_status(st, faith.STATUS_PALADIN)
        place(st, ["merchant", "cleric"])

        talk(st, "merchant", engine, _rng(4))
        result = act(st, "dialog_attack", engine, _rng(1))

        assert st["visible"]["hp"] == 27
        assert st["hidden"]["faith"]["punishment_pending"] is False
        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "cleric"
        assert any("gods demand a price" in e.lower()
                   for e in result.events)


class TestCombatVictoryCrime:
    def test_paladin_kills_necromancer(self, engine):
        st, _graph = node_state(["necromancer"], faith.STATUS_PALADIN)
        st["hidden"]["quests_raw"].append({
            "id": "elder_1", "giver_role": "elder", "status": "active",
            "chain": None, "type": "deliver", "target": None,
        })
        put_combat(st, "necromancer", hp=1)

        result = act(st, "attack_necromancer_1", engine, _rng(6))

        assert faith.get_status(st) == faith.STATUS_KILLER
        assert faith.get_killer_from(st) == faith.STATUS_PALADIN
        assert st["hidden"]["faith"]["punishment_pending"] is True
        assert st["hidden"]["faith"]["paladin_chain_blocked"] is True
        assert st["hidden"]["faith"]["heretic_chain_blocked"] is True
        assert st["hidden"]["reputation"]["necromancer"] == -10
        assert st["hidden"]["reputation_overall"] == -5
        assert st["hidden"]["quests_raw"][0]["status"] == "failed"
        assert "necromancer" not in st["hidden"]["npcs_here"]
        assert "necromancer" not in st["hidden"]["npcs_by_node"]["n1"]
        assert st["hidden"]["combat_npc_role"] is None
        assert st["hidden"]["current_mode"] == "exploring"
        combined = "\n".join(result.events)
        assert "Your open work is lost." in combined
        assert "Faith: killer" in combined

    def test_killer_kills_guard_keeps_killer_from(self, engine):
        st, _graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_HERETIC,
        )
        put_combat(st, "guard", hp=1)

        act(st, "attack_guard_1", engine, _rng(6))

        assert faith.get_status(st) == faith.STATUS_KILLER
        assert faith.get_killer_from(st) == faith.STATUS_HERETIC
        assert st["hidden"]["reputation"]["guard"] == -10
        assert st["hidden"]["reputation_overall"] == -5
        assert "guard" not in st["hidden"]["npcs_here"]
        assert st["hidden"]["combat_npc_role"] is None

    def test_heretic_kills_cleric(self, engine):
        st, _graph = node_state(["cleric"], faith.STATUS_HERETIC)
        put_combat(st, "cleric", hp=1)

        act(st, "attack_cleric_1", engine, _rng(6))

        assert faith.get_status(st) == faith.STATUS_KILLER
        assert faith.get_killer_from(st) == faith.STATUS_HERETIC
        assert st["hidden"]["faith"]["punishment_pending"] is False

    def test_flee_keeps_guard_and_applies_no_crime(self, engine):
        st, _graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )
        put_combat(st, "guard", hp=15)

        act(st, "flee", engine, _rng(5))

        assert st["hidden"]["current_mode"] == "exploring"
        assert st["hidden"]["combat"] is None
        assert st["hidden"]["combat_npc_role"] is None
        assert "guard" in st["hidden"]["npcs_here"]
        assert st["hidden"]["reputation"]["guard"] == 0
        assert st["hidden"]["reputation_overall"] == 0

    def test_kill_wolf_is_not_a_crime(self, engine):
        st = make_state()
        put_combat(st, "wolf", hp=1)
        st["hidden"]["combat_npc_role"] = None

        act(st, "attack_wolf_1", engine, _rng(6))

        assert faith.get_status(st) == faith.STATUS_NEUTRAL
        assert faith.get_killer_from(st) is None
        assert st["hidden"]["reputation"]["guard"] == 0
        assert st["hidden"]["reputation_overall"] == 0


class TestKillerK3DeadEnd:
    def test_killer_takes_k3_but_cannot_complete_it(self, engine):
        st, _graph = node_state(
            ["necromancer"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )

        talk(st, "necromancer", engine, _rng(4))
        act(st, "dialog_quest", engine, _rng(2, 4, 4))
        assert active(st, "heretic_3") is not None
        assert faith.active_chain(st) == faith.CHAIN_HERETIC
        act(st, "dialog_exit", engine)

        st["hidden"]["npcs_here"].append("cleric")
        st["hidden"]["npcs_by_node"]["n1"].append("cleric")
        labels = menu_labels(st, engine)
        assert labels.get("talk_to_cleric") == "Approach the cleric"
        assert faith.can_talk_to(st, "cleric") is False

        talk(st, "cleric", engine, _rng(1))

        assert st["hidden"]["current_mode"] == "combat"
        assert st["hidden"]["combat_npc_role"] == "cleric"
        assert st["hidden"]["dialog_state"] is None
        assert active(st, "heretic_3")["progress"] == 0
        assert faith.donate_available(st, "cleric") is False



class TestCombatStatePersistence:
    def test_combat_npc_role_survives_roundtrip(self, tmp_path):
        st, _graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
        )
        put_combat(st, "guard", hp=1)
        main._sync_meta_from_hidden(st)
        path = tmp_path / "state.json"

        state_io.save_state(path, st)
        loaded = state_io.load_state(path)

        assert loaded["hidden"]["combat_npc_role"] == "guard"
        act(loaded, "attack_guard_1", None, _rng(6))
        assert faith.get_status(loaded) == faith.STATUS_KILLER
        assert "guard" not in loaded["hidden"]["npcs_here"]

    def test_runtime_repairs_missing_combat_npc_role(self):
        st = make_state()
        del st["hidden"]["combat_npc_role"]

        main._ensure_runtime_fields(st)

        assert st["hidden"]["combat_npc_role"] is None


class TestNpcCombatDeath:
    def test_free_strike_death_clears_npc_role(self):
        st, graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
            hp=1,
        )

        _loc, started = arrive(st, graph, _rng(6))

        assert started is not None
        assert started.game_over is True
        assert st["visible"]["hp"] == 0
        assert st["hidden"]["combat"] is None
        assert st["hidden"]["combat_npc_role"] is None
        assert st["hidden"]["death_cause_override"] == "combat"

    def test_death_in_npc_round_clears_npc_role(self, engine):
        st, _graph = node_state(
            ["guard"], faith.STATUS_KILLER, faith.STATUS_NEUTRAL,
            hp=1,
        )
        put_combat(st, "guard", hp=15)

        result = act(st, "attack_guard_1", engine, _rng(1))

        assert result.game_over is True
        assert st["hidden"]["combat_npc_role"] is None
        assert st["hidden"]["current_mode"] == "exploring"

        assert st["hidden"]["combat_npc_role"] is None
