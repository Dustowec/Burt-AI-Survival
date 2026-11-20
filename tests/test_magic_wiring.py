"""Magic wiring — spec §9, §32, §8 (known_issues #8 / P1-8).

Three conditions for casting: staff + spell + teacher. Teachers: mage
(elements, 1d4 at spawn), cleric (light), necromancer (dark). Two spells
per life, light and dark are mutually exclusive.
"""
from __future__ import annotations

import pytest

from burt import loop, magic, npc_spawn
from burt.loop import Action, build_menu, execute_action
from burt.npc import DialogueEngine, load_replicas


ROLES = ("merchant", "elder", "blacksmith", "fisherman", "tavernkeeper",
         "cleric", "necromancer", "mage")


def _rng_seq(*values):
    seq = list(values)

    def rng():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return rng


@pytest.fixture(scope="module")
def engine():
    return DialogueEngine(load_replicas("replicas.json"))


def make_state(inventory=None, coin=50, step=5, **hidden_over):
    st = {
        "meta": {"life": 1, "day": 1, "step": step},
        "visible": {
            "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
            "eat": True, "sleep_counter": 0, "date": "1 day",
            "effects": [],
            "inventory": list(inventory or []),
            "wallet": {"coin": coin},
            "skills_visible": [],
            "location": {"name": "Temple", "exits": ["north"]},
        },
        "hidden": {
            "step": step, "day": 1,
            "current_mode": "exploring",
            "current_node_id": "start",
            "npcs_here": [],
            "npcs_by_node": {},
            "reputation": {r: 0 for r in ROLES},
            "quests_raw": [],
            "role_quest_block": {},
            "rep_applied": {},
            "has_room_tonight": False,
            "prices_by_node": {"start": 1.0},
            "price_modifier": 1.0,
            "spells": {"element": None, "alignment": None},
            "magic": {"mage_met": False, "teachers": {},
                      "loot_sold": 0, "granted": []},
            "has_staff": False,
            "teacher_found": False,
            "trained_by": [],
            "skills_raw": [],
            "pending_encounter": None,
            "encounter_revealed": False,
            "last_action": None,
            "same_action_count": 0,
            "combat": None,
            "location_graph": {
                "start": {"type": "temple", "entered": True,
                          "exits": {"north": None, "east": None,
                                    "south": None, "west": None}},
            },
        },
    }
    st["hidden"].update(hidden_over)
    return st


def train_with(st, role, engine, rng=None):
    """Leave any open dialogue, talk_to_<role>, then the Train category."""
    st["hidden"]["current_mode"] = "exploring"
    st["hidden"]["dialog_state"] = None
    st["hidden"]["npcs_here"] = [role]
    execute_action(
        Action(f"talk_to_{role}", f"Talk to {role}"), st,
        rng=_rng_seq(4, 4), dialogue_engine=engine,
    )
    return execute_action(
        Action("dialog_train", "Train"), st,
        rng=rng or _rng_seq(5, 2), dialogue_engine=engine,
    )
# ---------------------------------------------------------------------
# state plumbing
# ---------------------------------------------------------------------

class TestMagicState:
    def test_new_state_shape(self):
        st = magic.new_state()
        assert st["mage_met"] is False
        assert st["teachers"] == {}
        assert st["loot_sold"] == 0
        assert st["granted"] == []

    def test_ensure_state_repairs_old_saves(self):
        hidden = {}
        st = magic.ensure_state(hidden)
        assert hidden["magic"] is st
        assert st["mage_met"] is False

    def test_ensure_state_keeps_values(self):
        hidden = {"magic": {"mage_met": True, "teachers": {}, "loot_sold": 1}}
        st = magic.ensure_state(hidden)
        assert st["mage_met"] is True
        assert st["loot_sold"] == 1
        assert st["granted"] == []

    def test_spell_slots_ignore_garbage(self):
        hidden = {"spells": {"element": "banana", "alignment": 5}}
        assert magic.spell_slots(hidden) == (None, None)

    def test_spells_open_counts(self):
        hidden = {"spells": {"element": "fire", "alignment": None}}
        assert magic.spells_open(hidden) == 1


# ---------------------------------------------------------------------
# Cast readiness — three conditions (§9)
# ---------------------------------------------------------------------

class TestCastReady:
    def test_no_staff_no_cast(self):
        hidden = {"spells": {"element": "fire", "alignment": None},
                  "teacher_found": True}
        assert magic.cast_ready(hidden, False) is False

    def test_no_spell_no_cast(self):
        hidden = {"spells": {"element": None, "alignment": None},
                  "teacher_found": True}
        assert magic.cast_ready(hidden, True) is False

    def test_no_teacher_no_cast(self):
        hidden = {"spells": {"element": "fire", "alignment": None},
                  "teacher_found": False}
        assert magic.cast_ready(hidden, True) is False

    def test_all_three_open_cast(self):
        hidden = {"spells": {"element": None, "alignment": "light"},
                  "teacher_found": True}
        assert magic.cast_ready(hidden, True) is True


