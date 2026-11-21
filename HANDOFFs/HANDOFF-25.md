=====================================================================
BURT -- HANDOFF 25
Date: 21.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0 / new_bug.md (20.11.2026)
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-24 (faith statuses, chains, crime core)
Uncommitted at handoff write: YES (§34 NPC hostility)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Task: NPC hostility (§34, continuation of #10) and NPC combat.

1. New pure core: burt/npc_combat.py
   - NPC_ROLES = guard / cleric / necromancer;
   - enemy_key(role), is_npc_enemy(key), is_hostile(state, role),
     hostile_role(npcs, state);
   - only "fight" counts; "flee" / "none" are ignored;
   - status comes from faith.get_status, never from killer_from, so a
     paladin-turned-killer does not aggro the necromancer.

2. Bestiary (§32/§34)
   - guard: HP 15, damage 2-4, sword, tag "npc" (numbers are an
     assumption: the spec gives none);
   - cleric: HP 25, MP 50, light 5-8 for 1 MP, staff 1-3 (spec);
   - necromancer: mirrors the cleric (dark magic is mechanically the
     same spell in combat.py).

3. Faith dialogue gate
   - faith.can_talk_to(state, role): hostile residents are combat, not
     dialogue; non-residents stay talkable; after a crime only the
     necromancer remains talkable;
   - NO_TALK_AFTER_CRIME = all residents except the necromancer;
   - cannot_talk_after_crime() kept as a status-free compatibility
     helper.

4. Loop wiring
   - a hostile resident attacks on arrival (enemy initiative);
   - the same resident attacks right after dialog_attack in the same
     node, in the same action;
   - choosing talk_to_<hostile> is a re-engagement path ("Approach the
     <role>") after a flee;
   - the cleric serves god's wrath once (paladin -> killer), then
     fights; if the punishment kills, no combat starts;
   - winning an NPC fight runs faith.on_resident_killed + remove_npc
     (status, quests, rep, life block, chain blocks, god's wrath);
   - fleeing keeps the NPC alive and applies no crime;
   - hidden["combat_npc_role"] survives save/load and is cleared on
     win / flee / death; old saves get it via _ensure_runtime_fields.

5. Combat API
   - resolve_free_strike / open_combat accept opening_text
     (default "Ambush!"); NPC fights use "The guard attacks!" etc.
     Monster logs stay unchanged.

6. Intentional design (decided by the author)
   - killer + heretic_3 is unsolvable: the cleric fights a killer on
     sight, and the insult step needs the cleric dialogue;
   - a killer, a heretic-killer and a paladin-killer cannot shed the
     status; murder is an execution, not a resettable state;
   - the necromancer still offers K3, so the dead end is visible;
   - recorded in known_issues #10 and README "Осознанно оставлено".

7. Tests: 2534 -> 2665 passed (+131)
   - test_npc_combat_core.py (36);
   - test_npc_hostility_loop.py (40);
   - test_faith.py 51 -> 55 (can_talk_to, no-talk);
   - test_bestiary.py +16 (guard / cleric / necromancer);
   - test_faith_crime.py updated: Approach labels, punishment+fight,
     child flee fixture without a cleric;
   - test_npc_integration.py (35, root-level; included in the full run).

8. Docs: known_issues #10 -> DONE / CLOSED with the K3 design note,
   README roadmap + test counter v0.9.1, this HANDOFF-25.

---------------------------------------------------------------------
CURRENT STATE (21.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe -q  ->  2665 passed
  (tests/ only: 2630; the root-level test_npc_integration.py adds 35)
- No live run after this change (needs approval, max 20 steps).
- known_issues #10 is closed; the K3 killer dead-end is a design note.
- Tag: v0.9.1.
- Uncommitted: bestiary, combat, faith, loop, state, main, tests, docs.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe -q                     # 2665 passed
  .\.venv\Scripts\pytest.exe tests/ -q              # 2630 (tests/ only)
  .\.venv\Scripts\pytest.exe tests/test_npc_combat_core.py tests/test_npc_hostility_loop.py -q
  python main.py --new --max-steps 20 --log-level INFO   # approval only

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- NPC hostility (§34) ---
  # killer   -> guard / cleric fights on arrival and after a murder
  # paladin  -> necromancer fights
  # heretic  -> cleric fights
  # killer   -> child / peasant* flee
  # killer   -> necromancer still talks (K3), other residents do not
  # Approach the <role> = re-engage after flee; Talk to <role> = dialogue

  # --- Punishment + crime ---
  # cleric first: god's wrath 1*level once, then fight
  # punishment can kill -> god_wrath, no combat
  # combat victory over a resident = dialog_attack crime pipeline
  # flee = NPC stays, no crime
  # hidden["combat_npc_role"] = guard|cleric|necromancer|None

  # --- K3 killer dead end (by design) ---
  # the necromancer offers heretic_3, but the cleric fights on sight,
  # so the insult step is unreachable; killer = execution

  # --- New bestiary ---
  # guard: 15 HP, 2-4 sword
  # cleric: 25 HP, 50 MP, 5-8 light (1 MP), 1-3 staff
  # necromancer: same as cleric (dark magic)

TEST COUNTER: 2665 passed
  Last verified: 21.11.2026

=====================================================================
END OF HANDOFF 25.
====================================================================
