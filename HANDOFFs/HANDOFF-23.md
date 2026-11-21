=====================================================================
BURT -- HANDOFF 23
Date: 21.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0 / new_bug.md (20.11.2026)
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-22 (new_bug §0-§8, last-life save)
Uncommitted at handoff write: YES (P0 day rollover fix)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

P0 -- the state stopped persisting AGAIN. This time the door was the
last step of the day + combat + death + resurrection.

1. Log analysis (Gemma 4-E4B(log_of_life_x4)_3.txt)
   - L791  step 19 attack -> step 20 + combat; forced sleep blocked
           (correct, §5: no sleep in combat)
   - L800  combat death on step 20
   - L803  epitaph written before the roll (§6 violation)
   - L804  roll 6 -> resurrection, 2 HP (flag set, state NOT saved)
   - L809-829  next step-20 turn (osmotret) ticks 20->21
   - L830-843  Failed to save state: step (21) > maximum (20)
   - L844-996  steps 21..25: EVERY save fails; on step 25 Burt dies
           again and the dice are rolled a second time that day

2. Root causes
   - sleep.is_forced_sleep required exactly step 20; the 20->21 tick
     left the day open forever and step overran DAY_STEPS;
   - game_loop saved BEFORE the resurrection branch, so a dead state
     could stay on disk;
   - hidden["resurrection_used_today"] was written but never read.

3. Fixes
   - burt/sleep.py: is_forced_sleep -> step >= SLEEP_FORCED_AT (20);
     docstring explains the transitional tick;
   - main.run_turn: logs the real step; when forced sleep is blocked by
     combat and step > DAY_STEPS, the step is clamped to DAY_STEPS
     (a step-20 fight can no longer corrupt the save; the day wraps on
     the turn the fight ends);
   - main.run_turn death paths (diarrhea / combat / hunger): meta is
     synced before the return; death_cause travels in TurnResult;
   - main.game_loop: one mercy per day (the flag is read, no roll on a
     second death); state is saved AFTER the resurrection / new life;
     the epitaph is written only on a failed roll, inside try/except so
     an LLM failure does not kill the loop;
   - TurnResult.death_cause field.

4. Tests
   - tests/test_resurrection_day_end.py (new, 4 mock tests: log replay,
     save right after the resurrection, one mercy per day, step clamp
     while a step-20 fight is ongoing);
   - tests/test_sleep.py: is_forced_sleep(21) is True;
   - tests/test_diary_epitaph.py: run_turn never writes the epitaph;
   - test_main_lives / test_state_persistence_lives / test_life_memory:
     mock _write_epitaph (it moved out of run_turn).

5. Docs
   - known_issues.md: closed "day rollover after a resurrection",
     #21 DAY_STEPS note, tests 2463;
   - README test counter 2463;
   - this HANDOFF-23.

---------------------------------------------------------------------
CURRENT STATE (21.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe tests/ -q  ->  2463 passed
- No live run after the fix (needs approval). Expected in the log:
  after a step-20 death + roll 6 -> "Forced sleep (step 20/21)",
  day+1 / step 0, and no "Failed to save state".
- known_issues: 13 open, 12 closed

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q
  .\.venv\Scripts\pytest.exe tests/test_resurrection_day_end.py -q
  python main.py --new --max-steps 80 --log-level INFO   # approval only

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Day rollover (§3/§5) ---
  # forced sleep when step >= 20 (transitional 20->21 after an action)
  # forced sleep blocked in combat -> step clamped to DAY_STEPS
  # the day wraps on the turn the fight ends

  # --- Resurrection (§6) ---
  # one mercy per day: hidden["resurrection_used_today"] is read
  # the state is saved AFTER the resurrection / new life
  # epitaph only when the roll != 6 (game_loop FAILED branch)

  # --- Death cause ---
  # run_turn -> TurnResult.death_cause -> game_loop epitaph

TEST COUNTER: 2463 passed
  Last verified: 21.11.2026

=====================================================================
END OF HANDOFF 23.
=====================================================================
