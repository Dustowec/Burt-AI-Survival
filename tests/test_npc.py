"""
tesn_npc.py — RED tests for the NPC dialogue engine (spec «12. ДИАЛОГИ И NPC»).

Expected production module: ``npc_dialogue``.
The module is NOT implemented yet — every test here is RED: it describes the
required behaviour and must fail until the engine exists.

Expected public API of ``npc_dialogue`` (used by these tests)::

    load_replicas(path: str) -> dict
    resolve_heretic_deception(roll: int) -> bool

    class Outcome(Enum):
        FAIL = 0
        NEUTRAL = 1
        SUCCESS = 2

    class DialogueEngine:
        def __init__(self, replicas: dict): ...
        def available_categories(self, role_key: str) -> set[str]: ...
        def start(self, role_key: str, *,
                  hp: int = 10, coins: int = 100,
                  reputation_bonus: int = 0) -> "Session": ...

    class Session:
        hp, coins, is_angry, turn       # properties
        def can_exit(self) -> bool: ...
        def advance_turn(self) -> None: ...
        def set_quest_state(self, state: str) -> None: ...
        def say(self, category: str, roll: int | None = None,
                second_roll: int | None = None,
                modifier: int = 0) -> "Result": ...

    class Result:
        outcome: Outcome
        text: str
        bonus: dict | None
        hp_change: int
        coins_change: int
        became_angry: bool

Run::

    pytest tesn_npc.py -v
"""
from __future__ import annotations

import os
import pytest

# ---------------------------------------------------------------------------
# RED: this import must fail until the engine exists.
# ---------------------------------------------------------------------------
from burt.npc import (
    load_replicas,
    DialogueEngine,
    Session,
    Result,
    Outcome,
    resolve_heretic_deception,
)

REPLICAS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "replicas.json")

# All role keys from the spec/JSON.
ROLES = [
    "elder", "peasant", "peasant_woman", "blacksmith", "merchant",
    "guard", "fisherman", "child", "veteran", "cleric",
    "necromancer", "tavernkeeper",
]

# Category constants used in tests.
TRUTH, LIE, POLITE = "truth", "lie", "polite"
THREAT, CHARM, BRIBE = "threat", "charm", "bribe"
TRADE, TRAIN, QUEST = "trade", "train", "quest"
EXIT = "exit"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def replicas() -> dict:
    return load_replicas(REPLICAS_PATH)


@pytest.fixture()
def engine(replicas) -> DialogueEngine:
    return DialogueEngine(replicas)


@pytest.fixture()
def elder(engine) -> Session:
    return engine.start("elder")


# ===========================================================================
# 1. DATA INTEGRITY
# ===========================================================================
class TestReplicasData:
    def test_roles_are_present(self, replicas):
        assert set(ROLES) <= set(replicas["roles"])

    def test_events_are_present(self, replicas):
        assert {"mage_event", "preacher_event"} <= set(replicas["events"])

    def test_role_count_in_spec_range(self, replicas):
        """Spec: «10–15 РОЛЕЙ NPC»."""
        assert 10 <= len(replicas["roles"]) <= 15

    def test_every_role_has_core_pools(self, replicas):
        core = {"intro", "fail_angry", "fail", "neutral", "success"}
        for name, role in replicas["roles"].items():
            missing = core - set(role)
            assert not missing, f"role '{name}' is missing {missing}"

    def test_each_pool_has_3_to_5_variants(self, replicas):
        """Spec: «Наборы вариантов (3–5, по контексту)»."""
        def iter_pools(node, prefix=""):
            for k, v in node.items():
                if isinstance(v, list):
                    yield f"{prefix}{k}", v
                elif isinstance(v, dict):
                    yield from iter_pools(v, prefix + k + ".")

        for role_name, role in replicas["roles"].items():
            for pool_name, variants in iter_pools(role):
                assert 3 <= len(variants) <= 5, (
                    f"{role_name}.{pool_name} has {len(variants)} variants"
                )

    def test_no_role_carries_a_personal_name(self, replicas):
        """Spec: «Все безымянны»."""
        forbidden = {"name", "first_name", "last_name", "surname", "full_name"}
        for name, role in replicas["roles"].items():
            assert not (forbidden & set(role)), f"role '{name}' has a name"


