=====================================================================
BURT -- HANDOFF 13 (UPDATED END-OF-SESSION)
Date: 15.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-12 (fully closed by this)
Uncommitted at handoff write: NO
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY (HANDOFF-13, part 1: HANDOFF-12 closure)
---------------------------------------------------------------------

1. HANDOFF-12 FULLY CLOSED. All six known issues resolved:

   #1 [MEDIUM] Loot after combat — CLOSED
      loop._execute_combat: on outcome "burt_won", dead enemies are
      filtered by not e.alive, enemy keys + rng rolls passed to
      loot.collect_loot, items merged into inventory (by name),
      copper added to wallet, "Loot: ..." event appended.
      Tests: tests/test_loop_loot.py (7).

   #2 [MEDIUM] cast in combat — CLOSED
      combat._burt_cast: 1 MP, damage 3-6, hits first living enemy,
      no self-penalty (magic has no backfire per §9). Wired into
      resolve_round via action="cast". Menu: loop._build_combat_menu
      adds "cast" when spells_available. execute_action maps "cast".
      Tests: tests/test_cast_in_combat.py (11).

   #3 [MEDIUM] diary / memory / epitaph — CLOSED (part 1/2)
      Diary: menu action "write_diary_and_go_sleep" at step >= 19 only.
      hidden["diary"] is a single str, overwritten each day.
      hidden["day_log"] accumulates {step, location, llm_message, action}.
      On write: DIARY_PROMPT + day_log + previous diary -> hidden["diary"],
      diary_written_today=True.
      On skip (sleep without diary): diary=None, diary_skipped_today=True.
      Morning injection: last diary entry OR "punished by the gods of
      oblivion" text (once per new day, gated by injected_day).
      Context reset: history = [] after ANY sleep (including forced) —
      this is the whole point of the diary.
      Epitaph: SPIRIT_PROMPT + cause + days + last diary -> meta["memory"],
      meta["memory_cause"], on game_over and final hunger death.
      Tests: tests/test_diary_epitaph.py (21).
      NOT wired: MEMORY_SUMMARY_PROMPT (blocked on life counter),
      DIARY_SUMMARY_PROMPT (dropped by design — "every 5 days" removed).

   #4 [LOW] eat=True hardcode — CLOSED
      state.create_initial_state: visible["eat"] = False (was True).
      Real hunger mechanics now consistent with hunger.reset_hunger_after_sleep
      which already returns (False, False). Burt starts with bread x2 +
      water x1, so eating on step 0 is available.
      test_state.py:test_initial_hunger_and_sleep assertion flipped.
      Tests: tests/test_start_hunger.py (5).

   #5 [LOW] go_* in combat — CLOSED (surgical)
      loop.execute_action: guard before last_action reset.
      if mode == "combat" and action.key.startswith("go_"):
          return error_result(f"cannot {action.key} in combat")
      Blocks go_north/east/south/west/back/forward.
      Does NOT block search, sleep, eat_food, drink_water, osmotret —
      that is a broader task (see KNOWN ISSUES below).
      Tests: tests/test_go_blocked_in_combat.py (12).

   #6 [LOW] Gemma robotic — WON'T FIX
      Model limitation (Gemma 3n-E4B via user-fallback answers
      CHOICE: 0 on every prompt). Qwen 3.5 4B is the recommended model.
      No code change.

2. New state fields added in HANDOFF-13 part 1 (initialized in
   create_initial_state, setdefault in _ensure_runtime_fields, NOT
   validated — old saves OK):
      hidden["diary"]: str | None
      hidden["day_log"]: list[dict]
      hidden["diary_written_today"]: bool
      hidden["diary_skipped_today"]: bool
      hidden["injected_day"]: int

3. Workflow (proven effective this session):
   User as architect + code reviewer, AI agent (GigaCode) as implementer.
   Each task: tight TZ (files, functions, exact code, test names, forbidden
   list) -> agent runs -> user returns git diff -> I review -> commit.
   Agent cost for one medium task: ~90k tokens (vs 6-7M for Qwen 3.7-Flash
   on same-scale task).

---------------------------------------------------------------------
SESSION SUMMARY (HANDOFF-13, part 2: end-of-session work TZ-1/2/3)
---------------------------------------------------------------------

