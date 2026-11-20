# Known Issues — BURT

Spec: v0.7.0 · Code: `main @ 886d31f` · Verified: 20.11.2026 · Tests: 1826 passed

This file lists every divergence between the code and spec v0.7.0.
Nothing here is a guess: each entry has a `file:line` evidence pointer.

Status legend:

- **NOT IMPLEMENTED** — no code exists
- **CORE ONLY** — pure logic module exists, but nothing in the game calls it
- **PARTIAL** — works, but only part of the spec behaviour is covered
- **DEVIATION** — implemented differently on purpose (see "Intentional deviations")
- **ACCEPTED** — known, decided not to change
- **WON'T FIX** — out of scope / model limitation

---

## 🔴 CRITICAL — block gameplay

### 1. Logging — DONE (§38, §39) — CLOSED 20.11.2026

Implemented in `burt/trace.py`, `burt/plugin_log.py`, `burt/game_session.py`.

- `logs/plugin_YYYY-MM-DD_HH.jsonl`, JSONL, one line = one event, 12h buckets
- `session_uuid` / `turn_uuid` / `call_uuid` / floor / monotonic `seq`
- Layers: `react` / `tool` / `interaction`
- Ring buffer (deque, `RING_BUFFER_SIZE`) for crash reports
- Async writer via `asyncio.Queue`, sync fallback without a loop
- `crashes/crash_<ts>_<turn_uuid>.log` with ring dump + traceback
- `game_session.jsonl`, append-only, synchronous, next to state.json
- Levels 0-3, DEBUG payload policy (chars + sha256 + 80-char preview)
- `session_summary` with warn/error/floors counters, atexit + SIGINT/SIGTERM

Old `burt/game_logger.py` (one JSON per turn in `LOGS/`) is deleted.
Config flags `DEBUG`, `LOG_LEVEL`, `LOG_DIR`, `CRASH_DIR`, `LOG_ROTATE_HOURS`,
`RING_BUFFER_SIZE` are now actually read, plus `GAME_SESSION_PATH`,
`LOG_PREVIEW_CHARS`, `LOG_QUEUE_MAXSIZE`, `LOG_FSYNC`.
Tests: `test_trace.py`, `test_plugin_log.py`, `test_game_session.py`,
`test_logging_integration.py` (+112).

**Still open from the old entry:** the spec's `memory.json`, `quests.json`,
`diary.json` files — tracked separately in #16.


**Evidence:** `burt/plugin_log.py`, `burt/game_session.py`, `burt/trace.py`
(`main.py:765` used to wire the old `GameLogger(Path("LOGS"))`, now removed)

**Spec requires (all implemented):**

- JSONL: one line = one event
- `session_uuid` / `turn_uuid` / `call_uuid` tracing
- Three layers: `react` / `tool` / `interaction`

- Ring buffer `maxlen=20` for crash reports
- Async writer via `asyncio.Queue`
- 12h rotation: `logs/plugin_YYYY-MM-DD_HH.jsonl`
- Crash reports: `crashes/crash_<ts>_<turn_uuid>.log`
- `game_session.jsonl`, append-only, synchronous
- Alert levels 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR
- Final `session_summary` line with warn/error counters

**Code (was):** one JSON file per turn (`LOGS/day_NNN/turn_NNNNNN.json`), `threading.Lock`, day-based rotation, no UUIDs, no layers, no ring buffer, no crash dumps, no `game_session.jsonl`, no alert levels, no session summary.

**Config flags:** `DEBUG`, `LOG_LEVEL`, `LOG_DIR`, `CRASH_DIR`, `LOG_ROTATE_HOURS`, `RING_BUFFER_SIZE`, `GAME_SESSION_PATH`, `LOG_PREVIEW_CHARS`, `LOG_QUEUE_MAXSIZE`, `LOG_FSYNC` — now consumed by `burt/plugin_log.py` and `burt/game_session.py`.


### 2. NPC spawn by location is missing, so dialogue is unreachable in a real game (§32) — NOT IMPLEMENTED

**Evidence:** `state.py:138` (`npcs_here: []`), `loop.py:127` (reader only), `test_npc_integration.py:154` (the only writer — a test that injects `npcs_here` manually).

**Spec requires:** 12 roles spawned procedurally by location (village / river / road / forest / temple / dungeon), rare roles on d6 >= 5, one quest per NPC on d6 >= 4.

**Code:** `burt/npc.py` (349 lines) and the dialog menu/execution path in `loop.py` are complete, but nothing ever fills `hidden["npcs_here"]`, so `talk_to_*` never appears in the menu.

