=====================================================================
BURT -- HANDOFF 16
Date: 18.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-15 (fully closed by this)
Uncommitted at handoff write: NO
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. HANDOFF-15 fully closed. All priorities resolved:
   - TZ-4 (Gemma fallback + 404 fix): committed
   - TZ-5 (wipe LLM history between lives): committed

2. TZ-4: Gemma 3n system-role fallback + 404 NameError fix
   - burt/llm_client.py: added _build_messages() helper
     - If _engine_rejects_system_role=True → folds system into user
     - If False → standard [system, ...history, user]
   - call_llm(): on "roles must alternate" error → sets flag=True
     and retries with folded messages (system+user combined)
   - Subsequent calls automatically use folded mode (no re-detection)
   - create_chat_completion(): 404 fix — use _BASE_URL constant
     instead of bare `base_url` (NameError)
   - Also passes headers to alt URL retry

3. TZ-5: Wipe LLM history between lives
   - main.py game_loop: added `history = []` after make_new_state()
     on FAILED resurrection (new life)
   - Fixes bug: combat context from previous life leaked into new life
   - SUCCESS resurrection keeps history (same life, same context)

4. World map fix: crossroads + thicket now reachable
   - config.py LOCATION_TYPE_ROLLS[6]: replaced two "village" with
     "crossroads" and "thicket"
   - burt/world.py roll_location_type(): added roll_size==5 → crossroads,
     roll_size==6 → thicket
   - All 11 types from LOCATION_TYPES now covered by rolls

5. Files changed:
   - burt/llm_client.py: _build_messages(), Gemma fallback, 404 fix
   - config.py: LOCATION_TYPE_ROLLS[6] updated, env vars removed
   - main.py: history = [] wipe on new life
   - burt/world.py: roll_location_type() crossroads/thicket
   - tests/test_llm_client.py: TestGemmaFallback class (11 new tests)
   - tests/test_api_config.py: renamed from test_openai_api.py, env tests
   - tests/test_config.py: test_all_11_types_in_rolls
   - tests/test_world.py: crossroads/thicket tests
   - tests/test_main_lives.py: NEW — 3 tests for history wipe
   - .gitignore: added epitaphs.json, .gigacode_vsc/, burt/api_config.py
   - .env.example: updated with api_config.py instructions
   - burt/api_config.py.example: NEW — template for API key

6. Test results: 1646 passed, 0 failed
   (1638 from HANDOFF-15 + 14 new - 6 removed = 1646)

---------------------------------------------------------------------
CURRENT STATE (18.11.2026, end of session)
---------------------------------------------------------------------

- 1646 passed, 0 failed
- LLM API: api_config.py (separate file, not committed) + config.py
- Gemma 3n auto-detection + fallback working
- LLM history wiped between lives (bug fix)
- World map: all 11 location types reachable
- Epitaphs system fully implemented (HANDOFF-14/15)
- Resurrection mechanic working

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1646 pass (verify)
  python main.py --new --max-steps 20 --log-level INFO
  python main.py --new --dry-run                # inspect state only
  git --no-pager log --oneline -5               # recent commits
  git status

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

  # --- LLM API: separate api_config.py (HANDOFF-15 + TZ-4) ---
  # API ключ в burt/api_config.py (НЕ коммитится, в .gitignore)
  # Скопируйте burt/api_config.py.example → burt/api_config.py
  # Если API_KEY пустой → LM Studio (localhost:1234)
  # Если API_KEY есть → внешний API (OpenAI, Together, Groq, aiTunnel)
  #
  # llm_client.py читает из api_config при импорте
  # Authorization: Bearer <key> отправляется если API_KEY не пустой

  # --- TZ-4: Gemma 3n system-role fallback ---
  # _build_messages(system, user, history, reject_system)
  # reject_system=True → folds system into user: "SYS\n\nUSR"
  # reject_system=False → standard [system, ...history, user]
  # On "roles must alternate" error → sets _engine_rejects_system_role=True
  # Subsequent calls auto-use folded mode
  # 404 fix: use _BASE_URL constant (was bare base_url → NameError)
  # New tests: tests/test_llm_client.py TestGemmaFallback (11 tests)

  # --- TZ-5: Wipe LLM history between lives ---
  # game_loop: after make_new_state() on FAILED resurrection → history = []
  # SUCCESS resurrection keeps history (same life)
  # New tests: tests/test_main_lives.py (3 tests)

  # --- World map fix: crossroads + thicket reachable ---
  # config.py LOCATION_TYPE_ROLLS[6]: village,village,crossroads,thicket
  # world.py roll_location_type(): roll_size==5→crossroads, ==6→thicket
  # All 11 LOCATION_TYPES now covered by rolls
  # New tests: tests/test_world.py, tests/test_config.py

  # --- From HANDOFF-15 (unchanged) ---
  # Epitaphs store: burt/epitaphs.py (load, save, add, get_all, get_last)
  # Resurrection: burt/resurrection.py (check_resurrection: 1d6, roll=6 -> success)
  # _write_epitaph: saves to epitaphs.json + meta["memory"]
  # make_new_state: reads last epitaph as memory
  # game_loop: resurrection check after game_over (continue on success, new life on fail)
  # _write_memory_summary: at life >= 10, calls LLM with MEMORY_SUMMARY_PROMPT
  # _build_system_prompt: injects memory_summary into BURT_SYSTEM_PROMPT
  # _check_hunger_death: simplified (resurrection moved to game_loop)

TEST COUNTER: 1646 passed
  Last verified: 18.11.2026

=====================================================================
END OF HANDOFF 16.
=====================================================================