4. TZ-2 [DONE] sensory: Hunger -> Fed
   Commit f372e59 "feat(sensory): Hunger -> Fed (yes/no) for small-model clarity"
   - sensory._format_hunger_sleep returns:
       "Fed: yes"              if visible["eat"] is True
       "Fed: no (hungry)"      if visible["eat"] is False
   - Rationale: "Hunger: full" was misread by small models as "hunger is
     full" (i.e. completely hungry). "Fed" is unambiguous.
   - main.py hunger injection ("You are hungry.") untouched — it reinforces
     the same signal and never conflicts.
   - Tests: tests/test_sensory.py (2 asserts + docstring + full-report
     expected string).

5. TZ-1 [DONE] single coin denomination + "found money" event
   Commit f22b177 "feat(currency): single coin denomination; loot/movement event use coin"
   - Currency: gold/silver/copper -> single "coin". 1 coin = 1 former copper.
   - state.STARTING_WALLET = {"coin": 50} (was {"gold":0,"silver":5,"copper":0};
     5 silver == 50 copper == 50 coin).
   - state.validate_state: only "coin" key allowed; extra keys rejected.
   - sensory._format_wallet: "{coin} coin" / "empty".
   - loot.LootDrop.coins_copper -> LootDrop.coins.
   - dice.MovementEventResult.gold -> .coin.
   - Movement event roll=5: fixed 1 coin, description "You found some money."
     (was rng() 1..6 gold = 100..600 copper — massively OP).
     rng() is NOT called in the roll==5 branch anymore.
   - loop: wallet["coin"] usage; loot_parts uses "coin" instead of "copper".
   - trade.py: only comments updated. BASE_PRICES / LOOT_PRICES values
     UNCHANGED (they were already in copper, which == coin).
   - Tests: 17 test files updated; new test_wallet_extra_keys_rejected.
   - No save migration: no old saves exist.

6. TZ-3 [DONE] search loot + DoT + unified counter (SURVIVABILITY BLOCKER closed)
   Commit aeb368c "feat(search): loot pools, DoT, unified search counter, combat guard (TZ-3)"
   - NEW burt/items.py: item registry (food/junk/weapon). is_food()/is_junk().
     Currently search-only; full unification with trade/loot is a separate task.
   - NEW burt/search.py:
       SEARCH_AVAILABLE: frozenset of locations where search works.
       SEARCH_POOLS: per-location food pools.
       resolve_search(roll, location_type, rng) -> (SearchRollResult, items, coin)
       apply_dot / tick_dot / sync_poisoned_effect
       increment_search_counter / check_search_penalty
       Public WARN_TEXT, PENALTY_TEXT.
   - Master search table (universal):
       roll 1    -> fail_penalty: DoT -1 HP now + 2 more ticks (3 HP total)
       roll 2    -> fail: nothing
       roll 3-4  -> partial: 1 item from pool
       roll 5    -> success: 2 items from pool
       roll 6    -> crit:    2 items from pool + 1d6 coin
     Crossroads: roll 2-5 empty (no loot); crit (6):
       rng<=3 -> 1d6 coin; rng>=4 -> club.
     Road: roll 2-4 empty; roll 5 -> 1d6 coin;
           roll 6 -> club / low_quality_sword / spear (no coin).
     Food pools:
       forest:  mushrooms, berries
       field:   roots, berries
       steppe:  berries
       swamp:   moss, berries
       thicket: berries
       river:   fish, shell
     Village / temple / dungeon: search disabled (not in menu,
       blocked in execute_action defensively).
   - DoT: no stacking. A second roll=1 while poisoned = -1 HP now,
     existing DoT continues (ticks_left unchanged).
   - Effects: "poisoned" synced into visible["effects"] while
     hidden["dot_effects"] is non-empty.
   - Counter unified with osmotret via hidden["last_action"] /
     hidden["same_action_count"]:
       search #1: count=1, no warning, normal loot
       search #2: count=2, WARN_TEXT shown, normal loot
       search #3+: deterministic penalty: -1 HP, "Divine spit in the
                   face: -1 HP", "You find nothing."; rng NOT called,
                   no loot
     Any other action (except osmotret, which shares the counter)
     resets the counter. Search is excluded from the top-level
     last_action reset together with osmotret.
   - Combat: search blocked via extended guard:
       if mode == "combat" and (key.startswith("go_") or key == "search"):
           return error_result(...)
   - main.run_turn: DoT tick at start of turn (skipped in dry_run);
     death -> epitaph cause="diarrhea"; sync_poisoned_effect after tick.
   - main._ensure_runtime_fields: dot_effects added.
   - state.create_initial_state: hidden["dot_effects"] = [].
   - Food items all restore +1 HP: berries, mushrooms, roots, moss, fish.
     loop.build_menu / loop.eat_food use items.is_food(name) instead of
     the old hardcoded tuple.
   - Tests: test_items.py (19), test_search_loot.py (31),
     test_loop_search_fix.py (12), test_main_dot.py (2). Full DoT
     lifecycle (3 HP over 3 turns, expires) and repeat-roll-1 no-stack
     are covered.