**Needed:** role spawn table + fill `npcs_here` on node entry.

### 3. Quests are never issued or completed (§18, §36) — CORE ONLY

**Evidence:** `burt/quests.py` (423 lines) is a complete core, but `main.py:520-521` calls only `expire_blockades` / `expire_deceit_penalties`.

**Spec requires:** role quest pools (bring / kill / find / talk / help), 3 quests per day per location, deadline `1d6 -> 3/5/7` days, partial-completion roll, "scroll" tool to read active quests, reputation +1 on completion / -2 on failure.

**Code:** no `quest_give` / `quest_progress` / `quest_complete` call anywhere in the game. `quests_templates.json` contains only the faith chains (`pala_1..3`, `heretic_1..3`) — no role quest templates at all, and no "scroll" menu action. `dialog_state["quest_state"]` is hardcoded `"available"` (`loop.py:1037`), so the quest reply branch always answers as if a quest is available.

### 4. Trade is not wired (§19, §35) — CORE ONLY

**Evidence:** `burt/trade.py` (183 lines) + `tests/test_trade.py` (345 lines); `grep "trade\."` outside `trade.py`/tests returns zero hits.

**Spec requires:** buy/sell menu at the 7 trade roles, role price modifiers, location modifier +/-25% rolled once on entering a location, `sell = floor(floor(base*0.5)*mod)`, tavern room purchase.

**Code:** no buy/sell actions, no price-modifier roll, no room purchase, loot items have no sell path.

---

## 🟠 HIGH — break progression and subsystems

### 5. XP and levels do not exist (§7) — NOT IMPLEMENTED

**Evidence:** `state.py:105-124` (no `level`, no `xp`), `grep '\["level"\] ='` returns nothing, while `loop.py:1248`, `1312`, `1357`, `1401` read `visible.get("level", 1)`.

**Spec requires:** `cap(level) = 10 * 1.5^(level-1)`, `kill_exp = 5`, HP +2 / MP +1 per level, base HP 10 / MP 3.

**Side effect (important):** level is always 1, so the TZ-10 cap (`level < 5 -> single enemy`) is permanently active — packs of 2-3 enemies never appear in a real game.

### 6. Skill system does not exist (§8) — NOT IMPLEMENTED

**Evidence:** `sensory.py:177-187` (`[SKILLS]` is always `empty`), `state.py:134` (`skills_raw` stays `[]`), `loop.py:999-1005` (`master`/`modifier` always 0).

**Spec requires:** 10 skills, +1 to the die roll per 5 skill levels, +1 to damage range per 2 weapon-mastery levels, mastery thresholds 5 and 10, skills hidden until 1/10, training = +1 skill once per life.

### 7. Weapon damage table does not exist (§20) — NOT IMPLEMENTED

**Evidence:** `combat.py:119-120` (`damage_min=1`, `damage_max=2` defaults); `dice.py` has no weapon table.

**Spec requires:** damage table for 10 weapon types, quality shifts the range by +/-1, mastery modifiers, ban on non-humanoid weapons (moot without weapons).

**Code:** Burt always fights with fists; inventory weapons have no effect.

### 8. Magic is unreachable (§9) — CORE ONLY

**Evidence:** `burt/magic.py` (202 lines) is not imported by the game; `state.py:148` (`spells = {element: None, alignment: None}`) is never granted; `loop.py:992-997` derives `spells_available` from it.

**Spec requires:** three conditions (staff + spell + teacher), 2 spells per life, light/dark mutually exclusive, cast = 1 MP / 3-6 damage, teacher events for mage / cleric / necromancer.

**Code:** "Cast" can never appear in the combat menu in a real game.

### 9. Reputation is effectively static (§16) — PARTIAL

**Evidence:** `quests.py:276` is the only writer (`-1` on failed deception).

**Spec requires:** dialogue success +1, neutral 0, fail -1, anger -2; quest complete +1, quest fail -2; killing a resident -5 overall and -10 for the victim's role; effects at |rep| >= 5 (prices, tone, quest availability).

**Code:** dialogue and quests never change reputation; no effects are applied anywhere.

### 10. Faith, killer status and crime do not exist (§33, §34) — NOT IMPLEMENTED

**Evidence:** `grep faith|paladin|heretic|killer` matches only `npc.resolve_heretic_deception`.

**Spec requires:** statuses neutral / paladin / heretic / killer, paladin and heretic chains (K1-K2-K3), god's punishment `1 * level`, killing a resident blocks quests for life, cleric and necromancer hostility, killer skips chain steps 1-2.