# ===========================================================================
# 2. CATEGORY AVAILABILITY
# ===========================================================================
class TestCategoryAvailability:
    @pytest.mark.parametrize("role", ["child", "peasant", "peasant_woman"])
    def test_lie_is_unavailable(self, engine, role):
        """Spec: «КАТЕГОРИИ, ГДЕ ЛОЖЬ НЕДОСТУПНА: ребёнок, крестьянин, крестьянка»."""
        assert LIE not in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["elder", "blacksmith", "merchant",
                                      "fisherman", "necromancer", "tavernkeeper"])
    def test_trade_is_available(self, engine, role):
        """Spec: trade available to elders, blacksmiths, merchants, fishermen,
        mages, necromancers, tavernkeepers."""
        assert TRADE in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["guard", "peasant", "peasant_woman",
                                      "child", "veteran", "cleric"])
    def test_trade_is_unavailable(self, engine, role):
        assert TRADE not in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["guard", "elder", "veteran", "peasant"])
    def test_threat_is_available(self, engine, role):
        assert THREAT in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["peasant_woman", "child", "elder"])
    def test_charm_is_available(self, engine, role):
        assert CHARM in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["veteran", "cleric", "necromancer"])
    def test_train_is_available(self, engine, role):
        """Spec: trained roles are mage, necromancer, cleric, veteran."""
        assert TRAIN in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["peasant", "peasant_woman", "child"])
    def test_train_is_unavailable(self, engine, role):
        assert TRAIN not in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["elder", "blacksmith", "merchant", "guard",
                                      "fisherman", "veteran", "cleric",
                                      "necromancer", "tavernkeeper"])
    def test_quest_is_available(self, engine, role):
        assert QUEST in engine.available_categories(role)

    @pytest.mark.parametrize("role", ["peasant", "peasant_woman", "child"])
    def test_quest_is_unavailable(self, engine, role):
        assert QUEST not in engine.available_categories(role)

    @pytest.mark.parametrize("role", ROLES)
    def test_exit_is_always_available(self, engine, role):
        """Spec: «Выход — отдельный пункт меню, бесплатный, без кубика»."""
        assert EXIT in engine.available_categories(role)


# ===========================================================================
# 3. DICE RESOLUTION (PAIRS)
# ===========================================================================
class TestDiceResolution:
    @pytest.mark.parametrize("roll,expected", [
        (1, Outcome.FAIL), (2, Outcome.FAIL),
        (3, Outcome.NEUTRAL), (4, Outcome.NEUTRAL),
        (5, Outcome.SUCCESS), (6, Outcome.SUCCESS),
    ])
    def test_base_outcome(self, elder, roll, expected):
        # second_roll chosen so penalty/reward branch is deterministic.
        second = 5 if expected == Outcome.FAIL else 4
        assert elder.say(TRUTH, roll=roll, second_roll=second).outcome == expected

    @pytest.mark.parametrize("roll", [3, 4])
    def test_plus_one_lifts_neutral_to_success(self, elder, roll):
        assert elder.say(TRUTH, roll=roll, second_roll=4,
                         modifier=+1).outcome == Outcome.SUCCESS

    @pytest.mark.parametrize("roll", [3, 4])
    def test_minus_one_drops_neutral_to_fail(self, elder, roll):
        assert elder.say(TRUTH, roll=roll, second_roll=5,
                         modifier=-1).outcome == Outcome.FAIL

    @pytest.mark.parametrize("roll", [5, 6])
    def test_minus_one_drops_success_to_neutral(self, elder, roll):
        assert elder.say(TRUTH, roll=roll, modifier=-1).outcome == Outcome.NEUTRAL

    @pytest.mark.parametrize("roll", [1, 2])
    def test_plus_one_lifts_fail_to_neutral(self, elder, roll):
        assert elder.say(TRUTH, roll=roll, modifier=+1).outcome == Outcome.NEUTRAL

    def test_neutral_ignores_second_roll(self, elder):
        """Spec: «Второго броска нет» on neutral."""
        res = elder.say(TRUTH, roll=3, second_roll=1)
        assert res.outcome == Outcome.NEUTRAL
        assert res.bonus is None
        assert res.hp_change == 0
        assert not res.became_angry


