"""TZ-8: Ambush order — enemy free strike before Burt's turn.

Verifies the correct order of events during combat:
1. Ambush!
2. Enemy free strike
3. Burt's action
4. Enemy regular turns
5. Combat report (if ongoing)

All tests use deterministic cycling RNG for reproducibility.
"""
from itertools import cycle

import pytest

from burt import combat, loop
from burt.combat import CombatState, BurtStats, RoundResult
from burt.loop import Action, execute_action, _start_combat


# ─── Helpers ───────────────────────────────────────────────────


def _cycle_rng(values=(1, 2, 3, 4, 5, 6)):
    """Deterministic cycling RNG: repeats values indefinitely."""
    it = cycle(values)
    return lambda: next(it)


def _classify_event(text: str) -> str:
    """Classify an event string into a category.

    Categories:
    - "ambush": contains "Ambush!"
    - "enemy": contains enemy name + hit/missed (but not "You")
    - "burt": starts with "You " or contains "Your "
    - "report": contains "[COMBAT]"
    - "other": everything else
    """
    if "Ambush!" in text:
        return "ambush"
    if "[COMBAT]" in text:
        return "report"
    if text.startswith("You ") or text.startswith("Your "):
        return "burt"
    # Enemy events contain enemy name patterns like "wolf", "goblin", etc.
    # and hit/miss indicators, but NOT "You "
    if any(name in text.lower() for name in ("wolf", "goblin", "bandit",
                                               "boar", "bear", "dragon",
                                               "shaman")):
        if any(kw in text.lower() for kw in ("hit", "miss", "hurls",
                                               "breathes", "struck",
                                               "block", "fled", "dead")):
            return "enemy"
    return "other"


def _event_categories(events: list[str]) -> list[str]:
    """Map a list of events to their categories."""
    return [_classify_event(e) for e in events]


def _first_battle_event(categories: list[str]) -> str | None:
    """Return the first non-'other' category."""
    for c in categories:
        if c != "other":
            return c
    return None


# ─── Test 1: Ambush free strike before Burt action (unit) ──────


class TestAmbushFreeStrikeUnit:
    """Unit tests via combat.resolve_round."""

    def test_ambush_free_strike_before_burt_action(self):
        """First round with enemy initiative: Ambush! → enemy → Burt."""
        c = combat.start_combat(["wolf"], "enemy")
        burt = BurtStats(hp=10, hp_max=10, damage_min=1, damage_max=2)

        result = combat.resolve_round(c, burt, "attack", "wolf_1", _cycle_rng([4]))

        cats = _event_categories(result.events_llm)
        first = _first_battle_event(cats)
        assert first == "ambush", (
            f"First battle event should be 'ambush', got: {first}. "
            f"Events: {result.events_llm}"
        )

        # At least one enemy event before first Burt event
        ambush_idx = cats.index("ambush")
        burt_indices = [i for i, c in enumerate(cats) if c == "burt"]
        assert burt_indices, "Burt action event should be present"
        first_burt_idx = burt_indices[0]
        enemy_before_burt = any(
            cats[i] == "enemy" for i in range(ambush_idx + 1, first_burt_idx)
        )
        assert enemy_before_burt, (
            f"At least one enemy event should appear before Burt's action. "
            f"Cats: {cats}. Events: {result.events_llm}"
        )

    def test_burt_initiative_no_free_strike(self):
        """Player initiative: no Ambush!, Burt acts first."""
        c = combat.start_combat(["wolf"], "burt")
        burt = BurtStats(hp=10, hp_max=10, damage_min=1, damage_max=2)

        result = combat.resolve_round(c, burt, "attack", "wolf_1", _cycle_rng([4]))

        cats = _event_categories(result.events_llm)
        assert "ambush" not in cats, (
            f"Player initiative should not produce 'Ambush!'. "
            f"Events: {result.events_llm}"
        )
        first = _first_battle_event(cats)
        assert first == "burt", (
            f"First battle event should be Burt's action, got: {first}. "
            f"Events: {result.events_llm}"
        )
        # free_strike_done should be True after start with burt initiative
        assert c.free_strike_done is True


# ─── Test 2: Free strike only once (unit) ─────────────────────


class TestFreeStrikeOnceUnit:
    """Free strike happens only in the first round with enemy initiative."""

    def test_free_strike_only_once(self):
        """Round 1: Ambush! present. Round 2: no Ambush!."""
        c = combat.start_combat(["wolf"], "enemy")
        burt = BurtStats(hp=10, hp_max=10, damage_min=1, damage_max=2)

        # Round 1
        r1 = combat.resolve_round(c, burt, "attack", "wolf_1", _cycle_rng([4]))
        cats1 = _event_categories(r1.events_llm)
        assert "ambush" in cats1, (
            f"Round 1 should contain 'Ambush!'. Events: {r1.events_llm}"
        )

        # Round 2
        r2 = combat.resolve_round(c, r1.burt, "attack", "wolf_1", _cycle_rng([4]))
        cats2 = _event_categories(r2.events_llm)
        assert "ambush" not in cats2, (
            f"Round 2 should NOT contain 'Ambush!'. Events: {r2.events_llm}"
        )
        assert c.free_strike_done is True