**Code:** no status field in state at all, so nothing else can be layered on top.

### 11. Random events, preacher and effects do not exist (§10, §13) — NOT IMPLEMENTED

**Evidence:** `state.py:139` (`events_here`), `state.py:147` (`pending_events`) — never read or written by any module.

**Spec requires:** random events on travel (bad / nothing / good), preacher event with curse/blessing for 3 turns, mage event once per life, temple/dungeon rare spawns.

**Code:** no event spawner; `blessed` / `cursed` are never granted; `hidden.effects_detail` is never used; `BurtStats.modifier` is always 0.

---

## 🟡 MEDIUM — format and behaviour drift

### 12. Tools menu is missing (§26) — PARTIAL

**Evidence:** `loop.py:157` — the only free tool is `osmotret` (look around).

**Spec requires:** free tools — look around (once per turn, not in combat), scroll, inventory, status, remember, diary; tools must be available in dialog and combat menus too.

**Also:** "re-ask once when `CHOICE` is missing" is not implemented — `parse_choice` (`loop.py:414-480`) goes straight to rfind/synonym heuristics and then to the first menu item.

### 13. Sleep availability ignores bedroll / tavern room (§5) — DEVIATION

**Evidence:** `sleep.py:43` `is_sleep_available()` is never called; `loop.py:166-175` offers "Sleep" at `step >= 19` or HP < 25%.

