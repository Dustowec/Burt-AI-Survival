=====================================================================
BURT -- HANDOFF 28
Date: 24.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Code: v0.9.5-BETA
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-27 (tutorial young_goblin + level-2 club)
Remote tag check: origin latest was v0.9.4-BETA -> next is v0.9.5-BETA
Uncommitted at handoff write: YES
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. Sleep and diary
   - ordinary `sleep` action removed completely (menu, synonyms,
     execute_action, main forced-sleep check);
   - only `write_diary_and_go_sleep` remains (bedroll / paid room,
     step >= 19); forced sleep at step 20 is unchanged;
   - the old critical-HP sleep-without-bed valve is gone with it;
   - new morning inject at step 0 of a new day:
     "CHECK YOUR DIARY!!! Check your diary, quest scroll and inventory
     before you move."

2. Veteran spawn
   - removed from the forest pool (forest is empty now);
   - `npc_spawn.maybe_add_veteran` spawns him only in the village,
     d6 >= 5, at most once per 10 game days;
   - cooldown stored in hidden["veteran_last_spawn_day"];
   - while the cooldown is active the die is not rolled (RNG order safe).

3. Dialog anti-loop
   - `dialog_state["dialog_last_action"]` / `dialog_same_count`;
   - the 3rd identical dialog action in a row cuts the dialogue,
     costs 1 HP and injects
     "Shut up, kid! I don't have time for this!";
   - `dialog_exit` and shop transactions break the streak instead of
     counting, so trade and anger-lock are not affected.

4. Hands vs backpack
   - new pure module `burt/hands.py`;
   - `visible["inventory"]` remains the single source of item counts;
   - `visible["hands"] = {"weapon": ..., "item": ...}` holds at most two
     references;
   - base sensory report shows only [HANDS]; the inventory tool shows
     [INVENTORY] = [HANDS] + [BACKPACK];
   - only the slot-1 weapon is used in combat; backpack weapons do nothing
     until equipped;
   - equip_<item> / unequip_weapon / unequip_item are free actions;
   - eating/drinking uses slot 2 and auto-picks the item from the backpack
     when needed;
   - old saves migrate automatically (best weapon + first food/water).

5. Trade no-money block
   - per-trader counters in hidden["trade_buy_failures"];
   - block in hidden["trade_dialog_blocked_until"] until the next day;
   - any failed purchase with insufficient coin counts; successful buys,
     sells, item changes and reopening the shop do not reset the counter;
   - on the 3rd failure the dialogue is cut, the trader refuses to talk
     until the next day, inject:
     "STOP! You have no money! Go work!";
   - `trade.ensure_state` / `refresh_day` / `record_failed_buy` /
     `is_dialog_blocked` own the logic; loop only wires it.

6. Documentation
   - README refreshed for v0.9.5-BETA, 3093 tests, new modules, tests,
     mechanics and history;
   - `ТЗ/known_issues.md` refreshed: statuses, deviations, summary,
     verification; open items now 8;
   - `rules/Правила для игрока (LLM).md` and `rules/правила общие.md`
     updated (sleep, hands, trade block, anti-loop, coin, map);
   - `CyrDict.md` updated with [INVENTORY], [BACKPACK], [weapon], [item];
   - this HANDOFF-28.

---------------------------------------------------------------------
CURRENT STATE (24.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe -q  ->  3093 passed
- compileall burt + main.py       ->  ok
- git diff --check                ->  clean
- No live LLM run after these changes.
- Uncommitted: burt/loop.py, burt/npc_spawn.py, burt/prompts.py,
  burt/quests.py, burt/sensory.py, burt/state.py, burt/trade.py, main.py,
  burt/hands.py (new), tests/*, README.md, ТЗ/known_issues.md,
  rules/*.md, CyrDict.md, this HANDOFF-28.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe -q                     # 3093 passed
  .\.venv\Scripts\pytest.exe tests/test_hands.py tests/test_veteran_spawn.py tests/test_dialog_repeat_guard.py tests/test_trade_no_money_block.py -q
  .\.venv\Scripts\pytest.exe tests/ -q              # tests/ only
  python main.py --new --dry-run                    # inspect state + menu
  python main.py --new --max-steps 20 --log-level INFO

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Sleep ---
  # only write_diary_and_go_sleep at step >= 19 (bedroll/room)
  # forced sleep at step 20, no bed required
  # no ordinary sleep; no critical-HP sleep valve

  # --- Hands ---
  # [HANDS] = weapon + one auxiliary item (max 2)
  # [INVENTORY] = [HANDS] + [BACKPACK]
  # combat uses slot-1 weapon only
  # eat/drink auto-pick from backpack into slot 2

  # --- Veteran ---
  # village only, d6 >= 5, cooldown 10 game days

  # --- Dialog anti-loop ---
  # 3 identical dialog actions in a row -> exit, -1 HP, inject
  # "Shut up, kid! I don't have time for this!"

  # --- Trade no-money block ---
  # per trader; 3 failed buys with insufficient coin -> dialogue cut,
  # trader silent until next day, inject
  # "STOP! You have no money! Go work!"

TEST COUNTER: 3093 passed
  Last verified: 24.11.2026

=====================================================================
END OF HANDOFF 28.
=====================================================================
