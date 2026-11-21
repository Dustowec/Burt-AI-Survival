=====================================================================
BURT -- HANDOFF 26
Date: 21.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0 / new_bug.md (20.11.2026)
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-25 (NPC hostility / NPC combat)
Tag: v0.9.2-BETA (this commit)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Task 1: random events and effects (§10, §13) -- known_issues #11.
Task 2: full tools menu (§26) -- known_issues #12.

1. New pure core: burt/events.py
   - EFFECT_BLESSED / EFFECT_CURSED / EFFECT_DURATION = 3;
   - resolve_preacher(roll): 1 curse, 2-5 nothing, 6 blessing;
   - effect_for(kind): curse -> cursed, blessing -> blessed,
     nothing -> None;
   - hidden["effects_detail"] entries {type, modifier, turns_left};
   - ensure_state / sync_visible / apply_effect / tick / modifier;
   - spawn_preacher(hidden, rng): §10 table (5-6 good) -> the
     preacher_event joins npcs_here + events_here, never npcs_by_node;
   - mark_preacher_used(hidden).

2. Preacher wiring (loop.py)
   - spawn only after a positive travel event (movement roll 5-6);
     the preacher d6 is the LAST die, so the old dice order is intact;
   - text: "You are lucky to meet a preacher." appended after the
     loot/blessing line (never at events[0]);
   - talk_to_preacher_event: free, intro from
     replicas.events.preacher_event.intro, no reputation;
   - the first topic reply rolls once (1/6), text from
     curse / nothing / blessing pools, effect applied;
   - dialog_exit ticks once, removes the preacher from npcs_here and
     marks events_here used; sleep also removes him;
   - neutral to every faith status (non-resident: can_talk_to True).

3. Effects
   - curse -1 / blessing +1 to BurtStats.modifier and cast_modifier;
   - execute_dialog passes events.modifier(hidden) to Session.say
     (dialogue pairs shift, §12);
   - execute_action wrapper ticks after every step-advancing action
     and after every combat round (combat does not move the step);
   - free tools and dialogue replies do not tick;
   - sleep clears visible["effects"] and hidden["effects_detail"];
   - sensory shows "Effects: blessed|cursed" with no duration/numbers.

4. Tools (§26)
   - loop.TOOL_KEYS = scroll / inventory / status / remember / diary;
   - all cost_free=True; appended at the end of the exploring, dialog
     and combat menus (old indices stay stable);
   - NOT in micro-locations (only go_back/go_forward) and NOT in the
     revealed-encounter menu (only attack_* / go_away_to_*);
   - handlers run before dialog/combat routing: no step tick, no mode
     change, no HP/wallet/inventory change;
   - output: [SCROLL], [INVENTORY] (Name -- Npcs / empty),
     [STATUS] (HP/MP, Fed, Sleep: N/20, Effects: ...),
     [MEMORY], [DIARY];
   - main.run_turn stores the text in hidden["pending_tool_output"]
     and prepends it to the next prompt once (ReAct-lite), then clears;
   - CHOICE re-ask (new_bug §8) is unchanged.

5. Tests: 2665 -> 2769 passed (+104)
   - tests/test_events.py (42);
   - tests/test_preacher_loop.py (26);
   - tests/test_tools_menu.py (33);
   - tests/test_tools_prompt.py (3).
   Targeted regressions: test_loop, test_loop_movement_events,
   test_npc_spawn_loop, test_blessing_text, test_encounter_reveal,
   test_dialogue_single_action, test_scroll_tool, test_loop_combat,
   test_sensory, test_npc, test_main, test_magic_wiring,
   test_npc_hostility_loop, test_social_integration, test_trade_loop,
   test_quests*, test_faith*, test_integration,
   test_invalid_choice_retry, test_state*, test_combat,
   test_cast_in_combat, test_game_session, test_logging_integration,
   test_main_lives, test_state_persistence_lives,
   test_resurrection_day_end.

6. Docs
   - known_issues #11 and #12 -> DONE / CLOSED;
   - README v0.9.2-BETA + priorities renumbered;
   - this HANDOFF-26.

---------------------------------------------------------------------
CURRENT STATE (21.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe -q  ->  2769 passed
  (tests/ only: 2734; the root-level test_npc_integration.py adds 35)
- No live run after this change (approval only).
- known_issues open: 11 (high 2, medium 2, low 8; deviations not counted).
- Committed and tagged: v0.9.2-BETA (burt/events.py, burt/loop.py,
  burt/npc.py, burt/sensory.py, main.py, tests/*, docs).

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe -q                     # 2769 passed
  .\.venv\Scripts\pytest.exe tests/ -q              # 2734 (tests/ only)
  .\.venv\Scripts\pytest.exe tests/test_events.py tests/test_preacher_loop.py tests/test_tools_menu.py tests/test_tools_prompt.py -q
  python main.py --new --max-steps 20 --log-level INFO   # approval only

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Preacher (§13) ---
  # not a role; never in npcs_by_node; neutral to all faith statuses
  # spawn: positive travel event (move 5-6) + separate d6 5-6
  # dialogue: one roll -> 1 curse / 2-5 nothing / 6 blessing
  # curse -1, blessing +1, exactly 3 actions
  # dialog_exit removes him; sleep removes him; events_here.used=True

  # --- Effects ---
  # hidden["effects_detail"] = {type, modifier, turns_left}
  # visible["effects"] = types only (no duration)
  # tick: step-advancing actions + combat rounds; NOT tools/replies
  # sleep clears both sections

  # --- Tools (§26) ---
  # scroll / inventory / status / remember / diary
  # exploring + dialog + combat; not micro, not encounter reveal
  # no step tick; text goes to the next prompt (pending_tool_output)

TEST COUNTER: 2769 passed
  Last verified: 21.11.2026

=====================================================================
END OF HANDOFF 26.
=====================================================================

