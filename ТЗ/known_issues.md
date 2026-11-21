# Known Issues — BURT

Spec: v0.7.0 · Code: `main @ 323f0d6 + working tree` · Verified: 21.11.2026 · Tests: 2463 passed

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


### 2. NPC spawn by location — DONE (§32) — CLOSED 20.11.2026

Implemented in `burt/npc_spawn.py`, wired through `loop._arrive_at_node()`.

- `ROLE_SPAWN` pools for village / river / road / forest / temple / dungeon
- village: 1-3 roles by d6, no duplicates; temple/dungeon: one fixed role
- river/road: one role, plus a rare role (cleric/necromancer) on d6 >= 5
- spawn is cached per node in `hidden["npcs_by_node"]` — re-entry shows
  the same people; `hidden["npcs_here"]` is the working list
- `bandit` stays a monster (§21), never an NPC
- exploring menu lists `talk_to_*` **together with** exits, search and
  the quest scroll; a revealed encounter (TZ-9) still wins
- Tests: `test_npc_spawn.py` (50), `test_npc_spawn_loop.py` (13)

### 2a. NPC spawn — ORIGINAL ENTRY (kept for history) — NOT IMPLEMENTED

**Evidence:** `state.py:138` (`npcs_here: []`), `loop.py:127` (reader only), `test_npc_integration.py:154` (the only writer — a test that injects `npcs_here` manually).

**Spec requires:** 12 roles spawned procedurally by location (village / river / road / forest / temple / dungeon), rare roles on d6 >= 5, one quest per NPC on d6 >= 4.

**Code:** `burt/npc.py` (349 lines) and the dialog menu/execution path in `loop.py` are complete, but nothing ever fills `hidden["npcs_here"]`, so `talk_to_*` never appears in the menu.

**Needed:** role spawn table + fill `npcs_here` on node entry.

### 3. Role quests — DONE (§18, §36) — CLOSED 20.11.2026 (faith chains still open, see §33)

Implemented in `burt/quests.py`, wired through `loop.py`.

- 22 role quest templates added to `quests_templates.json`
  (7 roles x 3 quests: deliver / kill / visit / talk / help)
- deadline rolled at issue: 1d6 -> 3 / 5 / 7 days (`quests.roll_deadline`)
- `quest_state` comes from `quests.quest_state_for_role()` instead of the
  hardcoded "available" (`available` / `in_progress` / `none`)
- `dialog_quest` issues the quest, and hands it in when it is finished
  (partial hand-in keeps the §18 d6 rule inside `quest_complete`)
- progress hooks: `on_enemy_killed`, `on_enter_location`, `on_talk`,
  `on_quest_completed`, plus `deliver_ready` / `deliver_progress`
- quest scroll tool (§26): free action, no step growth, giver hidden
- `target` is now persisted on the quest record
- Legacy data fix: `pala_2` referenced a non-existent
  `goblin_shaman_staff`; now uses `goblin_staff`
- Tests: `test_quests_roles.py` (35), `test_quests_hooks.py` (18),
  `test_scroll_tool.py` (9), `test_social_integration.py` (8)

**Still open:** faith chains (pala/heretic) are not issued — §33 task.

### 3a. Quests — ORIGINAL ENTRY (kept for history) — CORE ONLY

**Evidence:** `burt/quests.py` (423 lines) is a complete core, but `main.py:520-521` calls only `expire_blockades` / `expire_deceit_penalties`.

**Spec requires:** role quest pools (bring / kill / find / talk / help), 3 quests per day per location, deadline `1d6 -> 3/5/7` days, partial-completion roll, "scroll" tool to read active quests, reputation +1 on completion / -2 on failure.

**Code:** no `quest_give` / `quest_progress` / `quest_complete` call anywhere in the game. `quests_templates.json` contains only the faith chains (`pala_1..3`, `heretic_1..3`) — no role quest templates at all, and no "scroll" menu action. `dialog_state["quest_state"]` is hardcoded `"available"` (`loop.py:1037`), so the quest reply branch always answers as if a quest is available.