# ---------------------------------------------------------------------
# Training with a teacher (§9, §32)
# ---------------------------------------------------------------------

class TestTrainCleric:
    def test_cleric_grants_light(self, engine):
        st = make_state()
        train_with(st, "cleric", engine)
        assert st["hidden"]["spells"]["alignment"] == "light"
        assert st["hidden"]["teacher_found"] is True

    def test_cleric_counts_as_trained(self, engine):
        st = make_state()
        train_with(st, "cleric", engine)
        assert "cleric" in st["hidden"]["trained_by"]

    def test_skill_grows_and_becomes_visible(self, engine):
        st = make_state()
        train_with(st, "cleric", engine)
        assert st["hidden"]["skills_raw"] == [{"name": "Magic", "level": 1}]
        assert st["visible"]["skills_visible"] == [
            {"name": "Magic", "level": 1, "max": magic.SKILL_MAX_LEVEL},
        ]

    def test_second_training_same_teacher_is_refused(self, engine):
        st = make_state()
        train_with(st, "cleric", engine)
        result = train_with(st, "cleric", engine)
        assert st["hidden"]["spells"]["alignment"] == "light"
        assert st["hidden"]["trained_by"].count("cleric") == 1
        assert any("already taught" in e for e in result.events)


class TestTrainAlignmentLock:
    def test_dark_blocks_light(self, engine):
        st = make_state()
        train_with(st, "necromancer", engine)
        assert st["hidden"]["spells"]["alignment"] == "dark"
        result = train_with(st, "cleric", engine)
        assert st["hidden"]["spells"]["alignment"] == "dark"
        assert any("another path" in e for e in result.events)

    def test_light_blocks_dark(self, engine):
        st = make_state()
        train_with(st, "cleric", engine)
        train_with(st, "necromancer", engine)
        assert st["hidden"]["spells"]["alignment"] == "light"


class TestTrainMage:
    def _mage_state(self, element="fire"):
        st = make_state()
        st["hidden"]["magic"]["teachers"]["mage_event"] = {"element": element}
        st["hidden"]["magic"]["mage_met"] = True
        return st

    def test_mage_grants_his_element(self, engine):
        st = self._mage_state("water")
        train_with(st, "mage_event", engine)
        assert st["hidden"]["spells"]["element"] == "water"
        assert st["hidden"]["teacher_found"] is True

    def test_second_element_is_refused(self, engine):
        st = self._mage_state("water")
        train_with(st, "mage_event", engine)
        st["hidden"]["trained_by"] = []          # forget the training limit
        st["hidden"]["magic"]["teachers"]["mage_event"] = {"element": "air"}
        result = train_with(st, "mage_event", engine)
        assert st["hidden"]["spells"]["element"] == "water"
        assert any("another element" in e for e in result.events)

    def test_mage_without_element_grants_nothing(self, engine):
        st = make_state()
        result = train_with(st, "mage_event", engine)
        assert st["hidden"]["spells"]["element"] is None
        assert any("no element" in e for e in result.events)

    def test_skill_caps_at_ten(self, engine):
        st = self._mage_state("fire")
        st["hidden"]["skills_raw"] = [{"name": "Magic", "level": 9}]
        train_with(st, "mage_event", engine)
        assert st["hidden"]["skills_raw"][0]["level"] == 10
        st["hidden"]["trained_by"] = []
        train_with(st, "mage_event", engine)
        assert st["hidden"]["skills_raw"][0]["level"] == 10
# ---------------------------------------------------------------------
# Spawn of the wandering mage (§9, §32)
# ---------------------------------------------------------------------

