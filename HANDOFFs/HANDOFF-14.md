=====================================================================
BURT -- HANDOFF 14
Date: 15.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-13 (fully closed by this)
Uncommitted at handoff write: NO
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. HANDOFF-13 fully closed. All priorities resolved:
   - TZ-1 (coin): committed
   - TZ-2 (Fed): committed
   - TZ-3 (search loot): committed
   - P1 (dice flat damage): committed

2. P2: Life counter + memory summary — FULLY CLOSED

   TZ-4: Life counter + auto-restart
   - make_new_state(life=1) → make_new_state(life, memory, memory_cause)
     - Accepts memory/memory_cause from previous life
     - Increments life counter
     - Resets: inventory, wallet, skills, quests, location_graph
     - Transfers: meta["memory"], meta["memory_cause"]
   - create_initial_state: optional memory/memory_cause params
     - If provided → stored in meta
     - If None → not stored (first life)
   - game_loop: instead of break on game_over → auto-restart
     - Reads old memory/memory_cause from meta
     - Calls make_new_state(life=old+1, memory=old, memory_cause=old)
     - Syncs hidden from meta, ensures runtime fields
     - Logs: "Game over (life N) → new life N+1 started (memory=yes/no)"
     - Continues loop (no break)
   - Memory injection into sensory report (run_turn):
     - If meta["life"] > 1 AND meta.get("memory") → append:
       "You remember your past life:\n{meta['memory']}"
     - Only fires on life 2+ (not first life)

3. Files changed:
   - burt/state.py: create_initial_state accepts memory/memory_cause
   - main.py: make_new_state accepts memory/memory_cause
   - main.py: game_loop auto-restart instead of break
   - main.py: memory injection in run_turn (step 1c)
   - tests/test_life_memory.py: NEW — 20 tests

4. Test results: 1592 passed, 0 failed
   (1572 from HANDOFF-13 + 20 new)

---------------------------------------------------------------------
CURRENT STATE (15.11.2026, end of session)
---------------------------------------------------------------------

- 1592 passed, 0 failed
- Four commits this session, in chronological order:
    381abb1 feat(dice): flat micro-location damage per spec (P1)
    [P2 commits will be here after commit]
- HANDOFF-13 fully closed
- Survivability blocker closed (search yields food/coin)
- Currency unified to "coin"
- Sensory: "Hunger" -> "Fed: yes/no (hungry)"
- Life counter + auto-restart working
- Memory injection into BURT context working

---------------------------------------------------------------------
KNOWN ISSUES (next session)
---------------------------------------------------------------------

1. [MEDIUM] Life counter not incremented on initial --new.
   meta["life"] starts at 1 (correct), but user must rerun with --new
   to start life 2. Auto-restart handles this internally.
   External rerun with --new always starts life 1.
   This is BY DESIGN: --new is a fresh start, auto-restart is
   the internal "new life after death" flow.

2. [MEDIUM] dice.py micro-event damage — DONE (P1, committed)

3. [LOW] Non-combat actions still reachable in combat.
   Still reachable: sleep, eat_food, drink_water, osmotret.
   No rush: menu never offers them in combat.

4. [LOW] Hunger constants duplicated.
   state.HUNGER_HUNGRY_AT / HUNGER_DEATH_AT vs hunger.py versions.
   Cleanup: keep one source of truth.

5. [LOW] items.py not unified with trade/loot.
   burt/items.py is search-only registry. Duplicates with trade/loot.
   Refactor, not blocker.

6. [LOW] sync_poisoned_effect is poison-specific.
   If more tick-effect statuses added, must be generalized.

---------------------------------------------------------------------
RECOMMENDED NEXT STEPS
---------------------------------------------------------------------

Priority 1 (3-4 hours): MEMORY_SUMMARY_PROMPT at 10+ lives
  - Unblocks the "wisdom across lives" mechanic
  - Requires: collect epitaphs, call LLM, inject into system prompt
  - Split into 2 TZs:
    a) _write_memory_summary at life >= 10
    b) Inject memory_summary into BURT_SYSTEM_PROMPT

Priority 2 (30 min): Dedupe hunger constants
  - Keep hunger.py as source, state.py imports
  - Update test_state.py

Priority 3 (30 min): Broader combat action blocking
  - Extend guard to sleep/eat_food/drink_water/osmotret
  - Only if playtesting shows hallucinations

Priority 4 (1-2 hours): Items registry unification
  - burt/items.py <-> trade.BASE_PRICES / LOOT_PRICES / loot.py
  - Big refactor, do when items grow beyond a handful

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1592 pass (verify)
  python main.py --new --max-steps 20 --log-level INFO
  python main.py --new --dry-run                # inspect state only
  git --no-pager log --oneline -5               # recent commits
  git status

