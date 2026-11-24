=====================================================================
BURT -- HANDOFF 29
Date: 24.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Code: v0.9.6-BETA
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-28 (hands/backpack, diary-only sleep, trade anti-loop)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. `remember` tool removed
   - the tool confused the model and duplicated the memory channel;
   - removed from TOOL_KEYS, _TOOL_LABELS, every menu, _execute_tool
     and _ACTION_SYNONYMS;
   - `format_memory()` and the `[MEMORY]` block are gone;
   - TOOL_KEYS is now: quest_log / inventory / status / diary / map.

2. Memory of past lives: one inject per life
   - old behaviour: memory was appended to the sensory report on EVERY
     turn when life > 1, and memory_summary lived in the system prompt;
   - new behaviour: a single inject at day 1 / step 0 of a new life,
     gated by hidden["memory_injected"] (set after the inject);
   - the inject contains both blocks:
       You remember your past life:
       <meta.memory>

       Across all your lives you understood:
       <meta.memory_summary>
   - memory_summary removed from _build_system_prompt;
   - field added to create_initial_state and _ensure_runtime_fields.

3. `scroll` renamed to `quest_log`
   - action key: scroll -> quest_log;
   - menu label: "Quest scroll" -> "Quest log";
   - output header: [SCROLL] -> [QUESTS];
   - format_scroll -> format_quest_log;
   - test file renamed: test_scroll_tool.py -> test_quest_log_tool.py.

4. Diary vs quest log disambiguation
   - BURT_SYSTEM_PROMPT: "Quest log lists active quests... It is NOT the
     diary." + "Never look for quests in the diary.";
   - DIARY_PROMPT: "check inventory, quest log, and map";
   - morning inject: "Check your diary, quest log and inventory."

5. Documentation
   - README: v0.9.6-BETA, 3094 tests, tools section, memory section,
     version history;
   - ТЗ/known_issues.md: #12 tools updated, #16 memory, summary and
     verification refreshed;
   - rules/*: quest log, tools, memory;
   - CyrDict.md: [QUESTS] added;
   - this HANDOFF-29.

---------------------------------------------------------------------
CURRENT STATE (24.11.2026, end of session)
---------------------------------------------------------------------

- .\.venv\Scripts\pytest.exe -q  ->  3094 passed
- No live LLM run after these changes.
- Uncommitted at handoff write: YES.

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe -q                     # 3094 passed
  .\.venv\Scripts\pytest.exe tests/test_quest_log_tool.py tests/test_tools_menu.py tests/test_diary_epitaph.py tests/test_memory_transfer.py tests/test_prompts.py -q
  python main.py --new --dry-run                    # inspect state + menu

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Tools ---
  # quest_log / inventory / status / diary / map
  # no remember tool
  # [QUESTS] = active quests, deadlines, progress, giver hidden
  # [INVENTORY] = [HANDS] + [BACKPACK]

  # --- Memory ---
  # injected once: day 1, step 0, hidden["memory_injected"]
  # "You remember your past life: ..."
  # "Across all your lives you understood: ..."
  # never in the system prompt

  # --- Prompt rules ---
  # quest log is NOT the diary
  # never look for quests in the diary

TEST COUNTER: 3094 passed
  Last verified: 24.11.2026

=====================================================================
END OF HANDOFF 29.
=====================================================================