# ===========================================================================
# 4. FAIL BRANCH
# ===========================================================================
class TestFailBranch:
    def test_fail_penalty_roll_1_to_3_costs_hp_and_angers(self, elder):
        """Spec: fail + second_roll 1–3 → −1 HP + ярость."""
        hp_before = elder.hp
        res = elder.say(TRUTH, roll=1, second_roll=2)
        assert res.outcome == Outcome.FAIL
        assert res.hp_change == -1
        assert elder.hp == hp_before - 1
        assert res.became_angry is True
        assert elder.is_angry is True

    def test_fail_penalty_roll_4_to_6_is_plain_refusal(self, elder):
        """Spec: fail + second_roll 4–6 → просто отказ, без урона и ярости."""
        hp_before = elder.hp
        res = elder.say(TRUTH, roll=1, second_roll=5)
        assert res.outcome == Outcome.FAIL
        assert res.hp_change == 0
        assert elder.hp == hp_before
        assert res.became_angry is False
        assert elder.is_angry is False

    def test_anger_uses_fail_angry_pool(self, replicas, elder):
        res = elder.say(TRUTH, roll=1, second_roll=1)
        assert res.became_angry
        assert res.text in replicas["roles"]["elder"]["fail_angry"]

    def test_plain_fail_uses_fail_pool(self, replicas, elder):
        res = elder.say(TRUTH, roll=2, second_roll=4)
        assert res.outcome == Outcome.FAIL
        assert res.text in replicas["roles"]["elder"]["fail"]


# ===========================================================================
# 5. ANGER / EXIT LOCK
# ===========================================================================
class TestAngerExitLock:
    def test_anger_closes_exit_current_turn(self, elder):
        """Spec: «выход закрыт до конца следующего хода»."""
        elder.say(TRUTH, roll=1, second_roll=1)
        assert elder.is_angry
        assert elder.can_exit() is False

    def test_anger_still_locks_next_turn(self, elder):
        elder.say(TRUTH, roll=1, second_roll=1)
        elder.advance_turn()                 # move to the "next turn"
        assert elder.can_exit() is False

    def test_exit_reopens_after_next_turn(self, elder):
        elder.say(TRUTH, roll=1, second_roll=1)
        elder.advance_turn()                 # next turn
        elder.advance_turn()                 # turn after next
        assert elder.can_exit() is True

    def test_exit_is_free_when_calm(self, elder):
        """Spec: exit is a free menu item, no dice."""
        assert elder.can_exit()
        res = elder.say(EXIT)                # no roll, no second roll
        assert res.outcome in (Outcome.SUCCESS,)
        assert res.bonus is None
        assert res.hp_change == 0


# ===========================================================================
# 6. SUCCESS BRANCH
# ===========================================================================
class TestSuccessBranch:
    def test_success_without_second_roll_has_no_bonus(self, elder):
        res = elder.say(TRUTH, roll=5)
        assert res.outcome == Outcome.SUCCESS
        assert res.bonus is None

    def test_success_second_roll_4_to_6_has_no_bonus(self, elder):
        res = elder.say(TRUTH, roll=5, second_roll=4)
        assert res.outcome == Outcome.SUCCESS
        assert res.bonus is None

    def test_success_second_roll_1_to_3_grants_bonus(self, elder):
        res = elder.say(TRUTH, roll=5, second_roll=1)
        assert res.outcome == Outcome.SUCCESS
        assert res.bonus is not None

    def test_success_text_comes_from_success_pool(self, replicas, elder):
        res = elder.say(TRUTH, roll=6, second_roll=4)
        assert res.text in replicas["roles"]["elder"]["success"]