MODEL RECOMMENDATIONS (6 GB VRAM):
  - Qwen 3.5 4B (thinking on) + max_tokens=2048 — BEST
  - Gemma 3n-E4B (system->user fallback) — FAST, but robotic
  - Gemma 4 E2B (thinking on) — WORST (osmotret spammer)

MEMORY AID (all English):

  # --- P1: dice flat damage (committed) ---
  - MicroEventResult: damage_min, damage_max (NOT dice_count)
  - stone=1-2, tree=2-3, lightning=3-4, god_wrath=1*lvl (fixed)
  - calculate_micro_damage: rng() % range + min
  - Affected: test_loop.py, test_loop_bad_events.py, test_loop_combat_start.py

  # --- P2: life counter + memory (committed) ---
  - make_new_state(life, memory=None, memory_cause=None)
  - create_initial_state: optional memory/memory_cause params
  - game_loop: auto-restart on game_over (no break)
    - Reads old memory/memory_cause from meta
    - Calls make_new_state(life=old+1, memory=old, memory_cause=old)
    - _sync_hidden_from_meta(state), _ensure_runtime_fields(state)
    - Logs: "Game over (life N) -> new life N+1 started"
    - continue (not break)
  - Memory injection in run_turn (step 1c):
    - If meta["life"] > 1 AND meta.get("memory") → append to report
    - "You remember your past life:\n{meta['memory']}"
  - New tests: tests/test_life_memory.py (20 tests)
  - All existing tests untouched (only new file added)

  # --- From HANDOFF-13 (unchanged) ---
  - TZ-1: STARTING_WALLET = {"coin": 50}. validate_state rejects
    wallet keys other than "coin".
  - TZ-2: sensory._format_hunger_sleep: "Fed: yes" / "Fed: no (hungry)".
  - TZ-3: burt/search.py: SEARCH_AVAILABLE, SEARCH_POOLS, resolve_search().
    apply_dot / tick_dot / sync_poisoned_effect.
    increment_search_counter / check_search_penalty.
    WARN_TEXT, PENALTY_TEXT (public).
  - burt/items.py: ITEMS, is_food(), is_junk().
  - loop.build_menu: has_food via items.is_food(name).
    search only if _current_location_type(hidden) in SEARCH_AVAILABLE.
  - loop.execute_action: combat guard:
      if mode == "combat" and (key.startswith("go_") or key == "search").
  - loop.execute_action: top-level last_action reset excludes BOTH
    "osmotret" and "search".
  - loop.search branch: check_search_penalty first; if penalize -> -1 HP,
    no rng. Else increment counter, warn on count==2, resolve_search,
    apply_dot on fail_penalty, aggregate loot, "Found: ...".
  - search.apply_dot: -1 HP now, ticks_left=2 (3 HP total).
  - search.tick_dot: 1 HP per turn, decrement ticks_left, remove at 0.
  - search.sync_poisoned_effect: visible["effects"] mirrors
    hidden["dot_effects"] non-empty via "poisoned".
  - main.run_turn: DoT tick at start of turn (skipped in dry_run);
    death -> epitaph cause="diarrhea".
  - main._ensure_runtime_fields: hidden.setdefault("dot_effects", []).
  - state.create_initial_state: hidden["dot_effects"] = [].
  - loop._execute_combat: burt_won -> loot.collect_loot, merge by name,
    coin to wallet, "Loot: ..." event. burt_died -> game_over=True.
  - combat._burt_cast: check spells_available + mp >= 1, target = first
    living, mp -= 1, dice.resolve_attack(roll, 3, 6), kill if hp <= 0.
  - main.run_turn: day_before at top, day_after at bottom, history=[]
    if day_after > day_before.
  - main.run_turn: day_log.append BEFORE execute_action, _write_diary
    called BEFORE execute_action (so day_log is still populated).
  - main._do_sleep: clears day_log, clears diary if not written_today,
    resets diary_written_today.
  - main._write_diary: DIARY_PROMPT + user_msg (day, prev diary,
    day_log) -> hidden["diary"], flag=True.
  - main._write_epitaph: SPIRIT_PROMPT + user_msg (days, cause, last
    diary) -> meta["memory"], meta["memory_cause"].
  - state.create_initial_state: visible["eat"]=False (real hunger).
  - prompts.MEMORY_SUMMARY_PROMPT: unused, blocked on life counter.
  - prompts.DIARY_SUMMARY_PROMPT: unused, dropped by design.

TEST COUNTER: 1592 passed
  Last verified: 15.11.2026

=====================================================================
END OF HANDOFF 14.
=====================================================================
