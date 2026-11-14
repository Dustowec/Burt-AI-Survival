=====================================================================
BURT -- HANDOFF 12
Date: 15.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-11 (superseded by this)
Uncommitted at handoff write: NO
=====================================================================

---------------------------------------------------------------------
LANGUAGE POLICY
---------------------------------------------------------------------

Game is FULLY ENGLISH (code, docstrings, UI, prompts, replicas,
quests, sensory report, combat messages, tests asserts).
Communication with user is RUSSIAN (chat, commits, docs for user).

If Cyrillic appears in source or UI — that is a BUG.

---------------------------------------------------------------------
SESSION SUMMARY (HANDOFF-12)
---------------------------------------------------------------------

1. AI Agent Workflow Integration:
   - Started using an AI coding agent (GigaCode) to implement TDD specs.
   - User acts as architect & code reviewer, Agent writes the code & tests.
   - Proved to be highly effective: Agent writes 80% boilerplate/tests, 
     Human catches edge cases and architectural flaws.

2. Movement Failure Logic Fix (Architecture):
   - OLD: On 'fail' or 'fail_bad', BOTH micro_event (lightning) AND
     bad_movement_event (trap) rolled. Resulted in double damage and 
     "log lies" (10 HP - 9 lightning - 1 trap = 0 HP, but log showed only lightning).
   - NEW (Variant A): One fail = strictly one event.
     * fail -> only micro_event.
     * fail_bad -> only bad_movement_event.
   - Fixed micro_location being skipped if combat started, preventing 
     stuck state.
   - Fixed micro_location not logged on lethal micro-event, fixing 
     cause=unknown in death log.

3. Forced Sleep Bug:
   - OLD: Forced sleep triggered at step 20 even if hidden["current_mode"] == "combat".
   - NEW: Added check `if hidden.get("current_mode") != "combat"`. 
   - Combat now freezes time correctly. If Burt wins on step 20, mode becomes 
     "exploring" and sleep triggers in the same turn.

4. Save/Load Integrity (Combat Reset):
   - OLD: Moving during combat (e.g., hallucinated `go_north`) triggered 
     _maybe_start_combat_on_enter, restarting combat, resetting free_strike_done, 
     and changing locations.
   - NEW: Added `if hidden.get("combat") is not None: return None` in 
     _maybe_start_combat_on_enter. Active combat is now preserved across save/load.

5. Sensory & Menu Cleanup:
   - Removed misleading `Sleep: 0/20` from [STATE] (sleep_counter was never 
     updated, confusing the LLM).
   - Removed SHOW_SLEEP_TIMER from config.
   - Fixed build_menu: Sleep option now checks `hidden["step"] >= 19` 
     instead of the broken sleep_counter.

6. LLM Optimization (Gemma 3n):
   - Added `_engine_rejects_system_role` global flag in llm_client.
   - If an engine throws 'roles must alternate' (Gemma), the flag is set.
   - Subsequent calls immediately use role="user", avoiding a wasted 
     failed request on every turn.

7. Tests:
   - 1425 -> 1464 passed.
   - Added TestSaveLoadIntegrity, TestForcedSleepBlockedInCombat, 
     TestMovementFailureSingleEvent, TestEngineRejectsSystemRole.
   - Removed obsolete tests for sleep_counter and SHOW_SLEEP_TIMER.

---------------------------------------------------------------------
CURRENT STATE (15.11.2026)
---------------------------------------------------------------------

- 1464 passed, 0 failed.
- `python main.py --new --max-steps 20 --log-level INFO` runs smoothly.
- Game survives to step 20, forced sleep works.
- Combat can be safely saved/loaded without resetting or losing free_strike.
- Death logs are 100% accurate (cause=lightning, cause=combat, etc.).
- Gemma 3n-E4B (with system->user fallback) and Qwen 3.5 4B both play.

---------------------------------------------------------------------
KNOWN ISSUES (next session)
---------------------------------------------------------------------

1. [MEDIUM] Loot after combat not collected.
   loop.py: _execute_combat outcome="burt_won" -> loot.collect_loot
   not called. Loot stays in enemy, not in inventory.

2. [MEDIUM] cast action in combat not implemented.
   combat.resolve_round has no action="cast".
   format_combat_report shows "cast" if spells_available.

3. [MEDIUM] diary / memory / epitaph not wired.
   DIARY_PROMPT, MEMORY_SUMMARY_PROMPT, SPIRIT_PROMPT unused in main.py.
   Need to wire them on sleep (day+1) and on death.

4. [LOW] Hardcoded eat=True on start (state.py).
   Temporary crutch from HANDOFF-10. Needs removal for real hunger mechanics.
   (should_inject_hunger is now fixed, so it's safe to remove).

5. [LOW] `go_` actions processed during combat.
   In execute_action, the `go_` handler is checked before `mode == "combat"`.
   If model hallucinates "go_north" during combat, Burt physically moves
   (though combat state is preserved). Should ignore movement in combat.

6. [LOW] Gemma 3n-E4B plays robotically (only CHOICE: 0).
   This is a model limitation when using the 'user' fallback for system prompts. 
   Qwen is the recommended model.

---------------------------------------------------------------------
RECOMMENDED NEXT STEPS
---------------------------------------------------------------------

Priority 1 (1 hour): Loot + Cast
  - Implement loot.collect_loot in loop.py on "burt_won".
  - Implement action="cast" in combat.py (if spells_available).

Priority 2 (1-2 hours): Diary / Memory / Epitaph
  - Wire DIARY_PROMPT on sleep.
  - Wire MEMORY_SUMMARY_PROMPT on 10+ lives.
  - Wire SPIRIT_PROMPT on final death.

Priority 3 (30 min): Remove hardcoded eat=True
  - state.py: eat=False on start.
  - Verify hunger inject works correctly.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1464 pass
  python main.py --new --max-steps 20 --log-level INFO
  python main.py --new --dry-run                # inspect state only

MODEL RECOMMENDATIONS (6 GB VRAM):
  - Qwen 3.5 4B (thinking on) + max_tokens=2048 — BEST
  - Gemma 3n-E4B (system->user fallback) — FAST, but robotic
  - Gemma 4 E2B (thinking on) — WORST (osmotret spammer)

MEMORY AID (all English):
  - loop._handle_movement_failure: fail = micro only, fail_bad = bad only.
  - loop._maybe_start_combat_on_enter: early return if hidden["combat"] is not None.
  - main.run_turn: forced sleep blocked if current_mode == "combat".
  - main._determine_death_cause: relies on hidden["micro_location"].
  - burt/llm_client.py: _engine_rejects_system_role flag caches Gemma behavior.
  - burt/loop.py: build_menu uses hidden["step"] for sleep availability.
  - burt/sensory.py: Sleep counter removed from [STATE].

TEST COUNTER: 1464 passed.
  Last verified: 15.11.2026

=====================================================================
END OF HANDOFF 12.
=====================================================================