# ===========================================================================
# 7. BONUS BY CONTEXT
# ===========================================================================
class TestBonusByContext:
    def test_trade_bonus_is_a_20_percent_discount(self, engine):
        """Spec: торговля → −20% к цене."""
        s = engine.start("merchant")
        res = s.say(TRADE, roll=5, second_roll=1)
        assert res.bonus is not None
        assert res.bonus.get("type") in {"discount", "trade_discount"}
        assert res.bonus.get("percent") == 20

    def test_quest_bonus(self, engine):
        """Spec: квест → −20% к требованию или +мелкая награда."""
        s = engine.start("elder")
        res = s.say(QUEST, roll=5, second_roll=1)
        assert res.bonus is not None
        assert res.bonus.get("type") in {"quest_discount", "quest_reward"}

    def test_bribe_bonus(self, engine):
        """Spec: подкуп → дешевле на 2 coin или согласие с первого раза."""
        s = engine.start("guard")
        res = s.say(BRIBE, roll=5, second_roll=1)
        assert res.bonus is not None
        assert res.bonus.get("type") in {"bribe_discount", "bribe_accept"}
        if res.bonus["type"] == "bribe_discount":
            assert res.bonus.get("amount") == 2

    @pytest.mark.parametrize("category", [TRUTH, POLITE, CHARM])
    def test_kind_word_bonus_is_coins_rumor_or_item(self, engine, category):
        """Spec: правда/вежливо/лесть → 2 coin подарком, слух, мелкий предмет."""
        s = engine.start("elder")
        res = s.say(category, roll=5, second_roll=1)
        assert res.bonus is not None
        assert res.bonus.get("type") in {"coins", "rumor", "item"}
        if res.bonus["type"] == "coins":
            assert res.bonus.get("amount") == 2

    def test_threat_bonus_means_npc_flinched(self, engine):
        """Spec: угроза → NPC дрогнул: выдаёт больше, чем должен."""
        s = engine.start("guard")
        res = s.say(THREAT, roll=5, second_roll=1)
        assert res.bonus is not None
        assert res.bonus.get("type") in {"extra_info", "extra_goods"}


# ===========================================================================
# 8. BONUS RULES
# ===========================================================================
class TestBonusRules:
    def test_only_one_bonus_per_dialog(self, engine):
        """Spec: «Один бонус на диалог»."""
        s = engine.start("elder")
        first = s.say(TRUTH, roll=5, second_roll=1)
        assert first.bonus is not None
        second = s.say(TRUTH, roll=5, second_roll=1)
        assert second.bonus is None

    def test_second_bonus_in_another_category_is_also_blocked(self, engine):
        s = engine.start("elder")
        s.say(TRUTH, roll=5, second_roll=1)          # consumes the one bonus
        again = s.say(POLITE, roll=5, second_roll=1)
        assert again.bonus is None

    def test_bonus_not_applicable_falls_back_to_food_or_nothing(self, engine):
        """Spec: «Если бонус неприменим — 2 мед. или ничего»."""
        s = engine.start("child")
        res = s.say(POLITE, roll=5, second_roll=1)
        if res.bonus is not None:
            assert res.bonus.get("type") in {"food", "nothing"}


# ===========================================================================
# 9. BRIBE — MONEY HANDLING
# ===========================================================================
class TestBribeMoney:
    def test_bribe_success_spends_coins(self, engine):
        s = engine.start("guard", coins=100)
        before = s.coins
        res = s.say(BRIBE, roll=5, second_roll=4)     # no bonus reward
        assert res.outcome == Outcome.SUCCESS
        assert s.coins < before
        assert res.coins_change == s.coins - before

    def test_bribe_fail_keeps_coins(self, engine):
        s = engine.start("guard", coins=100)
        before = s.coins
        res = s.say(BRIBE, roll=1, second_roll=5)     # plain refusal
        assert res.outcome == Outcome.FAIL
        assert s.coins == before

    def test_bribe_neutral_keeps_coins(self, engine):
        s = engine.start("guard", coins=100)
        before = s.coins
        res = s.say(BRIBE, roll=3)                    # neutral
        assert res.outcome == Outcome.NEUTRAL
        assert s.coins == before


# ===========================================================================
# 10. HERETIC DECEPTION (K2, §33)
# ===========================================================================
class TestHereticDeception:
    """Spec: «ОБМАН ЕРЕТИКА (К2, §33): порог успеха = roll ≥ 3.
    Второй бросок не применяется»."""

    @pytest.mark.parametrize("roll", [3, 4, 5, 6])
    def test_roll_three_or_more_succeeds(self, roll):
        assert resolve_heretic_deception(roll) is True

    @pytest.mark.parametrize("roll", [1, 2])
    def test_roll_below_three_fails(self, roll):
        assert resolve_heretic_deception(roll) is False

    def test_second_roll_is_never_applied(self, engine):
        """No reward roll for heretic deception."""
        s = engine.start("preacher_event")
        res = s.say("deception", roll=3, second_roll=1)
        assert res.outcome == Outcome.SUCCESS
        assert res.bonus is None


