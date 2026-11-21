=====================================================================
BURT -- HANDOFF 24
Date: 21.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0 / new_bug.md (20.11.2026)
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-23 (day rollover / resurrection P0)
Uncommitted at handoff write: YES (§33/§34 faith core)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Task: §33/§34 faith, statuses and crimes (#10), scope A + instant
murder from the dialogue (NPC hostility deferred to the next task).

1. New pure core: burt/faith.py
   - statuses neutral / paladin / heretic / killer, killer_from;
   - paladin chain (cleric): K1 20 daggers + 2 staffs -> K2 help 5
     (closed role quests only, any quest failure resets) -> K3 donate
     all (0 coins auto) -> paladin;
   - heretic chain (necromancer): K1 10 daggers -> K2 deceive 3 NPCs
     (first roll >= 3, one try per NPC, failure -1 rep) -> K3 insult
     the cleric + donate (0 coins still needs the action) -> heretic;
   - killer skips K1-K2 and gets K3 from the necromancer;
   - strict chain completion (no 1d6 partial), the finale fails the
     parallel chain (rules §33);
   - crime: status, all active quests fail, rep -5 overall / -10 the
     victim's role, killed quest giver blocked for life (-1), paladin
     -> killer queues god's wrath (1 * level, once) and blocks the
     paladin chain; hostility() predicates for the next task.

2. State / sensory
   - visible.faith + hidden.faith, reputation_overall, old-save repair
     (faith.ensure_runtime), validate_state checks;
   - [STATE] shows "Faith: paladin|heretic|killer" (neutral hidden);
   - ROLE_NAMES += peasant_woman (13 roles) -> killing her lowers rep.

3. Chains in quests / loop
   - quests_templates.json pala_1..3 / heretic_1..3 rewritten per §33;
   - quests: force give for chains, chain-aware quest_state_for_role,
     strict completion, life block (-1) fixed in quest_can_give,
     K2 reset on quest failure, finale -> faith.on_chain_complete;
   - loop: chain issuing by cleric/necromancer, K2 lie hook (same first
     roll), K3 insult after a successful threat vs the cleric, new
     dialog_donate action (cleric only), dialog_attack (instant murder,
     one action, closes the dialogue), residents hidden after the
     crime (cleric/necromancer stay talkable until NPC hostility),
     children/peasants flee on arrival, god's wrath at the first cleric
     meeting (death cause "god_wrath").

4. Tests: 2463 -> 2534 passed (+71)
   - test_faith.py (51), test_faith_chain_loop.py (7),
     test_faith_crime.py (8), test_faith_status_sensory.py (4);
   - test_quests.py deduplicated (the first 204 lines were a shadowed
     copy), templates/strict/life-block updated;
   - test_state.py ROLE_NAMES 13; old fixtures without faith still pass.

5. Docs: known_issues #10 -> PARTIAL (hostility open), #22 partially
   fixed, README roadmap + test counter, this HANDOFF-24.

---------------------------------------------------------------------
CURRENT STATE (21.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe tests/ -q  ->  2534 passed
- No live run after this change (needs approval, max 20 steps).
- known_issues: 13 open (#10 PARTIAL), 12 closed.
- Tag: v0.9.0-BETA (includes the step-20 day rollover P0 from 2bbaa78).

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q
  .\.venv\Scripts\pytest.exe tests/test_faith.py tests/test_faith_chain_loop.py -q
  python main.py --new --max-steps 20 --log-level INFO   # approval only

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Faith (§33) ---
  # statuses: neutral / paladin / heretic / killer; [STATE] hides neutral
  # paladin: cleric K1 20 daggers + 2 staffs -> K2 5 closed quests -> K3 donate
  # heretic: necromancer K1 10 daggers -> K2 deceive 3 (roll >= 3) ->
  #          K3 insult the cleric + donate
  # killer: K1-K2 skipped, K3 from the necromancer
  # chains are strict; the finale fails the parallel chain

  # --- Crime (§34) ---
  # dialog_attack in a resident dialogue = instant kill, one action
  # killer: all quests fail, -5 overall / -10 role, giver blocked for life
  # paladin -> killer: god's wrath 1 * level at the first cleric meeting
  # children/peasants flee; residents have no dialogue (cleric/necromancer
  # stay talkable until NPC hostility exists)

  # --- Faith state ---
  # hidden.faith = {status, killer_from, chain, k2_helped, k3_insulted,
  #                 paladin_chain_blocked, heretic_chain_blocked,
  #                 punishment_pending, deceive_attempts}

TEST COUNTER: 2534 passed
  Last verified: 21.11.2026

=====================================================================
END OF HANDOFF 24.
=====================================================================
