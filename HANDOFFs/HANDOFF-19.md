=====================================================================
BURT -- HANDOFF 19
Date: 20.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-18 (logging, tag v0.8.5)
Uncommitted at handoff write: YES (social layer, see below)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Point A of the roadmap: bring the social layer to life.
Spec sections: §32 (NPC spawn), §36 (role quests), §18 (quests),
§26 (tools), §16 (reputation).

1. burt/npc_spawn.py (NEW, pure core)
   - ROLE_SPAWN pools:
       village: elder, peasant, peasant_woman, blacksmith, merchant,
                child, guard, tavernkeeper
       river:   fisherman, merchant
       road:    merchant
       forest:  veteran
       temple:  cleric (always)
       dungeon: necromancer (always)
   - village: 1d6 -> 1/2/3 roles, no duplicates
   - river/road: one role + rare role (cleric/necromancer) on d6 >= 5
   - bandit is a monster (§21), never an NPC
   - spawn cached per node in hidden["npcs_by_node"];
     hidden["npcs_here"] is the working list
   - API: roll_npcs, ensure_npcs, npcs_for, clear_npcs, reset_cache

2. loop.py — single arrival point
   - NEW _arrive_at_node(node_id, graph, hidden, visible, rng)
     used by go_*, go_forward, go_away_to_*: node init, visible update,
     TZ-9 encounter roll, NPC spawn
   - order matters: encounter roll FIRST (keeps the exact rng sequence
     that combat tests rely on), NPC spawn after it
   - exploring menu now lists talk_to_* TOGETHER with exits, search
     and the scroll; a revealed encounter still replaces the menu

3. quests_templates.json
   - +22 role quests (7 roles x 3): deliver / kill / visit / talk / help
   - legacy fix: pala_2 used "goblin_shaman_staff" (does not exist),
     now "goblin_staff"
   - every template now has an explicit "target" key


4. burt/quests.py
   - Quest dataclass: new `target` field, persisted in quests_raw
   - QUEST_ROLES, REPUTATION_QUEST_MIN = -5
   - roll_deadline(rng): 1d6 -> 3/5/7 days (§36)
   - pick_quest_for_role(role, state, rng)
   - quest_state_for_role(role, state) -> available | in_progress | none
     (none when rep <= -5, role blocked, no templates, or cannot give)
   - progress hooks: on_enemy_killed, on_enter_location, on_talk,
     on_quest_completed (each returns quest ids that became ready)
   - deliver_ready / deliver_progress (inventory check, §18)

5. loop.py — quest flow
   - _execute_talk_to: dialog_state["quest_state"] from the real state,
     plus "rep_applied": False
   - dialog_quest:
       available   -> _issue_role_quest (quest_give + rolled deadline)
       in_progress -> _try_hand_in_quest (hand-in when finished)
   - kill hook inside _execute_combat on "burt_won" + "Quest ready" event
   - visit hook inside _arrive_at_node
   - talk hook on every non-quest reply
   - format_scroll(): [SCROLL] block, giver hidden, inventory progress,
     days left

6. burt/reputation.py (NEW, pure core)
   - range -10..+10, clamped; unknown roles ignored
   - DIALOGUE_SUCCESS +1 / NEUTRAL 0 / FAIL -1 / ANGER -2
   - QUEST_DELTA_OK +1 / QUEST_DELTA_FAIL -2
   - KILL_OVERALL -5 / KILL_ROLE -10 (ready for §34)
   - apply_dialog_rep(): at most one change per role per dialogue
   - price_modifier(): 0.9 / 1.0 / 1.1; can_give_quests(): rep > -5
   - wired: dialogue outcome, quest hand-in, reset on dialog exit


7. Tests: 1938 -> 2099 passed (+161)
   - test_npc_spawn.py (50)
   - test_npc_spawn_loop.py (13)
   - test_quests_roles.py (35)
   - test_quests_hooks.py (18)
   - test_scroll_tool.py (9)
   - test_reputation.py (30)
   - test_social_integration.py (8)
   - test_loop_combat_start.py: go_forward expectation updated
     (village now rolls for its NPCs)

---------------------------------------------------------------------
CURRENT STATE (20.11.2026, end of session)
---------------------------------------------------------------------

- 2099 passed, 0 failed
- Dialogue reachable in a real game: village/forest/road/river/temple/
  dungeon spawn NPCs, menu offers talk + exits + search + scroll
- Role quests: issued with a rolled deadline, progress through
  kill/visit/talk/help/deliver, handed in at the giver
- Quest scroll shows open quests without the giver (§18)
- Reputation: changes from dialogue and quests, blocks quests at -5
- known_issues: 19 open (was 23), 4 items closed

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 2099 pass
  python main.py --new --max-steps 10           # walk, meet, talk
  python main.py --new --dry-run                # inspect menu

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- NPC spawn (§32) ---
  # npc_spawn.ROLE_SPAWN: village/river/road/forest/temple/dungeon
  # village 1-3 roles (d6), temple/dungeon exactly one
  # river/road: rare role on d6 >= 5
  # cached per node: hidden["npcs_by_node"][node_id] = [roles]
  # working list: hidden["npcs_here"]

  # --- Arrival (§17, TZ-9, §32, §36) ---
  # loop._arrive_at_node: init node -> visible -> encounter -> visit
  # quest hook -> NPC spawn. Encounter dice come first (test contract).

  # --- Quests (§18, §36) ---
  # dialog_quest: available -> issue, in_progress -> hand in
  # deadline: quests.roll_deadline -> 3/5/7 days
  # hooks: on_enemy_killed / on_enter_location / on_talk /
  #        on_quest_completed; deliver_ready for item quests
  # scroll tool: free action, no step growth, giver hidden

  # --- Reputation (§16) ---
  # reputation.change(state, role, delta) -> clamped new value
  # one dialogue change per role: reputation.apply_dialog_rep
  # reset on dialog exit: reputation.reset_dialog_rep
  # rep <= -5 -> quests blocked; price modifier 0.9 / 1.0 / 1.1

TEST COUNTER: 2099 passed
  Last verified: 20.11.2026

=====================================================================
END OF HANDOFF 19.
=====================================================================

  git --no-pager log --oneline -5