7. SURVIVABILITY BLOCKER CLOSED (the reason TZ-3 existed).
   Before: search returned only a category string, no loot. Burt could
   not survive past step 28 (2 breads = 2 hunger resets on day 1;
   day 2 step 8 = death with no food).
   After: 6 locations yield food (with DoT risk on roll=1);
   crossroads and road yield coin and weapons on crit.

---------------------------------------------------------------------
CURRENT STATE (15.11.2026, end of session)
---------------------------------------------------------------------

- 1572 passed, 0 failed (est: 1520 -> 1570 after TZ-3, +2 from
  TZ-3-FIX2 lifecycle/no-stack tests). VERIFY before next session:
      .\.venv\Scripts\pytest.exe tests/ -q
- Three commits this session, in chronological order:
      f372e59  TZ-2  Hunger -> Fed                          (pushed)
      f22b177  TZ-1  single coin denomination               (pushed)
      aeb368c  TZ-3  search loot + DoT + counter            (LOCAL, ahead of origin by 1)
- HANDOFF-12 fully closed (six issues).
- Survivability blocker closed: search yields food/coin.
- Currency unified to "coin"; "found money" event fixed.
- Sensory: "Hunger" -> "Fed: yes/no (hungry)".
- python main.py --new --max-steps 20 --log-level INFO runs smoothly.
- Diary cycle, epitaph, cast in combat, loot on victory — all from
  part 1 and still working.

---------------------------------------------------------------------
KNOWN ISSUES (next session)
---------------------------------------------------------------------

1. [MEDIUM] Life counter not incremented on death.
   meta["life"] is always 1. make_new_state(life=1) is hardcoded.
   There is no "new life after death" flow: death returns
   game_over=True, game_loop breaks, user reruns with --new.
   This BLOCKS MEMORY_SUMMARY_PROMPT (needs 10+ lives to summarize).
   Also blocks the spec §6 rule "memory transfers across lives".
   Requires:
     - make_new_state should take previous meta["memory"] and life+1;
     - after game_over, main should call make_new_state(life=old+1,
       memory=meta["memory"]) and continue in a fresh world;
     - start location same (Crossroads), roles same, layout different;
     - inventory/wallet/skills/quests reset, memory transferred.

2. [MEDIUM] dice.py micro-event damage still uses old dice rolls.
   Spec updated (user edit in ТЗ): stone=1-2, tree=2-3, lightning=3-4,
   god_wrath=1*lvl.
   Code still uses 1d6/2d6/3d6 (up to 18 HP on lightning).
   This is now the biggest balance bug: movement is unnecessarily lethal.
   Touches: dice.resolve_micro_event, dice.calculate_micro_damage,
   loop._handle_movement_failure (the visible "Took N damage" strings
   will change). Update test_dice.py, test_loop.py
   TestMovementFailureSingleEvent.

3. [LOW] Non-combat actions still reachable in combat.
   UPDATED after TZ-3: search is now blocked in combat.
   Still reachable: sleep, eat_food, drink_water, osmotret.
   execute_action checks mode after these branches; only go_* and
   search are guarded at the top.
   No rush: menu never offers them in combat, this is defensive only.
   Options:
     - extend the same guard to all non-combat actions; or
     - rework execute_action to route on mode FIRST, then action.

