=====================================================================
BURT -- HANDOFF 17
Date: 19.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-16 (fully closed by this)
Uncommitted at handoff write: YES (TZ-9 committed, TZ-10 pending commit)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. Earlier-18:00 commits from 18.11 backfilled into this handoff:

2. TZ-4-FIX (18.11 20:05, commit 054e959):
   - burt/llm_client.py: atomic append of the FULL {user, assistant}
     pair to messages_history on each call. History stays even-length
     with strict user/assistant alternation, so message_builder and
     Gemma's template still work when system is folded out and the
     history is non-empty.

3. TZ-7 (18.11 20:22, commit 7637cc4):
   - burt/loop.py execute_action / go_forward: an unentered target is
     now initialized via _enter_new_node before reading its type.
     Fixes bug where loc_type was '' (no encounter fired) on
     go_forward into a fresh node.
   - Tests: tests/test_loop_combat_start.py TestGoForwardInitTZ7.

4. TZ-6 fix (18.11 21:30, commit 55b8c00):
   - burt/dice.py MicroEventResult: new field flat_damage (None = roll
     rng, int = fixed damage).
   - god_wrath: damage_min/max now 0/0 and flat_damage=level (fixed
     damage = level, not computed as a range).
   - calculate_micro_damage: returns flat_damage directly when set;
     otherwise rolls rng() with (rng()-1) % range + min.
   - Tests updated: test_loop.py, test_loop_bad_events.py,
     test_loop_combat_start.py (TestMicroEventFlatDamageTZ6).

5. TZ-8 (18.11 21:47, commit fe9b729):
   - NEW tests/test_combat_order.py (279 lines): ambush free strike
     fires before Burt's action and only once; burt initiative has no
     free strike; ambush death resolves before Burt's turn; second
     round has no ambush free strike.

6. TZ-9 closed: encounter reveal via osmotret; ambush only in thicket.

7. State (burt/state.py):
   - create_initial_state hidden: pending_encounter=None,
     encounter_revealed=False.

8. main.py:
   - _ensure_runtime_fields: setdefault for the two new fields.
   - _do_sleep: any sleep (incl. forced) clears pending encounter.

9. burt/loop.py (encounter flow):
   - _maybe_start_combat_on_enter: non-ambush locations now create
     hidden["pending_encounter"] = {node_id, enemy_keys} instead of
     starting combat. Thicket (ambush) still starts combat
     immediately with initiative="enemy".
   - _start_combat: clears pending encounter on any combat start.
   - osmotret: if valid pending -> encounter_revealed=True +
     "You see: <display names>."; stale pending cleared silently.
   - build_menu: if revealed+valid jumps to encounter menu; invalid
     revealed -> self-heal to normal exploration menu.
   - _build_encounter_menu: only attack_{id} per previewed enemy and
     go_away_to_{direction} per existing exit.
   - _execute_encounter_attack: validates target against
     _preview_pending_enemies (combat.start_combat dry run), then
     clears pending, step+1, starts combat with initiative="burt",
     free_strike_done=True, no "Ambush!", no actual hit.
   - _execute_go_away: validates exit, clears pending, then performs
     a normal go (one step, last_action, movement loot/blessing,
     possibly new encounter on enter).
   - go_* handler clears stale pending on valid movement only.
   - Helpers: _clear_pending_encounter, _is_pending_encounter_valid,
     _preview_pending_enemies.
   - Step rules: +1 on attack-start, frozen during subsequent rounds.

10. Tests (encounter reveal, TZ-9):
   - NEW tests/test_encounter_reveal.py: 22 tests covering on-entry
     pending (forest), no-spawn/empty-spawn, thicket ambush, osmotret
     reveal/stale/no-pending, encounter menu attack/go_away only,
     enemy ids match start_combat, self-heal invalid pending,
     attack start (burt init, one step, no Ambush/hit), invalid
     target, go_away valid/invalid + movement event parity, normal
     go clearing unrevealed pending, search while pending (works),
     search blocked when revealed, first round no ambush, step
     frozen during combat.
   - tests/test_loop_combat_start.py: on-entry expectations rewritten
     to pending_encounter (TZ-9); thicket ambush unchanged.
   - tests/test_loop_movement_events.py: bad-movement-combat tests
     re-based on thicket ambush instead of forest.

