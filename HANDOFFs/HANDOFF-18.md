=====================================================================
BURT -- HANDOFF 18
Date: 20.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-17 (TZ-9/TZ-10 already committed)
Uncommitted at handoff write: YES (logging feature, see below)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

1. Known issues refreshed (docs):
   - `ТЗ/known_issues.md` rewritten from code evidence (file:line),
     24 open issues at that moment, 5 stale claims corrected.

2. §38/§39 logging implemented (priority C from the plan).
   Old `burt/game_logger.py` (one JSON per turn in LOGS/) DELETED.

   New modules:
   - burt/trace.py — session_uuid / turn_uuid / call_uuid / floor / seq
   - burt/plugin_log.py — JSONL technical log
   - burt/game_session.py — gameplay log (append-only, synchronous)

   Technical log:
   - logs/plugin_YYYY-MM-DD_HH.jsonl, one line = one event
   - 12h bucket rotation (00 and 12), old files never deleted
   - record: seq, ts (ms), level, session_uuid, turn_uuid, call_uuid,
     floor, layer, event, data
   - layers: react / tool / interaction
   - levels 0-3; level 0 only when DEBUG=True
   - DEBUG=False -> data carries chars + sha256 + 80-char preview
   - RingBuffer(deque, RING_BUFFER_SIZE=20) for crash reports
   - asyncio.Queue + writer task; sync mode when no loop is running
   - queue overflow -> synchronous write + log_queue_full (level 2)
   - crashes/crash_<ts>_<turn_uuid>.log: header, ring dump, traceback
   - session_summary (warn_count, error_count, floors_total, session_uuid)
   - atexit + SIGINT/SIGTERM flush (install_signal_handlers)

   Gameplay log:
   - game_session.jsonl next to state.json (config.GAME_SESSION_PATH)
   - one line per turn: ts, uuids, floor, day, step, mode, location,
     prompt, response, action_key/label, events, hp, hp_max, game_over
   - append_special() for death / resurrection
   - flush() every line; fsync optional (config.LOG_FSYNC)

3. main.py wiring:
   - run_turn(..., game_session=, plugin=, trace=) — all optional
   - layers: turn_start -> state_change -> llm_request -> llm_response ->
     parse_ok/parse_warn -> tool_call -> tool_result -> turn_complete
   - exceptions from LLM -> plugin.die() + crash report, re-raised
   - game_loop: loop_start, init->running, running->stopped
   - main(): builds Trace + PluginLogger + GameSessionLog from config
   - dry_run writes nothing to any log

4. config.py:
   - GAME_SESSION_PATH, LOG_PREVIEW_CHARS, LOG_QUEUE_MAXSIZE, LOG_FSYNC
   - DEBUG, LOG_LEVEL, LOG_DIR, CRASH_DIR, LOG_ROTATE_HOURS,
     RING_BUFFER_SIZE are now actually read (were dead flags)
   - .gitignore: game_session.jsonl

5. Tests: 1826 -> 1938 passed
   - tests/test_trace.py (20)
   - tests/test_plugin_log.py (48)
   - tests/test_game_session.py (19)
   - tests/test_logging_integration.py (14)
   - tests/test_config.py: +5 logging path tests

---------------------------------------------------------------------
CURRENT STATE (20.11.2026, end of session)
---------------------------------------------------------------------

- 1938 passed, 0 failed
- Logging matches §38/§39 (see known_issues #1, now CLOSED)
- known_issues: 23 open (was 24)
- Everything else unchanged: NPC spawn, quests, trade, magic, XP,
  skills, weapons, faith are still missing (see known_issues)

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 1938 pass
  python main.py --new --max-steps 5            # writes logs/
  python main.py --new --dry-run                # no log writes
  git --no-pager log --oneline -5

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Logging (§38, §39) ---
  # plugin_*.jsonl: technical, async, 12h buckets, levels 0-3
  # game_session.jsonl: gameplay, sync, one line per turn
  # uuid chain: session (run) -> turn (floor) -> call (per LLM/tool call)
  # DEBUG=True  -> data has full prompt/response
  # DEBUG=False -> prompt_chars/prompt_hash/prompt_preview (80)
  # ERROR -> crash_<ts>_<turn_uuid>.log with last 20 ring lines + traceback
  # event() never writes crash reports, die() does (keeps ONE file per error)
  # state_change(): running->waiting_llm is DEBUG, waiting_llm->running INFO,
  #                 any ->error/crashed is ERROR (goes through die())
  # sync mode: no asyncio loop -> every line written straight to disk

TEST COUNTER: 1938 passed
  Last verified: 20.11.2026

=====================================================================
END OF HANDOFF 18.
=====================================================================