# ─── Test 3: Integration via loop.execute_action ───────────────


class TestCombatOrderIntegration:
    """Integration tests via loop.execute_action."""

    def _make_combat_state(self, enemy_keys: list[str], initiative: str) -> dict:
        """Create a state with active combat."""
        state = {
            "visible": {
                "hp": 10, "hp_max": 10, "mp": 3, "mp_max": 3,
                "eat": True, "sleep_counter": 5, "date": "1 day",
                "effects": [],
                "location": {"name": "Thicket", "exits": []},
                "inventory": [], "wallet": {"coin": 50},
                "skills_visible": [],
            },
            "hidden": {
                "current_mode": "combat",
                "current_node_id": "start",
                "location_graph": {},
                "combat": None,
                "hp_raw": 10, "mp_raw": 3,
                "spells": {"element": None, "alignment": None},
                "step": 0, "day": 1,
            },
        }
        _start_combat(enemy_keys, initiative, state["hidden"], state["visible"], _cycle_rng([1]))
        return state

    def test_loop_execute_combat_preserves_order(self):
        """User-facing events: Burt → enemy → report (ambush was on prior step)."""
        st = self._make_combat_state(["wolf"], "enemy")
        result = execute_action(
            Action("attack_wolf_1", "Attack"), st, rng=_cycle_rng([4]),
        )

        cats = _event_categories(result.events)
        # Ambush now happens on the prior step (in _start_combat),
        # so the first battle event in this step is Burt's action.
        first = _first_battle_event(cats)
        assert first in ("burt", "enemy"), (
            f"First user event should be 'Burt' or 'enemy'. "
            f"Ambush was already resolved on the prior step. "
            f"Events: {result.events}"
        )

        # Burt event before Enemy event (new resolve_round order: Burt acts first)
        enemy_indices = [i for i, c in enumerate(cats) if c == "enemy"]
        burt_indices = [i for i, c in enumerate(cats) if c == "burt"]
        if enemy_indices and burt_indices:
            first_enemy_idx = enemy_indices[0]
            burt_before = any(
                i < first_enemy_idx for i in burt_indices
            )
            assert burt_before, (
                f"Burt event should appear before enemy in user events. "
                f"Cats: {cats}. Events: {result.events}"
            )

        # Combat report should NOT be before battle events
        report_indices = [i for i, c in enumerate(cats) if c == "report"]
        if report_indices:
            first_report_idx = report_indices[0]
            # Report should be at the end, after all battle events
            last_battle_idx = max(
                i for i, c in enumerate(cats) if c not in ("other", "report")
            )
            assert first_report_idx > last_battle_idx, (
                f"Combat report should come after all battle events. "
                f"Cats: {cats}. Events: {result.events}"
            )


# ─── Test 4: Burt death during free strike ─────────────────────


class TestAmbushDeathUnit:
    """If Burt dies during free strike, no Burt action in events."""

    def test_ambush_death_before_burt_turn(self):
        """Burt dies in free strike: no Burt action events."""
        # Burt with 1 HP, wolf deals 1-3 damage → can kill on first hit
        c = combat.start_combat(["wolf"], "enemy")
        burt = BurtStats(hp=1, hp_max=10, damage_min=1, damage_max=2)

        # Wolf attack roll=3 → min damage (1), which kills Burt
        # Then Burt attack roll=4 → mid damage (1) to wolf
        result = combat.resolve_round(c, burt, "attack", "wolf_1",
                                      _cycle_rng([3, 4]))

        cats = _event_categories(result.events_llm)
        assert "ambush" in cats, "Should have Ambush!"

        # No Burt action if Burt died during free strike
        burt_indices = [i for i, c in enumerate(cats) if c == "burt"]
        assert len(burt_indices) == 0, (
            f"No Burt action should appear if Burt died in free strike. "
            f"Cats: {cats}. Events: {result.events_llm}"
        )
        assert result.outcome == "burt_died"


# ─── Test 5: Second round after ambush — no free strike ───────


class TestSecondRoundNoFreeStrike:
    """Second round should not have Ambush! and Burt acts first."""

    def test_second_round_no_ambush(self):
        """Round 2: Burt acts, then enemies. No Ambush!."""
        c = combat.start_combat(["wolf"], "enemy")
        burt = BurtStats(hp=10, hp_max=10, damage_min=1, damage_max=2)

        # Round 1
        r1 = combat.resolve_round(c, burt, "attack", "wolf_1", _cycle_rng([4]))
        cats1 = _event_categories(r1.events_llm)
        assert "ambush" in cats1

        # Round 2
        r2 = combat.resolve_round(c, r1.burt, "attack", "wolf_1", _cycle_rng([4]))
        cats2 = _event_categories(r2.events_llm)
        assert "ambush" not in cats2, (
            f"Round 2 should not have Ambush!. Events: {r2.events_llm}"
        )
        # Burt should act before enemies in round 2
        first = _first_battle_event(cats2)
        assert first == "burt", (
            f"Round 2 first battle event should be Burt, got: {first}. "
            f"Events: {r2.events_llm}"
        )