# ===========================================================================
# 11. TRAINING
# ===========================================================================
class TestTraining:
    @pytest.mark.parametrize("role", ["veteran", "cleric", "necromancer"])
    def test_training_is_offered(self, engine, role):
        s = engine.start(role)
        res = s.say(TRAIN, roll=5, second_roll=4)
        assert res.outcome == Outcome.SUCCESS

    def test_training_success_grants_free_skill(self, engine):
        """Spec: бонус = 1 раз за мир +1 к навыку бесплатно."""
        s = engine.start("veteran")
        res = s.say(TRAIN, roll=5, second_roll=1)
        assert res.bonus is not None
        assert res.bonus.get("type") == "skill"
        assert res.bonus.get("amount") == 1

    def test_training_used_once_per_world(self, engine):
        """Second training attempt does not grant a second skill."""
        s = engine.start("veteran")
        s.say(TRAIN, roll=5, second_roll=1)              # consumes the skill bonus
        again = s.say(TRAIN, roll=5, second_roll=1)
        # bonus already used → no second skill
        assert again.bonus is None or again.bonus.get("type") != "skill"


# ===========================================================================
# 12. QUEST
# ===========================================================================
class TestQuest:
    def test_quest_available_for_elder(self, engine):
        assert QUEST in engine.available_categories("elder")

    def test_quest_unavailable_for_child(self, engine):
        assert QUEST not in engine.available_categories("child")

    def test_quest_none_when_npc_has_no_work(self, replicas, engine):
        s = engine.start("elder")
        s.set_quest_state("none")
        res = s.say(QUEST, roll=5)
        assert res.text in replicas["roles"]["elder"]["quest_none"]

    def test_quest_give_when_work_available(self, replicas, engine):
        s = engine.start("elder")
        s.set_quest_state("available")
        res = s.say(QUEST, roll=5)
        assert res.text in replicas["roles"]["elder"]["quest_give"]

    def test_quest_already_when_in_progress(self, replicas, engine):
        s = engine.start("elder")
        s.set_quest_state("in_progress")
        res = s.say(QUEST, roll=5)
        assert res.text in replicas["roles"]["elder"]["quest_already"]


# ===========================================================================
# 13. TEXT SELECTION — BASE POOL
# ===========================================================================
class TestTextSelectionBase:
    def test_neutral_uses_neutral_pool(self, replicas, elder):
        res = elder.say(TRUTH, roll=3)
        assert res.outcome == Outcome.NEUTRAL
        assert res.text in replicas["roles"]["elder"]["neutral"]

    def test_success_bonus_uses_success_bonus_pool(self, replicas, elder):
        res = elder.say(TRUTH, roll=5, second_roll=1)
        assert res.outcome == Outcome.SUCCESS
        assert res.bonus is not None
        assert res.text in replicas["roles"]["elder"]["success_bonus"]


# ===========================================================================
# 14. TEXT SELECTION — CATEGORY-SPECIFIC POOLS
# ===========================================================================
class TestTextSelectionCategorySpecific:
    @pytest.mark.parametrize("category,pool", [
        (CHARM, "charm_fail"),
        (THREAT, "threat_fail"),
        (TRADE, "trade_fail"),
        (BRIBE, "bribe_fail"),
    ])
    def test_category_fail_uses_specific_pool(self, replicas, engine,
                                              category, pool):
        s = engine.start("elder")
        res = s.say(category, roll=1, second_roll=5)  # fail, no anger
        assert res.outcome == Outcome.FAIL
        assert res.text in replicas["roles"]["elder"][pool]

    @pytest.mark.parametrize("category,pool", [
        (CHARM, "charm_success"),
        (THREAT, "threat_success"),
        (TRADE, "trade_success"),
        (BRIBE, "bribe_success"),
    ])
    def test_category_success_uses_specific_pool(self, replicas, engine,
                                                 category, pool):
        s = engine.start("elder")
        res = s.say(category, roll=5, second_roll=4)  # success, no bonus
        assert res.outcome == Outcome.SUCCESS
        assert res.text in replicas["roles"]["elder"][pool]


# ===========================================================================
# 15. SESSION STATE
# ===========================================================================
class TestSessionState:
    def test_initial_hp_and_coins_are_preserved(self, engine):
        s = engine.start("elder", hp=7, coins=42)
        assert s.hp == 7
        assert s.coins == 42

    def test_turn_starts_at_zero(self, elder):
        assert elder.turn == 0

    def test_advance_turn_increments(self, elder):
        elder.advance_turn()
        assert elder.turn == 1

    def test_calm_session_reports_is_angry_false(self, elder):
        assert elder.is_angry is False