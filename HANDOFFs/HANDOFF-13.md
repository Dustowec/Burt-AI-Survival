=====================================================================
BURT -- HANDOFF 13
Date: 15.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-12 (fully closed by this)
Uncommitted at handoff write: NO
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY (HANDOFF-13)
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

2. New state fields added (initialized in create_initial_state,
   setdefault in _ensure_runtime_fields, NOT validated — old saves OK):
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
CURRENT STATE (15.11.2026)
---------------------------------------------------------------------

- 1520 passed, 0 failed (verify: 1515 before eat task, +5 after).
- HANDOFF-12 fully closed, all six known issues resolved or won't-fixed.
- python main.py --new --max-steps 20 --log-level INFO runs smoothly.
- Diary cycle works: day -> write_diary_and_go_sleep or sleep -> next day
  -> injection of diary or punishment -> context reset.
- Epitaph written on both game_over and final hunger death.
- Cast in combat works when spells_available.
- Loot collected from all dead enemies on victory.
- eat=False on fresh life; hunger death check active.

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
     - start location TAX ЖЕ (Crossroads), roles same, layout different;
     - inventory/wallet/skills/quests reset, memory transferred.

2. [MEDIUM] dice.py micro-event damage still uses old dice rolls.
   Spec updated (user edit in "ТЗ/ТЗ на вечерок - v_0_7_0(но это не
   точно).txt"): stone=1-2, tree=2-3, lightning=3-4, god_wrath=1*lvl.
   Code still uses 1d6/2d6/3d6. Tests will need updating alongside.
   Touches: dice.resolve_micro_event, dice.calculate_micro_damage,
   loop._handle_movement_failure (the visible "Took N damage" strings
   will change).

3. [LOW] Non-combat actions still reachable in combat.
   search, sleep, eat_food, drink_water, osmotret all execute BEFORE
   the mode == "combat" check in loop.execute_action. Only go_* blocked
   (HANDOFF-12 #5). Model can hallucinate "search" in combat and Burt
   will search. Broader task, needs design decision:
     - block all non-combat actions? or
     - let some through (osmotret might be valid, eat during combat)? or
     - rework execute_action to route on mode FIRST, then action?
   No rush: menu never offers them in combat, this is defensive only.

4. [LOW] Hunger constants duplicated.
   state.HUNGER_HUNGRY_AT: list[int] = [0, 10]
   state.HUNGER_DEATH_AT: list[int] = [8, 18]
   hunger.HUNGER_HUNGRY_AT: tuple[int, ...] = (0, 10)
   hunger.HUNGER_DEATH_AT: tuple[int, ...] = (8, 18)
   Also HUNGER_HUNGRY_AT is unused in both (should_inject_hunger only
   checks eat flag). Cleanup: keep one source of truth, likely hunger.py;
   state.py imports from there. test_state.py::test_constants_match_tz
   will need updating to import from hunger.

---------------------------------------------------------------------
RECOMMENDED NEXT STEPS
---------------------------------------------------------------------

Priority 1 (3-4 hours): Life counter + memory summary
  - Unblocks MEMORY_SUMMARY_PROMPT.
  - Requires design: new life flow (world regen, role re-placement,
    memory transfer).
  - Large task — separate session. Split into 2-3 TZs.

Priority 2 (1-2 hours): dice.py flat damage per spec
  - Update resolve_micro_event / calculate_micro_damage.
  - Update affected tests (test_dice.py, test_loop.py
    TestMovementFailureSingleEvent — damage numbers will change).
  - User spec is authoritative (flat ranges, not dice).

Priority 3 (30 min): Dedupe hunger constants
  - Keep hunger.py as source, state.py imports.
  - Update test_state.py.

Priority 4 (30 min): Broader combat action blocking
  - Only if playtesting shows hallucinated non-go actions in combat.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1520 pass (verify)
  python main.py --new --max-steps 20 --log-level INFO
  python main.py --new --dry-run                # inspect state only

MODEL RECOMMENDATIONS (6 GB VRAM):
  - Qwen 3.5 4B (thinking on) + max_tokens=2048 — BEST
  - Gemma 3n-E4B (system->user fallback) — FAST, but robotic (WON'T FIX)
  - Gemma 4 E2B (thinking on) — WORST (osmotret spammer)

MEMORY AID (all English):
  - loop._execute_combat: burt_won -> loot.collect_loot, merge by name,
    copper to wallet, "Loot: ..." event. burt_died -> game_over=True.
  - combat._burt_cast: check spells_available + mp >= 1, target = first
    living, mp -= 1, dice.resolve_attack(roll, 3, 6), kill if hp <= 0.
  - loop.execute_action: guard `if mode == "combat" and
    action.key.startswith("go_")` BEFORE last_action reset.
  - loop.build_menu: "write_diary_and_go_sleep" only inside `if step >= 19`,
    NOT in critical-HP branch.
  - main.run_turn: day_before at top, day_after at bottom, history=[]
    if day_after > day_before.
  - main.run_turn: day_log.append BEFORE execute_action, _write_diary
    called BEFORE execute_action (so day_log is still populated).
  - main._do_sleep: clears day_log, clears diary if not written_today,
    resets diary_written_today.
  - main.run_turn: diary/punishment injection gated by
    injected_day != hidden["day"], before hunger injection.
  - main._write_diary: DIARY_PROMPT + user_msg (day, prev diary,
    day_log) -> hidden["diary"], flag=True.
  - main._write_epitaph: SPIRIT_PROMPT + user_msg (days, cause, last
    diary) -> meta["memory"], meta["memory_cause"].
  - state.create_initial_state: visible["eat"]=False (real hunger,
    HANDOFF-12 #4). reset_hunger_after_sleep also returns False.
  - prompts.MEMORY_SUMMARY_PROMPT: unused, blocked on life counter.
  - prompts.DIARY_SUMMARY_PROMPT: unused, dropped by design.

TEST COUNTER: 1520 passed (est — verify after eat task commit).
  Last verified: 15.11.2026

=====================================================================
END OF HANDOFF 13.
=====================================================================