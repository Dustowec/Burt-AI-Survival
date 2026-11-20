=====================================================================
BURT -- HANDOFF 21
Date: 20.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-20 (economy + magic)
Uncommitted at handoff write: YES (progression + combat, see below)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Point C of the roadmap: progression + combat.
Spec sections: §7 (XP/levels), §8 (skills), §20 (weapon damage),
§21 (bestiary), §30 (state), §23 (combat).

1. burt/progression.py (NEW, pure core) -- §7
   - visible["level"], visible["xp"] (running XP for the current life)
   - cap(level) = 10 * 1.5^(level-1), exact Fraction
   - total_xp_for_level(n) = 20 * (1.5^(n-1) - 1)
   - level_for_xp(xp): reproduces the §7 "total kills to level" table
     exactly: 2, 5, 10, 17, 27, 42, 65, 99, 150, 227, ...
   - kill_exp = 5
   - award_kills(visible, kills): XP + level-up, HP +2 / MP +1
   - ensure_state(visible): old-save repair (level 1 / xp 0)
   - NOTE: the per-level list in §7 ("5->6: 11") contradicts its own
     total table ("6: 27"); the total table wins.

2. burt/skills.py (NEW, pure core) -- §8
   - 10 skills: Sword / Club / Spear / Magic + Smithing / Stealth /
     Search / Eloquence / Intimidation / Deception
   - weapon mastery counts every STRIKE, not every hit
   - strikes_to_next: 30 for level 0/1, then ceil(30 * 1.5^(level-1))
   - modifier(level) = level // 5 (+1 at 5, +2 at 10)
   - range_bonus(level) = level // 2
   - record_strike / award_level / sync_visible / ensure_state
   - skills hidden until level 1 (visible["skills_visible"])

3. burt/weapons.py (NEW, pure data) -- §20
   - fists/stone 0-1, goblin dagger 1-2, goblin staff 0-1,
     club 1-2, spear 1-3, swords 1-3 / 2-4 / 3-5, magic 3-6
   - quality: low -1, normal 0, high +1
   - goblin weapons cannot be used in combat (selling stays allowed)
   - select_weapon(inventory, skill_levels): best usable weapon by
     effective damage range, fists as fallback
   - magic_damage_range(skill_level): 3-6 + mastery

4. burt/combat.py
   - BurtStats: weapon, cast_damage_min/max, cast_master,
     cast_modifier (defaults keep old tests green)
   - _burt_cast uses the cast profile instead of hardcoded 3-6
   - RoundResult.burt_acted: False when the ambush free strike kills
     Burt before his action, True after attack/block/flee/cast

5. burt/loop.py
   - _build_burt_stats: skills.level_map -> weapons.select_weapon ->
     damage_min/max + master/modifier + cast profile
   - _execute_combat:
       * records a strike for attack (weapon skill) and cast (Magic)
       * _award_combat_xp on combat end for every dead enemy
         (except burt_died), events "You gain N XP." /
         "You reach level N. HP +2, MP +1."
       * loot still only on burt_won
   - _execute_train passes rng to magic.train (veteran skill roll)

6. burt/magic.py
   - _bump_skill delegates to skills.award_level
   - SKILL_MAX_LEVEL = skills.MAX_LEVEL
   - veteran no longer gives the legacy "Combat" skill: teaches a
     random weapon skill (sword / club / spear) via veteran_skill_name

7. burt/state.py / main.py / sensory.py
   - create_initial_state: visible level 1 / xp 0
   - validate_state: level >= 1, xp >= 0 (optional for old saves)
   - main._ensure_runtime_fields: progression.ensure_state +
     skills.ensure_state
   - sensory [STATE]: "Level: N | XP: a/b" only when level exists

8. TZ-10
   - no code change needed: _start_combat and pending encounter
     already cap at level < 5; level now really grows, so the cap
     lifts at level 5 (tests in test_progression_loop.py)

9. Tests: 2222 -> 2382 passed (+160)
   - test_progression.py (54)
   - test_progression_loop.py (7)
   - test_skills.py (39)
   - test_weapons.py (38)
   - test_combat_equipment.py (12)
   - updated: test_state, test_sensory, test_main, test_life_memory,
     test_magic_wiring (skills_raw now has strikes fields)

---------------------------------------------------------------------
CURRENT STATE (20.11.2026, end of session)
---------------------------------------------------------------------

- 2382 passed, 0 failed
- New life: level 1, xp 0, HP 10, MP 3
- Old saves: level/xp and skill strikes are added on load
- Real game: kill 2 enemies -> level 2 (HP 12, MP 4);
  level 5 -> TZ-10 pack cap lifts; weapon in inventory is used
  automatically; skills appear in [SKILLS] from level 1
- known_issues: 14 open (was 17), closed #5 XP/levels, #6 skills,
  #7 weapon table
- Not done on purpose: full non-combat skill growth (spec defines no
  per-use growth), faith/statuses (#10), events/effects (#11)

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 2382 pass
  python main.py --new --dry-run                # Level: 1 | XP: 0/10
  python main.py --dry-run                      # old save migration
  git --no-pager log --oneline -5

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Progression (§7) ---
  # progression.cap(level) = 10 * 1.5^(level-1), kill_exp = 5
  # visible["xp"] is a running total; level = level_for_xp(xp)
  # award_kills: +2 HP / +1 MP per level (max and current, clamped)
  # loop._award_combat_xp on combat end (not on burt_died)
  # TZ-10 cap: level < 5 -> one enemy (start + pending encounter)

  # --- Skills (§8) ---
  # hidden["skills_raw"]: name, level, strikes, strikes_to_next, curve
  # weapon mastery = per strike, 30 strikes for level 1, curve x1.5
  # modifier = level // 5; range_bonus = level // 2
  # visible["skills_visible"] shows only level >= 1

  # --- Weapons (§20) ---
  # weapons.select_weapon(inventory, levels) -> WeaponChoice
  # quality: low -1 / normal 0 / high +1
  # goblin_dagger / goblin_staff: cannot use, can sell
  # BurtStats.damage_min/max from equipment; cast = 3-6 + mastery

  # --- Combat wiring ---
  # RoundResult.burt_acted gates strike counting
  # attack -> weapon skill strike; cast -> Magic strike
  # loot only on burt_won; XP for dead enemies on any non-death end

TEST COUNTER: 2382 passed
  Last verified: 20.11.2026

=====================================================================
END OF HANDOFF 21.
=====================================================================