11. TZ-10 (cap spawn to 1 enemy when Burt level < 5):
   - Rule: while level < 5 -> single monster, not a pack. Default
     level=1 when absent (visible.get("level", 1)). At level >= 5 the
     existing pack spawn stays.
   - burt/loop.py _start_combat: cap enemy_keys to [:1] before
     combat.start_combat. Single choke point that covers thicket ambush
     and any other combat start.
   - burt/loop.py _maybe_start_combat_on_enter: same cap applied when
     building pending_encounter["enemy_keys"], so the reveal ->
     encounter-menu -> combat all agree on the single monster.
   - Does NOT touch spawn.py, combat.py, or the _start_combat signature.
   - Tests in tests/test_loop_combat_start.py:
     - TestStartCombatTz10 (6): capped lvl1, capped lvl4, uncapped lvl5,
       preserves first, single enemy unchanged, empty-level default.
     - TestTz10EncounterConsistency (3): pending cap lvl1, ambush cap
       lvl1, ambush uncap lvl5.
     - test_thicket_always_ambush set to level=5 to keep its pack-size
       assertion (3 wolves) while testing uncapped path.

12. Test results: 1697 passed, 0 failed.

---------------------------------------------------------------------
CURRENT STATE (19.11.2026, end of session)
---------------------------------------------------------------------

- 1697 passed, 0 failed
- Encounter reveal flow implemented per TZ-9
- Search/foraging in forest still works while encounter unrevealed
- Thicket remains the only immediate-ambush location
- search blocked only while encounter_revealed=True (per TZ-9)
- TZ-10 implemented (cap spawn to 1 enemy while level < 5); UNCOMMITTED

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1697 pass (verify)
  python main.py --new --max-steps 40 --log-level INFO
  python main.py --new --dry-run                # inspect state only
  git --no-pager log --oneline -5               # recent commits

---------------------------------------------------------------------
MODEL RECOMMENDATIONS (6 GB VRAM):
---------------------------------------------------------------------

  - Qwen 3.5 4B (thinking on) + max_tokens=2048 — BEST
  - Gemma 3n-E4B (system->user fallback) — FAST, but robotic
  - Gemma 4 E2B (thinking on) — WORST (osmotret spammer)

  External API (paid):
  - gpt-4o-mini — cheap, fast, good enough
  - claude-haiku — fast, cheap

MEMORY AID (all English):

  # --- TZ-9: encounter reveal via osmotret (HANDOFF-17) ---
  # state: hidden["pending_encounter"]=None|{node_id, enemy_keys}
  #        hidden["encounter_revealed"]=False
  # non-ambush encounter location entry -> pending, NO combat
  # osmotret reveals -> "You see: ..." once -> menu attack_*/go_away_to_*
  # attack_{enemy_id} -> combat initiative="burt", free_strike_done=True,
  #   step+1 once, no Ambush, no actual hit that turn
  # go_away_to_{d} -> clear + normal go (one step, loot/blessing ok)
  # valid go_* clears unrevealed pending; invalid keeps it
  # thicket stays immediate ambush (initiative="enemy")
  # _preview_pending_enemies = combat.start_combat dry-run for ids/labels
  # search works while unrevealed; blocked only when revealed
  # New tests: tests/test_encounter_reveal.py (22 tests)

  # --- TZ-10: cap spawn to 1 enemy while level < 5 (HANDOFF-17) ---
  # rule: visible.get("level", 1) < 5 and len(enemy_keys) > 1
  #       -> enemy_keys = enemy_keys[:1] (single monster, not a pack)
  # level >= 5 (or absent default 1) -> existing pack spawn unchanged
  # point 1: loop._start_combat (covers thicket ambush + any combat)
  # point 2: loop._maybe_start_combat_on_enter pending_encounter enemy_keys
  #   so reveal -> encounter menu -> combat all show the same 1 enemy
  # did NOT touch spawn.py, combat.py, _start_combat signature
  # New tests: TestStartCombatTz10 (6) + TestTz10EncounterConsistency (3)

TEST COUNTER: 1697 passed
  Last verified: 19.11.2026

=====================================================================
END OF HANDOFF 17.
=====================================================================
