=====================================================================
BURT -- HANDOFF 15
Date: 15.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-14 (fully closed by this)
Uncommitted at handoff write: NO
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. Simplified LLM API configuration — three parameters only.

   BEFORE (confusing):
     - BACKEND = "lm_studio" | "openai"
     - LM_STUDIO_URL
     - OPENAI_API_URL
     - OPENAI_API_KEY
     - MODEL
     - _BASE_URLS dict in llm_client.py
     - Backend switching logic

   AFTER (simple):
     - LLM_BASE_URL = "http://localhost:1234/v1" (or any API)
     - LLM_API_KEY = "" (or "sk-...")
     - LLM_MODEL = "local-model" (or "gpt-4o-mini", etc.)
     - No backend switching, no _BASE_URLS dict
     - Authorization header sent if API_KEY is non-empty

   How to use:
     - Set env vars: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
     - Or edit config.py directly
     - Works with ANY OpenAI-compatible API (OpenAI, Together, Groq, etc.)

2. Files changed:
   - config.py: replaced BACKEND/LM_STUDIO_URL/OPENAI_* with BASE_URL/API_KEY/MODEL
   - burt/llm_client.py: removed _BASE_URLS, backend switching; simplified to single URL
   - tests/test_openai_api.py: updated tests for new config (9 tests)
   - tests/test_llm_client.py: removed TestBackendSwitching class
   - .env.example: updated with three-parameter format

3. Test results: 1638 passed, 0 failed
   (1633 from HANDOFF-14 + 9 new - 4 removed = 1638)

---------------------------------------------------------------------
CURRENT STATE (15.11.2026, end of session)
---------------------------------------------------------------------

- 1638 passed, 0 failed
- LLM API simplified to three parameters
- Epitaphs system fully implemented (HANDOFF-14)
- Resurrection mechanic working

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1638 pass (verify)
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

  # --- LLM API simplified (HANDOFF-15) ---
  # Three parameters only:
  #   LLM_BASE_URL=http://localhost:1234/v1
  #   LLM_API_KEY=""
  #   LLM_MODEL="local-model"
  #
  # config.py: BASE_URL, API_KEY, MODEL (env vars: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
  # llm_client.py: _BASE_URL, _MODEL, _API_KEY (no _BASE_URLS, no BACKEND)
  # Authorization header sent if _API_KEY is non-empty
  #
  # Works with: LM Studio, OpenAI, Together AI, Groq, LiteLLM, any OpenAI-compatible API
  #
  # .env.example updated with examples for all providers

  # --- From HANDOFF-14 (unchanged) ---
  - Epitaphs store: burt/epitaphs.py (load, save, add, get_all, get_last)
  - Resurrection: burt/resurrection.py (check_resurrection: 1d6, roll=6 -> success)
  - _write_epitaph: saves to epitaphs.json + meta["memory"]
  - make_new_state: reads last epitaph as memory
  - game_loop: resurrection check after game_over (continue on success, new life on fail)
  - _write_memory_summary: at life >= 10, calls LLM with MEMORY_SUMMARY_PROMPT
  - _build_system_prompt: injects memory_summary into BURT_SYSTEM_PROMPT
  - _check_hunger_death: simplified (resurrection moved to game_loop)
  - New tests: tests/test_epitaphs.py (15), tests/test_resurrection.py (15),
    tests/test_memory_transfer.py (11), tests/test_openai_api.py (9)

TEST COUNTER: 1638 passed
  Last verified: 15.11.2026

=====================================================================
END OF HANDOFF 15.
=====================================================================