class TestMageSpawn:
    def _hidden(self, loc="temple", role="cleric"):
        return {"npcs_here": [role], "npcs_by_node": {"n1": [role]}}

    def test_temple_spawns_mage_on_five(self):
        hidden = self._hidden()
        assert npc_spawn.maybe_add_mage(hidden, "temple", "n1", _rng_seq(5, 1)) is True
        assert hidden["npcs_here"] == ["cleric", "mage_event"]

    def test_dungeon_spawns_mage(self):
        hidden = self._hidden(role="necromancer")
        assert npc_spawn.maybe_add_mage(hidden, "dungeon", "n1", _rng_seq(6, 2)) is True
        assert "mage_event" in hidden["npcs_here"]

    def test_low_roll_gives_no_mage(self):
        hidden = self._hidden()
        assert npc_spawn.maybe_add_mage(hidden, "temple", "n1", _rng_seq(4)) is False
        assert hidden["npcs_here"] == ["cleric"]

    def test_forest_never_has_mage(self):
        hidden = {"npcs_here": ["veteran"], "npcs_by_node": {}}

        def rng():
            raise AssertionError("no die for a non-mage location")

        assert npc_spawn.maybe_add_mage(hidden, "forest", "n1", rng) is False

    def test_element_is_rolled_at_spawn(self):
        hidden = self._hidden()
        npc_spawn.maybe_add_mage(hidden, "temple", "n1", _rng_seq(5, 3))
        assert hidden["magic"]["teachers"]["mage_event"]["element"] == "earth"
        assert hidden["magic"]["mage_met"] is True

    def test_mage_appears_once_per_life(self):
        hidden = self._hidden()
        npc_spawn.maybe_add_mage(hidden, "temple", "n1", _rng_seq(5, 1))
        hidden["npcs_here"] = ["necromancer"]
        hidden["npcs_by_node"]["n2"] = ["necromancer"]

        def rng():
            raise AssertionError("mage already met, no die")

        assert npc_spawn.maybe_add_mage(hidden, "dungeon", "n2", rng) is False

    def test_spawn_is_cached_per_node(self):
        hidden = self._hidden()
        npc_spawn.maybe_add_mage(hidden, "temple", "n1", _rng_seq(5, 1))
        assert hidden["npcs_by_node"]["n1"] == ["cleric", "mage_event"]

    def test_reentry_restores_the_mage_from_cache(self):
        hidden = self._hidden()
        npc_spawn.maybe_add_mage(hidden, "temple", "n1", _rng_seq(5, 1))
        hidden["npcs_here"] = []
        npc_spawn.ensure_npcs(hidden, "temple", "n1", _rng_seq(1))
        assert hidden["npcs_here"] == ["cleric", "mage_event"]


# ---------------------------------------------------------------------
# Casting in combat (§9, §23)
# ---------------------------------------------------------------------

class TestCastInCombat:
    def _ready_state(self, with_staff=True):
        st = make_state(inventory=[{"name": "staff", "count": 1}] if with_staff else [])
        st["hidden"]["spells"] = {"element": "fire", "alignment": None}
        st["hidden"]["teacher_found"] = True
        return st

    def test_stats_report_spells_available(self):
        from burt.loop import _build_burt_stats
        st = self._ready_state()
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.spells_available is True

    def test_stats_without_staff(self):
        from burt.loop import _build_burt_stats
        st = self._ready_state(with_staff=False)
        burt = _build_burt_stats(st["visible"], st["hidden"])
        assert burt.spells_available is False

    def test_cast_appears_in_combat_menu(self):
        st = self._ready_state()
        loop._start_combat(["goblin"], "enemy", st["hidden"], st["visible"],
                           _rng_seq(1))
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "cast" in keys

    def test_cast_absent_without_magic(self):
        st = make_state()
        loop._start_combat(["goblin"], "enemy", st["hidden"], st["visible"],
                           _rng_seq(1))
        keys = [a.key for a in build_menu(st["visible"], st)]
        assert "cast" not in keys

    def test_cast_spends_mp_and_damages(self):
        st = self._ready_state()
        loop._start_combat(["goblin"], "enemy", st["hidden"], st["visible"],
                           _rng_seq(1))
        before_mp = st["visible"]["mp"]
        result = execute_action(Action("cast", "Cast"), st, rng=_rng_seq(5))
        assert st["visible"]["mp"] == before_mp - 1
        assert any("spell" in e.lower() for e in result.events)


# ---------------------------------------------------------------------
# Mage as a trader (§35 alias mage_event -> mage)
# ---------------------------------------------------------------------

class TestMageShop:
    def test_talking_to_the_mage_sets_rep_role(self, engine):
        st = make_state()
        st["hidden"]["npcs_here"] = ["mage_event"]
        execute_action(Action("talk_to_mage_event", "Talk"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        ds = st["hidden"]["dialog_state"]
        assert ds["rep_role"] == "mage"
        assert ds["shop_role"] == "mage"

    def test_mage_sells_the_staff(self, engine):
        st = make_state(coin=200)
        st["hidden"]["npcs_here"] = ["mage_event"]
        execute_action(Action("talk_to_mage_event", "Talk"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        execute_action(Action("dialog_trade", "Trade"), st,
                       rng=_rng_seq(4, 4), dialogue_engine=engine)
        assert "dialog_buy_staff" in [
            a.key for a in build_menu(st["visible"], st, dialogue_engine=engine)
        ]