### 4. Trade is wired — DONE (§19, §35) — CLOSED 20.11.2026

Implemented in `burt/economy.py` (new, price composition + inventory
stacks + node cache) and `burt/loop.py` (`_build_shop_menu`,
`_open_shop`, `_execute_trade_buy`, `_execute_trade_sell`).

- `dialog_trade` opens a shop sub-mode inside the dialogue; while open the
  menu shows `dialog_buy_<item>` / `dialog_sell_<item>` / `dialog_trade_close`
- buy list = `trade.ROLE_SELLS[role]`, sell list = every inventory item with
  a known price (`BASE_PRICES` or `LOOT_PRICES`)
- price = `floor(base * location * reputation * trade_bonus)` for buys and
  `floor(floor(base * 0.5) * ...)` for sells, computed with exact fractions
  so the floor never depends on float noise
- location modifier (§35): rolled once per node, cached in
  `hidden["prices_by_node"]`; rolled on the first meeting with a trader of
  that node (movement/encounter dice order stays untouched)
- reputation (§16): `price_modifier()` now actually reaches the counter
- `trade_discount` from npc.py is read once per dialogue (20% off)
- `tavern_room` is one-shot goods: `hidden["has_room_tonight"] = True`, no
  inventory item; reset on sleep; second purchase the same night is refused
