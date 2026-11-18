=====================================================================
BURT -- HANDOFF 17
Date: 19.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-16 (fully closed by this)
Uncommitted at handoff write: YES (TZ-9 pending commit)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. TZ-9 closed: encounter reveal via osmotret; ambush only in thicket.

2. State (burt/state.py):
   - create_initial_state hidden: pending_encounter=None,
     encounter_revealed=False.

3. main.py:
   - _ensure_runtime_fields: setdefault for the two new fields.
   - _do_sleep: any sleep (incl. forced) clears pending encounter.

4. burt/loop.py (encounter flow):
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

5. Tests:
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

6. Test results: 1688 passed, 0 failed.

---------------------------------------------------------------------
CURRENT STATE (19.11.2026, end of session)
---------------------------------------------------------------------

- 1688 passed, 0 failed
- Encounter reveal flow implemented per TZ-9
- Search/foraging in forest still works while encounter unrevealed
- Thicket remains the only immediate-ambush location
- search blocked only while encounter_revealed=True (per TZ-9)

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1688 pass (verify)
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

TEST COUNTER: 1688 passed
  Last verified: 19.11.2026

=====================================================================
END OF HANDOFF 17.
=====================================================================
