=====================================================================
BURT -- HANDOFF 22
Date: 20.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0 / new_bug.md (20.11.2026)
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-21 (economy + magic + progression)
Uncommitted at handoff write: YES (new_bug implementation)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Implemented the agreed new_bug.md plan after v0.8.8-BETA.

1. P0 -- state persistence of the current life (new_bug §0)
   - main.game_loop now returns the CURRENT state (-> dict);
   - a new life replaces the state IN PLACE (clear + update), so the
     caller's reference, Ctrl+C and the final save all see the last life;
   - main() does `state = await game_loop(...)` and saves that object;
   - tests: tests/test_state_persistence_lives.py (return value, file on
     disk, Ctrl+C, main() saves the returned state).

2. Dialogue = one action (new_bug §1)
   - talk_to_* no longer ticks;
   - replies, quest issue/hand-in, training, trade, buys, sells and
     closing the shop do not tick;
   - only dialog_exit ticks, via the single loop._finish_dialog;
   - eat_food is unreachable in dialog mode (menu + routing);
   - tests: tests/test_dialogue_single_action.py;
     test_trade_loop buy/sell step assertions updated.

2a. Anger lock expires (live-run finding, npc.py)
   - Session.advance_turn() was never called, so `turn` stayed 0 and
     `_build_dialog_menu` hid dialog_exit forever after a fail_angry;
   - every Session.say() now advances one dialogue turn; the exit
     reopens after two replies;
   - test: test_dialogue_single_action.py::TestAngerLock.

3. One date format (new_bug §2)
   - burt.state.format_date(day) -> "N day";
   - burt.state.canonical_date() repairs legacy saves;
   - used by create_initial_state, sensory [STATE], voluntary sleep,
     forced sleep, go_back and main._sync_meta_from_hidden;
   - tests: tests/test_date_format.py (plus a source scan for the old
     suffix).

4. Blessing text follows the real delta (new_bug §3)
   - loop._apply_movement_event applies the event and picks the text:
     delta > 0 -> "A blessing restores your vitality.";
     delta == 0 -> "A blessing washes over you.";
   - both movement paths (go_* and go_away_to_*) use it;
   - tests: tests/test_blessing_text.py,
     test_loop_movement_events.py updated.

5. Bonuses: human text + real coins/food (new_bug §4)
   - burt.npc.bonus_text() table; raw keys never reach the LLM;
   - unknown types -> neutral line + WARN;
   - loop._apply_bonus_effects(): coins -> wallet, food -> 1 bread;
   - tests: tests/test_bonus_text.py.

6. Combat sensory: HP and MP (new_bug §5)
   - sensory.format_combat_report puts "HP: x/y | MP: a/b" right after
     [COMBAT], before Enemy; same format as [STATE];
   - opening report is built after the free strike, so damage is visible
     immediately;
   - tests: tests/test_combat_sensory_hp.py,
     test_sensory_combat.py and test_loop_combat.py updated.

7. go_back text (new_bug §6)
   - "Return to <location name>." instead of the node id;
   - date via format_date;
   - tests: tests/test_go_back_text.py.

8. One sleep helper (new_bug §7)
   - loop._apply_sleep_state(state): HP/MP max, effects cleared,
     eat=False, sleep_counter=0, room consumed, day+1, step=0,
     date=format_date, day_log=[], diary flags, pending_encounter=None,
     encounter_revealed=False, resurrection_used_today=False;
   - voluntary sleep and main._do_sleep both call it;
   - tests: tests/test_sleep_parity.py.

9. Invalid CHOICE: retry + fallback (new_bug §8)
   - loop.parse_choice_strict(): a valid CHOICE line is required;
   - loop.INVALID_CHOICE_KICK = "Hey, you bumpkin! ...";
   - main.run_turn: one retry (answer + kick go into history through
     llm_client), both invalid attempts logged WARN;
   - loop.fallback_action(): block -> osmotret -> dialog_exit -> first;
   - lenient loop.parse_choice kept for tests/compatibility;
   - tests: tests/test_invalid_choice_retry.py,
     test_logging_integration.py still green.

10. Docs
    - known_issues #14 (dialogue ticks) -> CLOSED; #12 re-ask note
      updated; summary: 13 open, 11 closed;
    - README: v0.8.9-BETA, 2457 tests;
    - this HANDOFF-22.


---------------------------------------------------------------------
CURRENT STATE (20.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe tests/ -q  ->  2457 passed
- python main.py --new --dry-run        ->  Date: 1 day, HP/MP in STATE
- python main.py --new --max-steps 80 --log-level INFO:
  DONE, 80 turns. Final state life 3 (life 1 -> 2 by hunger,
  life 2 -> 3 by combat, one resurrection in between). state_io.load_state
  returns life 3. No "Bonus:", "day(s)", "node_", "Return to start" in
  the log; combat reports carry HP/MP (71 hits); 12 dialogue actions in
  a row stayed on step 4 and only dialog_exit moved the step.
- known_issues: 13 open, 11 closed (#14 closed here)

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 2457 pass
  python main.py --new --dry-run                # Date: 1 day
  python main.py --new --max-steps 80 --log-level INFO
  git --no-pager log --oneline -5

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Dialogue (§1) ---
  # one dialogue = one action; only dialog_exit -> _finish_dialog -> +1
  # talk/reply/quest/train/trade/buy/sell/close_shop never tick
  # eat_food is exploring-only

  # --- Date (§2) ---
  # state.format_date(day) -> "N day"; canonical_date repairs old saves

  # --- Blessing (§3) ---
  # real delta > 0 -> restores; delta == 0 -> washes over

  # --- Bonuses (§4) ---
  # npc.bonus_text(); coins -> wallet, food -> bread; no "Bonus:" ever

  # --- Combat sensory (§5) ---
  # [COMBAT] / HP: x/y | MP: a/b / Enemy / Your turn / menu

  # --- go_back (§6) ---
  # "Return to <visible location name>." + format_date

  # --- Sleep (§7) ---
  # loop._apply_sleep_state is the single source for both sleep paths

  # --- Invalid CHOICE (§8) ---
  # parse_choice_strict -> one retry (INVALID_CHOICE_KICK) -> fallback
  # fallback: block -> osmotret -> dialog_exit -> first menu action

  # --- P0 (§0) ---
  # game_loop returns state and replaces a new life in place

TEST COUNTER: 2457 passed
  Last verified: 20.11.2026

=====================================================================
END OF HANDOFF 22.
=====================================================================

