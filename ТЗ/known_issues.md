# Known Issues — BURT v0.7.0

Список расхождений между кодом и спецификацией v0.7.0, а также открытых задач из бэклога HANDOFF (1-17).

---

## 🔴 КРИТИЧЕСКИЕ (блокируют геймплей)

### 1. Логирование (§38-39) — НЕ реализовано

**HANDOFF:** 1, 4 | **Status:** требуется полная переработка

**Spec требует:**
- JSONL формат (одна строка = одно событие)
- UUID-трассировка: session_uuid / turn_uuid / call_uuid
- Три слоя: react / tool / interaction
- Ring buffer maxlen=20 для краш-репортов
- Async logging через asyncio.Queue
- Ротация каждые 12 часов (plugin_YYYY-MM-DD_HH.jsonl)
- Краш-репорты с dump ring buffer
- game_session.jsonl append-only
- Уровни алёртов: 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR

**Реальность:**
- One JSON per turn (не JSONL)
- Нет UUID-трассировки
- Нет floors (react/tool/interaction)
- Нет ring buffer
- Threading.Lock вместо asyncio.Queue
- Day-based rotation (не 12h)
- Нет краш-репортов
- Нет game_session.jsonl

---

### 2. npc.py — система диалогов NPC (§32)

**HANDOFF:** 1-17 | **Status:** NEVER IMPLEMENTED, DEFERRED by user

**Spec требует:**
- 13 ролей NPC с пулами реплик
- Диалоговая механика: категории ответов, кубик, бонусы
- Репутация по ролям
- Spawn по локациям

**Реальность:**
- Файл никогда не создан
- replicas.json загружается, но npc.py отсутствует
- Диалоги не реализованы

---

### 3. TZ-10: Cap spawn to 1 enemy when level < 5

**HANDOFF:** 17 | **Status:** UNCOMMITTED

**Spec требует:**
- При уровне < 5 спавн не более 1 врага

**Реальность:**
- Тесты есть (test_loop_combat_start.py)
- Код не закоммичен

---

## 🟡 СРЕДНИЕ (влияют на геймплей)

### 4. BurtStats unification — стуб вместо реальных данных

**HANDOFF:** 8, 9 | **Status:** stub

**Spec требует:**
- BurtStats с реальными weapon damage, skill modifier, master level

**Реальность:**
- BurtStats — стуб с defaults
- Реальная интеграция оружия/навыков не реализована

---

### 5. Combat [Tools] menu

**HANDOFF:** 8, 9 | **Status:** not implemented

**Spec требует:**
- Меню тулз в бою (свиток, зелья и т.д.)

**Реальность:**
- Меню тулз отсутствует в боевом контексте

---

### 6. Bandit first-turn money demand (§23)

**HANDOFF:** 2 | **Status:** not implemented

**Spec требует:**
- «1-й ход: требует деньги. Не платит — атака.»

**Реальность:**
- Бандит как стандартный враг (HP=10, dmg=2-4)
- Без механики требования денег

---

### 7. Chain templates (pala_1/2/3, heretic_1/2/3)

**HANDOFF:** 7 | **Status:** generic support only

**Spec требует:**
- Конкретные цепочки К1-К2-К3 для каждой ветки веры

**Реальность:**
- Generic chain support есть
- Конкретные шаблоны К1-К2-К3 не в коде

---

### 8. Reputation changes for quests (+1/-2) (§16)

**HANDOFF:** 16 | **Status:** not implemented

**Spec требует:**
- +1 за сдачу квеста, -2 за провал

**Реальность:**
- Не реализовано в логике квестов

---

### 9. Non-combat actions in combat

**HANDOFF:** 11, 12 | **Status:** partially fixed

**Spec требует:**
- Только attack/block/flee/cast в бою

**Реальность:**
- go_* заблокированы
- eat_food/drink_water/osmotret могут быть доступны

---

### 10. Валюта — spec v0.7.0 → coin

**Status:** spec обновлён, код соответствует

**Spec v0.7.0:** gold/silver/copper (1 золотой = 10 серебряных = 100 медяков)
**Код:** single `{"coin": 50}`
**Статус:** spec обновлён в этом же обновлении

---

### 11. Голод — изменённая механика (§4)

**Status:** зафиксировано как изменённая механика

**Spec:** инжект «голоден» строго на шагах 0 и 10.
**Код:** инжект на КАЖДОМ шаге, где eat=False.
**Причина:** противоречие со статусом «сыт» — модель видела «Fed: yes» и «ты голоден» одновременно.

---

## 🟢 НИЗКОГО ПРИОРИТЕТА

### 12. items.py не содержит таблицу урона оружия (§20)

**Status:** minor

**Spec:** таблица урона 10 типов оружия, модификаторы качества.
**Код:** items.py содержит только search-предметы; оружие в bestiary.py/combat.py.

---

### 13. sync_poisoned_effect — poison-specific

**HANDOFF:** 13 | **Status:** poison-specific

**Spec требует:**
- Generalized tick-effect system для статусов

**Реальность:**
- sync_poisoned_effect только для poison

---

### 14. Hunger constants deduplication

**HANDOFF:** 13 | **Status:** duplicated

**HUNGER_HUNGRY_AT и HUNGER_DEATH_AT продублированы в state.py и hunger.py.**

---

### 15. Old replica files in root

**HANDOFF:** 5 | **Status:** cleanup needed

**loop.py.back существует в burt/.**

---

### 16. LLM ignores micro-location context

**HANDOFF:** 11 | **Status:** cosmetic

**Косметическая проблема: LLM не учитывает микро-локацию при выборе действия.**

---

### 17. Gemma robotic behavior

**HANDOFF:** 10, 11 | **Status:** WON'T FIX

**Модель Gemma 3n ведёт себя роботизированно. Это ограничение модели, не кода.**

---

### 18. SHOW_SLEEP_TIMER отсутствует в config.py (§31)

**Status:** minor, по умолчанию True

---

### 19. world.py — 2-4 выхода вместо 4 соседа (§17)

**Status:** minor, design choice

**Spec:** «Граф, 4 соседа.»
**Код:** 2-4 выхода на ноду.

---

## 📊 СВОДКА

| Уровень | Кол-во | Блокируют геймплей |
|---------|--------|-------------------|
| 🔴 Критические | 3 | Да |
| 🟡 Средние | 8 | Частично |
| 🟢 Низкого приоритета | 8 | Нет |
| **Итого** | **19** | |