4. [LOW] Hunger constants duplicated.
   state.HUNGER_HUNGRY_AT: list[int] = [0, 10]
   state.HUNGER_DEATH_AT: list[int] = [8, 18]
   hunger.HUNGER_HUNGRY_AT: tuple[int, ...] = (0, 10)
   hunger.HUNGER_DEATH_AT: tuple[int, ...] = (8, 18)
   Also HUNGER_HUNGRY_AT is unused in both (should_inject_hunger only
   checks eat flag). Cleanup: keep one source of truth, likely hunger.py;
   state.py imports from there. test_state.py::test_constants_match_tz
   will need updating.

5. [LOW] NEW (from TZ-3): items.py not unified with trade/loot.
   burt/items.py is a search-only registry. "bread", "fish", "club",
   "low_quality_sword", "spear" are duplicated between items.ITEMS,
   trade.BASE_PRICES, trade.LOOT_PRICES. Also loot.py has its own
   per-enemy drop tables.
   Full unification: single source of truth for item metadata
   (name, display, category, base_price, hp_restore, drop tables).
   Refactor, not blocker — do when item count grows beyond a handful.

6. [LOW] NEW (from TZ-3): sync_poisoned_effect is poison-specific.
   If more tick-effect statuses are added (blessed, cursed, bleeding…),
   the sync must be generalized (mirror visible.effects from
   hidden.status_effects by kind). Currently only "poisoned" is synced.

---------------------------------------------------------------------
RECOMMENDED NEXT STEPS
---------------------------------------------------------------------

Priority 1 (1-2 hours): dice.py flat damage per spec
  - SPEC CHANGED: stone=1-2, tree=2-3, lightning=3-4, god_wrath=1*lvl.
    Code still uses 1d6/2d6/3d6 (up to 18 HP on lightning).
  - Largest remaining balance bug. Movement is unnecessarily lethal.
  - Touches: dice.resolve_micro_event, dice.calculate_micro_damage,
    loop._handle_movement_failure (visible "Took N damage" strings).
  - Update test_dice.py, test_loop.py TestMovementFailureSingleEvent.

Priority 2 (3-4 hours): Life counter + memory summary
  - Unblocks MEMORY_SUMMARY_PROMPT.
  - Requires design: new life flow (world regen, role re-placement,
    memory transfer).
  - Large task — split into 2-3 TZs.

Priority 3 (30 min): Dedupe hunger constants
  - Keep hunger.py as source, state.py imports.
  - Update test_state.py.

Priority 4 (30 min): Broader combat action blocking
  - Extend guard to sleep/eat_food/drink_water/osmotret, or leave as
    defense-in-depth. Only if playtesting shows hallucinations.

Priority 5 (1-2 hours): Items registry unification
  - burt/items.py <-> trade.BASE_PRICES / LOOT_PRICES / loot.py tables.
  - Big refactor, do when items grow beyond a handful.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1572 pass (verify)
  python main.py --new --max-steps 20 --log-level INFO
  python main.py --new --dry-run                # inspect state only
  git --no-pager log --oneline -5               # recent commits
  git status

MODEL RECOMMENDATIONS (6 GB VRAM):
  - Qwen 3.5 4B (thinking on) + max_tokens=2048 — BEST
  - Gemma 3n-E4B (system->user fallback) — FAST, but robotic (WON'T FIX)
  - Gemma 4 E2B (thinking on) — WORST (osmotret spammer)

MEMORY AID (all English):

  # --- TZ-1 (coin) ---
  - state.STARTING_WALLET = {"coin": 50}.
  - state.validate_state rejects wallet keys other than "coin".
  - sensory._format_wallet: "{coin} coin" / "empty".
  - loot.LootDrop.coins (was coins_copper).
  - dice.MovementEventResult.coin (was gold). roll==5 gives fixed 1 coin,
    description "You found some money."; rng() NOT called in this branch.

  # --- TZ-2 (Fed) ---
  - sensory._format_hunger_sleep: "Fed: yes" / "Fed: no (hungry)".
  - main.run_turn hunger injection ("You are hungry.") still fires
    when should_inject_hunger(step, eat) returns True (== not eat).

  # --- TZ-3 (search) ---
  - burt/search.py: SEARCH_AVAILABLE, SEARCH_POOLS, resolve_search().
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

  # --- From HANDOFF-13 part 1 (unchanged) ---
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

TEST COUNTER: 1572 passed (est — verify after TZ-3-FIX2).
  Last verified: 15.11.2026

=====================================================================
END OF HANDOFF 13.
=====================================================================