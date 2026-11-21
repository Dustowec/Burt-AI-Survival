=====================================================================
BURT -- HANDOFF 27
Date: 21.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-26 (preacher effects, full tools menu)
Uncommitted at handoff write: YES (tutorial young_goblin + club)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Task: tutorial monster young_goblin and the level-2 club reward.

1. Design decisions
   - key is young_goblin (the user's "yang_goblin" was a typo);
   - 3 HP, damage 0-1, weapon "fists", no spell;
   - only at level < 2: every non-empty wild location and the thicket
     ambush spawn exactly one young_goblin;
   - empty locations (river / road / village / temple) stay empty;
   - NPC hostility (guard / cleric / necromancer) is not affected;
   - young_goblin is NOT in _ENCOUNTER_TABLE, PACK_ENEMIES,
     possible_enemies or loot;
   - level >= 2: normal tables; young_goblin cannot spawn at all;
   - two kills = 10 XP = level 2;
   - level 2 grants one club as a simulated drop, not in loot.py;
   - old saves already at level 2 get nothing retroactively.

2. burt/bestiary.py
   - young_goblin entry (3 HP, 0-1, fists).
   - tests/test_bestiary.py EXPECTED set updated.

3. burt/spawn.py
   - YOUNG_GOBLIN_KEY = "young_goblin", YOUNG_LEVEL = 2;
   - spawn_for_level(location, level, roll_type, roll_size);
   - ambush_for_level(level, roll_type, roll_size);
   - both validate dice; at level < 2 return one young_goblin;
     at level >= 2 delegate to the untouched spawn_random /
     spawn_ambush tables.

4. burt/loop.py
   - _maybe_start_combat_on_enter uses ambush_for_level /
     spawn_for_level with visible["level"];
   - _handle_movement_failure uses spawn_for_level;
   - _award_combat_xp(..., dead_keys=None) -> bool grants the club on
     old_level < 2 <= new_level and returns True;
   - event: "You take a club from the young goblin." when a young
     goblin was among the dead, otherwise "You pick up a club.";
   - _execute_combat passes dead enemy keys and suppresses
     "Loot: nothing." when the club was granted.

5. Tests: 2769 -> 2990 passed (+221)
   - tests/test_young_goblin_loop.py (new);
   - test_bestiary.py: young_goblin stats + EXPECTED set;
   - test_spawn.py: level gate for all non-empty locations and rolls,
     thicket ambush, level >= 2 never young_goblin, single (not a
     pack), invalid rolls, not in possible_enemies;
   - test_loot.py: young_goblin empty drop;
   - old level-1 normal-spawn tests moved to level 2 (normal tables),
     cap tests moved to level 4 (still < 5).

6. Simulation (current combat code)
   - fists vs young_goblin: 91.9% win, 8.1% death, 6.5 rounds;
   - club vs goblin: 77.6% win, 22.4% death;
   - live loop without LLM: fight 1 -> level 1 / 5 XP;
     fight 2 -> level 2 / 10 XP / club.

---------------------------------------------------------------------
CURRENT STATE (21.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe -q  ->  2990 passed
- No live LLM run after this change.
- Uncommitted: burt/bestiary.py, burt/spawn.py, burt/loop.py,
  tests/*, README.md, ТЗ/known_issues.md, this HANDOFF-27.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe -q                     # 2990 passed
  .\.venv\Scripts\pytest.exe tests/test_young_goblin_loop.py tests/test_spawn.py tests/test_bestiary.py tests/test_loot.py -q
  .\.venv\Scripts\pytest.exe tests/ -q              # tests/ only
  python main.py --new --max-steps 20 --log-level INFO   # approval only

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Tutorial gate ---
  # level < 2: one young_goblin in every non-empty wild location
  # thicket ambush at level < 2: one young_goblin
  # level >= 2: normal spawn_random / spawn_ambush tables
  # young_goblin is not in any spawn table / pack / loot

  # --- Level 2 reward ---
  # 2 kills x 5 XP = 10 XP -> level 2
  # one club added to inventory, event "You take a club from the
  # young goblin."; club is a normal sellable item
  # no retroactive club for old saves already at level 2

TEST COUNTER: 2990 passed
  Last verified: 21.11.2026

=====================================================================
END OF HANDOFF 27.
=====================================================================