- `bedroll` is a normal inventory item (§5 gate, see #13)
- loot sells (§22): `goblin_dagger`, `goblin_staff`, `bandage`, `fangs`,
  `pelt`, `low_quality_sword`, `dragon_*`; `bandage` sells for 0 coin per
  the §35 formula (event says so)
- §9 trophy road: two `goblin_staff` sold to the necromancer and he hands
  over a real `staff` (agreement of 20.11.2026)
- a failed purchase (no coin, wrong item) does not advance the step

Tests: `test_economy.py` (33), `test_trade_loop.py` (41).

---

## 🟠 HIGH — break progression and subsystems

### 5. XP and levels — DONE (§7) — CLOSED 20.11.2026

Implemented in `burt/progression.py`, wired through `state.py`, `main.py`,
`sensory.py` and `loop._execute_combat`.

- `visible["level"]` and `visible["xp"]` (running XP for the current life)
- `cap(level) = 10 * 1.5^(level-1)` (exact `Fraction`), `kill_exp = 5`
- the level is derived from cumulative thresholds, so the §7 "total kills
  to level" table is reproduced exactly: 2, 5, 10, 17, 27, 42, 65, 99,
  150, 227, ...
- every level: HP +2, MP +1 (max and current, clamped)
- `loop._award_combat_xp` awards XP for dead enemies at combat end and
  emits `You gain N XP.` / `You reach level N.`
- TZ-10 is now dynamic: the pack cap at `level < 5` really lifts at level 5
- old saves: `main._ensure_runtime_fields` adds level 1 / xp 0
- tests: `test_progression.py`, `test_progression_loop.py`

Note: the per-level list in §7 ("5->6: 11") contradicts its own total table
("6: 27"); the implementation follows the total table and the cap formula.

### 6. Skill system — DONE (§8) — CLOSED 20.11.2026

Implemented in `burt/skills.py`, `burt/weapons.py`, `burt/combat.py`,
`burt/loop.py` and `burt/magic.py`.

- 10 skills: Sword / Club / Spear / Magic + Smithing / Stealth / Search /
  Eloquence / Intimidation / Deception
- weapon mastery is counted per STRIKE, not per hit: 30 strikes for level 1,
  curve x1.5 (`skills.strikes_to_next`)
- +1 to the die roll per 5 skill levels (+2 at level 10); +1 to the damage
  range per 2 weapon-mastery levels (`skills.modifier`, `skills.range_bonus`)
- mastery thresholds 5 / 10 are passed to `dice.resolve_attack` as `master`
- skills stay hidden until level 1 (`visible["skills_visible"]`)
- training gives +1 level (`magic.train` -> `skills.award_level`); the veteran
  now teaches a random weapon skill (sword / club / spear) instead of the
  legacy "Combat" placeholder
- `skills.ensure_state` repairs old records and re-syncs the visible mirror
- tests: `test_skills.py`, `test_combat_equipment.py`

Note: non-combat skills are registered and stored, but §8 defines no per-use
growth for them; they can only be raised by training or quests (future work).

### 7. Weapon damage table — DONE (§20) — CLOSED 20.11.2026

Implemented in `burt/weapons.py`, wired through `loop._build_burt_stats`.

- full §20 table: fists/stone 0-1, goblin dagger 1-2, goblin staff 0-1,
  club 1-2, spear 1-3, swords 1-3 / 2-4 / 3-5, magic 3-6
- quality shifts the range by -1 / 0 / +1; goblin weapons are not gradable
- non-humanoid weapons cannot be used in combat (selling stays allowed)
- the best usable weapon is selected automatically by effective damage range
  (no equip menu exists in the spec)
- `BurtStats.damage_min/max` now come from equipment; casts use the base
  3-6 range plus Magic mastery
- tests: `test_weapons.py`, `test_combat_equipment.py`

### 8. Magic is reachable — DONE (§9) — CLOSED 20.11.2026

Implemented in `burt/magic.py` (state + training), `burt/npc_spawn.py`
(mage spawn) and `burt/loop.py` (training reply, cast gate).

- three conditions (§9) are now enforced by `magic.cast_ready`:
  `staff` (inventory or `hidden["has_staff"]`) + at least one spell +
  `hidden["teacher_found"]`; `cast` appears in the combat menu only then
- training: `cleric -> light`, `necromancer -> dark`,
  `mage_event -> his element`; limits 1 element + 1 alignment per life,
  light and dark mutually exclusive; once per teacher per life
  (`hidden["trained_by"]`)
- mage element is rolled 1d4 at SPAWN time (`magic.record_teacher_spawn`),
  cached in `hidden["magic"]["teachers"]["mage_event"]["element"]`
- wandering mage spawn: temple / dungeon, d6 >= 5, at most once per life
  (`npc_spawn.maybe_add_mage`); runs after the fixed role, so the movement
  and NPC dice order is unchanged
- training also raises a skill (`Magic`, or a random weapon skill for the
  veteran), 1/10 and up to 10 (§32, §8); visible through
  `visible["skills_visible"]`
- staff sources: buy from mage / necromancer (100 coin) or the trophy road
  (two `goblin_staff` sold to the necromancer)
- cast itself was already implemented in combat (§23): 1 MP, 3-6 damage

Not in this scope (tracked separately): weapon-damage table (#7), full
10-skill system (#6), faith chains (#10).

Tests: `test_magic_wiring.py` (34).

### 9. Reputation — DONE (§16) — CLOSED 20.11.2026

Implemented in `burt/reputation.py`, wired through `loop.py`.

- per-role range -10..+10 with clamping (`reputation.change`)
- dialogue: success +1, neutral 0, fail -1, anger -2
  (`reputation.dialogue_delta`), applied once per dialogue
- quest completed +1 (`QUEST_DELTA_OK`); quest failed -2
  (`QUEST_DELTA_FAIL`, ready for the fail path)
- effects: `price_modifier()` (0.9 / 1.0 / 1.1) and `can_give_quests()`
  (rep <= -5 blocks quests, used by `quests.quest_state_for_role`)
- tests: `test_reputation.py` (30)

### 9a. Reputation — ORIGINAL ENTRY (kept for history) — PARTIAL

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

**Code:** no event spawner; `blessed` / `cursed` are never granted; `hidden.effects_detail` is never used; `BurtStats.modifier` now carries the weapon-skill bonus (§8), but no event/curse/blessing modifies it yet.

---

## 🟡 MEDIUM — format and behaviour drift

### 12. Tools menu is missing (§26) — PARTIAL

**Evidence:** `loop.py:157` — the only free tool is `osmotret` (look around).

**Spec requires:** free tools — look around (once per turn, not in combat), scroll, inventory, status, remember, diary; tools must be available in dialog and combat menus too.

**Also:** "re-ask once when `CHOICE` is missing" is now implemented:
`loop.parse_choice_strict` + one retry with `loop.INVALID_CHOICE_KICK` in
`main.run_turn`, then `loop.fallback_action` (block → osmotret →
dialog_exit → first item), new_bug §8.

### 13. Sleep availability honours bedroll / tavern room — DONE (§5) — CLOSED 20.11.2026

`sleep.is_sleep_available(step, in_combat, has_bedroll, has_room)` is now the
gate of the menu entry (`loop._sleep_available`).

- `sleep` appears only from step 19, outside combat, with a `bedroll` in the
  inventory or `hidden["has_room_tonight"]`
- `write_diary_and_go_sleep` requires the same gate plus step >= 19
- a paid room is consumed by sleep (`has_room_tonight = False`) in both
  `loop` and `main._do_sleep`
- **kept deviation:** below step 19 a Burt with critical HP (< 25%) may still
  sleep without a bed — see the deviations table

### 14. Day counter advances during dialogue (§3) — DONE — CLOSED 20.11.2026

The whole dialogue is one action now (new_bug §1):

- `talk_to_*` and every dialog action (replies, quests, training, trade,
  buys, sells, closing the shop) keep `hidden["step"]` unchanged;
- only `dialog_exit` ticks, through the single `loop._finish_dialog`;
- food is unavailable in dialog mode (menu and routing);
- `Session.say()` now advances the dialogue turn, so the anger lock
  expires and `dialog_exit` reopens after two replies;
- tests: `test_dialogue_single_action.py`.

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

Still never read by the game: `SHOW_HUNGER_TIMER`, `MEMORY_COMPRESS_AT`.
(`DAY_STEPS` *is* read: `state.validate_state` enforces the maximum and
`main.run_turn` clamps the step while a step-20 fight is ongoing.)


### 22. Role key mismatch — PARTIAL

- `peasant_woman` exists in `replicas.json` and in `npc.py` categories, but is missing from `state.ROLE_NAMES` (`state.py:23-36`), so `validate_state` would reject it.
- `ROLE_NAMES` has `mage`, while `replicas.json` uses `mage_event`. **Fixed for reputation and trade:** `loop._REP_ROLE_ALIAS` maps `mage_event -> mage`, so the mage's shop and reputation are keyed correctly (see `test_magic_wiring.py::TestMageShop`). The raw replica key is still `mage_event` in `npcs_here`.

### 23. World graph has 2-4 exits instead of 4 neighbours (§17) — ACCEPTED

**Evidence:** `world.py:111` `roll_exit_count` (1-2 -> 2 exits, 3-4 -> 3, 5-6 -> 4). Spec says "graph, 4 neighbours". Design choice, kept as is.

### 24. Documentation drift — PARTIAL

README was refreshed in v0.8.9-BETA: version, 2457 tests, HANDOFF-1..22,
the finished life cycle, the new_bug mechanics and the "Что дальше"
section now match the code. Remaining drift: the module/test lists in
README are not exhaustive, and older HANDOFFs keep their historical
notes.

---

## ⚪ INTENTIONAL DEVIATIONS (decided, not bugs)

| § | Deviation | Where / why |
|---|---|---|
| §4 | Hunger inject fires on EVERY step with `eat=False` (spec: steps 0 and 10 only) | the model saw "Fed: yes" and "you are hungry" at the same time |
| §25, §31 | `SHOW_SLEEP_TIMER` removed, no `Sleep: 15/20` in `[STATE]` | `sleep_counter` was never updated and confused the LLM (HANDOFF-12) |
| §5 | Below step 19 a Burt with critical HP (< 25%) may sleep without a bed | safety valve; a dying model kept walking into death without it (kept after #13) |
| §29 | Diary = one string, overwritten daily, no 5-day summary | HANDOFF-13, deliberate |
| §28 | Memory via `epitaphs.json` + `meta["memory"]` | HANDOFF-15 |
| §26 | No re-ask when `CHOICE` is missing | replaced by rfind + synonym parser |
| §25, §31 | English UI, prompts, replicas | UTF-8 issues in small models |
| §17 | 2-4 exits per node | design choice (#23) |

---

## ✅ CLOSED / WON'T FIX

- **Currency:** single `coin` (§19, §31) — done, enforced by `state.validate_state`.
- **TZ-9:** encounter reveal via "look around", ambush only in thicket — done.
- **TZ-10:** cap spawn at level < 5 — done and committed (`a32d64e`); now dynamic, level really reaches 5+ (#5).
- **Combat:** free strike on opening, loot after victory, cast in combat, block counters, dragon breath, shaman MP -> staff — done.
- **Death / resurrection:** 1d6, 2 HP, new life with memory transfer — done.
- **Day rollover after a resurrection (P0, 21.11.2026):** forced sleep fires at
  step >= 20 (the transitional 20->21 tick after an action), the step is clamped
  while a step-20 fight is ongoing, and `state.json` is written *after* the
  resurrection / new life instead of before it. Resurrection mercy is one per
  day (the flag is now read). The live log `Gemma 4-E4B(log_of_life_x4)_3.txt`
  (step 20 + combat + death + roll 6) no longer produces
  `ValueError: step (N) > maximum (20)`. Epitaphs are written only on a final
  death (roll != 6). Regression: `tests/test_resurrection_day_end.py`.
- **Diary / epitaph / memory summary (10+ lives):** wired to the LLM.
- **`npc.py` dialogue engine:** categories, dice pairs, bonuses, anger lock, bribe, training, heretic deception — implemented; the remaining gap is spawn (#2).
- **Trade (§35):** shop sub-mode, three-modifier prices, tavern room, loot selling, trophy staff road — done (#4).
- **Magic (§9):** staff + spell + teacher gate, teacher spawn, light/dark lock, skill growth — done (#8).
- **XP / levels (§7):** `visible.level/xp`, exact cap curve, kill XP, level-up stats, end-of-combat check — done (#5).
- **Skills (§8):** 10-skill registry, weapon mastery strikes, range/roll bonuses, thresholds 5/10 — done (#6).
- **Weapon table (§20):** damage ranges, quality, non-humanoid ban, equipment-driven `BurtStats` — done (#7).
- **Sleep gate (§5):** bedroll or paid room via `sleep.is_sleep_available` — done (#13).
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
| "trade.py / magic.py are dead code" | both are wired now: `burt/economy.py` + shop sub-mode for trade, `magic.cast_ready` + teacher spawn for magic (#4, #8) |

---

## Summary

| Severity | Count |
|---|---|
| 🔴 Critical | 0 (was 4; logging, NPC spawn, role quests, trade closed) |
| 🟠 High | 2 (was 7; reputation, magic, XP, skills and the weapon table closed) |
| 🟡 Medium | 3 (was 5; sleep availability and dialogue-as-one-action closed) |
| 🟢 Low | 8 |
| ⚪ Intentional deviations | 8 |
| ✅ Closed | 12 (#1 logging, #2 NPC spawn, #3 role quests, #4 trade, #5 XP/levels, #6 skills, #7 weapon table, #8 magic, #9 reputation, #13 sleep, #14 dialogue, day rollover/resurrection) |
| **Total open** | **13** |

---

## Verification

```text
cd E:\Butr-Ai
.\.venv\Scripts\pytest.exe tests/ -q     # 2457 passed
python main.py --new --dry-run           # inspect state + menu, no log writes
python main.py --new --max-steps 5       # logs/plugin_*.jsonl + game_session.jsonl
git --no-pager log --oneline -5
```