**Cause:** a room or bedroll cannot be bought while trade is not wired (see #4).

**Spec requires:** sleep only with a bedroll in inventory or a paid tavern room; otherwise the "sleep" item is absent from the menu.

### 14. Day counter advances during dialogue (§3) — DEVIATION

**Evidence:** `loop.py:1039` (enter dialog, +1), `loop.py:1138` (each reply, +1), `loop.py:1068` (exit, +1).

**Spec requires:** the whole dialogue is one action; entering freezes the counter; exit is free.

### 15. Start inject from the rules file is missing (§37) — NOT IMPLEMENTED

**Evidence:** `rules/*.md` exists but nothing reads it; `main.py` has no rules injection before the first sensory report.

**Spec requires:** the rules text is injected as the first message of a new life, before the system prompt and the first sensory report.

### 16. State files of §2 do not match the spec — PARTIAL

**Missing:** `game_session.jsonl`, `memory.json`, `quests.json`, `diary.json`.

**Diary:** lives as a single string in `hidden["diary"]`; spec wants `diary.json` with `entries[]` + `summaries[]`, raw entries going to `game_session.jsonl`.

**5-day summarization:** dropped by design (HANDOFF-13), `DIARY_SUMMARY_PROMPT` is unused.

**Memory:** between lives uses `epitaphs.json` + `meta["memory"]` instead of `memory.json`; `MEMORY_COMPRESS_AT` is unused.

---

## 🟢 LOW — tech debt and cosmetic

### 17. Bandit ignores the first-turn money demand (§23) — NOT IMPLEMENTED

**Evidence:** `grep bandit` in `combat.py` / `loop.py` returns zero hits. Bandit exists only in `bestiary.py` (HP 10, damage 2-4) and in the loot table.

### 18. Enemy tags are declared but never read (§21) — PARTIAL

**Evidence:** `bestiary.py` defines `passive` (bear does not pursue) and `wounded_prey` (boar attacks only a wounded Burt); `combat.py` reads only `no_flee` (line 246) and `staff_penalty` (lines 385, 486).

### 19. Non-humanoid weapon ban is moot (§20) — NOT IMPLEMENTED

No weapon system exists (#7), so `goblin_dagger` / `goblin_staff` cannot be equipped or forbidden either way. Selling them is allowed by the spec and stays allowed.

### 20. Duplicated and dead constants — PARTIAL

- `HUNGER_HUNGRY_AT` / `HUNGER_DEATH_AT` duplicated in `state.py:42-43` and `hunger.py:40`.
- `config.LOCATION_TYPES` and `config.LOCATION_TYPE_ROLLS` are dead: `world.py:36` keeps its own copy, although `config.py:7-8,107` claims `world.py` re-exports them.

### 21. Dead config flags — PARTIAL

Logging flags are live now (`DEBUG`, `LOG_LEVEL`, `LOG_DIR`, `CRASH_DIR`,
`LOG_ROTATE_HOURS`, `RING_BUFFER_SIZE`, `GAME_SESSION_PATH`, `LOG_PREVIEW_CHARS`,
`LOG_QUEUE_MAXSIZE`, `LOG_FSYNC`).

Still never read by the game: `SHOW_HUNGER_TIMER`, `MEMORY_COMPRESS_AT`, `DAY_STEPS`.


### 22. Role key mismatch — PARTIAL

- `peasant_woman` exists in `replicas.json` and in `npc.py` categories, but is missing from `state.ROLE_NAMES` (`state.py:23-36`), so `validate_state` would reject it.
- `ROLE_NAMES` has `mage`, while `replicas.json` uses `mage_event`, so mage reputation can never be keyed correctly (no practical effect yet, see #9).

### 23. World graph has 2-4 exits instead of 4 neighbours (§17) — ACCEPTED

**Evidence:** `world.py:111` `roll_exit_count` (1-2 -> 2 exits, 3-4 -> 3, 5-6 -> 4). Spec says "graph, 4 neighbours". Design choice, kept as is.

### 24. Documentation drift — PARTIAL

`README.md` states 1697 tests, `HANDOFF-1..13`, and "new life cycle in development" (it is implemented). Both `README.md` and this file were stale before this revision.

---

## ⚪ INTENTIONAL DEVIATIONS (decided, not bugs)

| § | Deviation | Where / why |
|---|---|---|
| §4 | Hunger inject fires on EVERY step with `eat=False` (spec: steps 0 and 10 only) | the model saw "Fed: yes" and "you are hungry" at the same time |
| §25, §31 | `SHOW_SLEEP_TIMER` removed, no `Sleep: 15/20` in `[STATE]` | `sleep_counter` was never updated and confused the LLM (HANDOFF-12) |
| §5 | Sleep without bedroll/room | a room cannot be bought until trade is wired (#4) |
| §29 | Diary = one string, overwritten daily, no 5-day summary | HANDOFF-13, deliberate |
| §28 | Memory via `epitaphs.json` + `meta["memory"]` | HANDOFF-15 |
| §26 | No re-ask when `CHOICE` is missing | replaced by rfind + synonym parser |
| §25, §31 | English UI, prompts, replicas | UTF-8 issues in small models |
| §17 | 2-4 exits per node | design choice (#23) |

---

## ✅ CLOSED / WON'T FIX

- **Currency:** single `coin` (§19, §31) — done, enforced by `state.validate_state`.
- **TZ-9:** encounter reveal via "look around", ambush only in thicket — done.
- **TZ-10:** cap spawn at level < 5 — done and committed (`a32d64e`); see #5: level never grows, so the cap is effectively permanent.
- **Combat:** free strike on opening, loot after victory, cast in combat, block counters, dragon breath, shaman MP -> staff — done.
- **Death / resurrection:** 1d6, 2 HP, new life with memory transfer — done.
- **Diary / epitaph / memory summary (10+ lives):** wired to the LLM.
- **`npc.py` dialogue engine:** categories, dice pairs, bonuses, anger lock, bribe, training, heretic deception — implemented; the remaining gap is spawn (#2).
- **`loop.py.back` leftover:** no longer present in `burt/`.
- **Gemma 3n robotic behaviour:** model limitation, WON'T FIX.
- **LLM ignores micro-location context:** cosmetic, open but harmless.

---

## Stale claims corrected in this revision (2026-11-20)

| Old claim | Reality |
|---|---|
| "npc.py NEVER IMPLEMENTED" | `npc.py` exists (349 lines) and is wired into the menu/execution path; the real gap is NPC spawn (#2) |
| "TZ-10 UNCOMMITTED" | committed: `a32d64e` "complete TZ-10..." |
| "`loop.py.back` exists in burt/" | absent |
| "`SHOW_SLEEP_TIMER` missing — minor" | removed on purpose, see Intentional Deviations |
| "chain templates not in code" | `quests_templates.json` has `pala_1..3` / `heretic_1..3`; they are simply never issued (#3) |

---

## Summary

| Severity | Count |
|---|---|
| 🔴 Critical | 3 (was 4; logging closed) |
| 🟠 High | 7 |
| 🟡 Medium | 5 |
| 🟢 Low | 8 |
| ⚪ Intentional deviations | 8 |
| ✅ Closed | 1 (#1 logging) |
| **Total open** | **23** |

---

## Verification

```text
cd E:\Butr-Ai
.\.venv\Scripts\pytest.exe tests/ -q     # 1938 passed
python main.py --new --dry-run           # inspect state + menu, no log writes
python main.py --new --max-steps 5       # logs/plugin_*.jsonl + game_session.jsonl
git --no-pager log --oneline -5
```

