"""Конфиг проекта BURT — §31.

Все флаги, крутилки и табличные данные, которые могут меняться
без правки логики. Отдельный файл, потому что крутится —
а исходники трогать не хочется.

Расклад типов локаций (§17) вынесен сюда из world.py (долг В7).
world.py реэкспортирует LOCATION_TYPES и читает LOCATION_TYPE_ROLLS.
"""
from __future__ import annotations

import os


# ---------------------------------------------------------------------
# LLM API (§1, §31)
# ---------------------------------------------------------------------
# Три параметра. Больше ничего не нужно.
#
# Локальная модель (LM Studio):
#   BASE_URL = "http://localhost:1234/v1"
#   API_KEY = ""
#   MODEL = "local-model"
#
# Внешний API — ключ хранится в burt/api_config.py (не коммитится).
# Если API_KEY пустой — автоматически используется LM Studio.

BASE_URL = "http://localhost:1234/v1"
API_KEY = ""
MODEL = "local-model"
TEMPERATURE = 0.95


# Бюджет ответа LLM (§1, §31).
#
# max_tokens — это ПОЛНЫЙ бюджет output, включая thinking-токены.
# Для thinking-моделей (Qwen 3.5 4B с thinking, Gemma 4 E2B с thinking)
# на "подумать" уходит 300–800 токенов, и при старом значении 512
# на сам ответ оставалось 0 -> пустая реплика, finish_reason=length.
#
# 2048 даёт "простор мысли": thinking-модели перестают обрезаться,
# Qwen перестаёт заикаться на длинных репликах.
#
# Цена: 4B-модель на 6GB VRAM генерит ~20–40 tok/s, то есть ход может
# занимать 40–75 секунд, если модель реально думает на 1500 токенов.
# Если латентность станет болью — крути вниз или включай per-mode
# бюджет (combat=512, exploration=2048) — это TODO на будущее.
#
# Управляется через env var BURT_MAX_TOKENS — чтобы гонять прогоны
# без правки кода:  BURT_MAX_TOKENS=1024 python main.py --new ...
MAX_TOKENS = int(os.environ.get("BURT_MAX_TOKENS", "2048"))


# Таймаут HTTP-запроса к LLM в секундах (§1).
#
# При MAX_TOKENS=2048 и медленной модели ход может занимать 50–70 секунд.
# Старый таймаут 60с ловил ложные ConnectionError -> fallback
# "Darkness consumes..." на ровном месте. 180с даёт запас на thinking
# плюс один ретрай.
LLM_TIMEOUT_SECONDS = 180


# ---------------------------------------------------------------------
# ОТОБРАЖЕНИЕ (§24, §25, §31)
# ---------------------------------------------------------------------

HP_DISPLAY = "numbers"       # §24: "numbers" | иной режим
SHOW_HUNGER_TIMER = False    # §25: голод — качественно
SHOW_DATE = True


# ---------------------------------------------------------------------
# ВРЕМЯ (§3, §31)
# ---------------------------------------------------------------------

DAY_STEPS = 20


# ---------------------------------------------------------------------
# ГОЛОД (§4, §31)
# ---------------------------------------------------------------------

HUNGER_HUNGRY_AT = [0, 10]
HUNGER_DEATH_AT = [8, 18]


# ---------------------------------------------------------------------
# ПАМЯТЬ (§28, §31)
# ---------------------------------------------------------------------

MEMORY_COMPRESS_AT = 10


# ---------------------------------------------------------------------
# ЛОГИ (§31, §38, §39)
# ---------------------------------------------------------------------

DEBUG = False
LOG_LEVEL = 1
LOG_DIR = "logs/"
CRASH_DIR = "crashes/"
LOG_ROTATE_HOURS = 12
RING_BUFFER_SIZE = 20

# Gameplay log (spec 2, 39): append-only, synchronous, one line per turn.
# Lives next to state.json.
GAME_SESSION_PATH = "game_session.jsonl"

# DEBUG=False: prompt/response are stored as chars + sha256 + preview.
LOG_PREVIEW_CHARS = 80

# Async writer queue. On overflow the line is written synchronously
# and a log_queue_full (level 2) event is emitted.
LOG_QUEUE_MAXSIZE = 1000

# fsync each gameplay line. False by default: flush() survives a normal
# interpreter exit, and fsync per turn is slow on Windows.
LOG_FSYNC = False


# ---------------------------------------------------------------------
# ЛОКАЦИИ (§17) — вынесено из world.py, долг В7
# ---------------------------------------------------------------------

LOCATION_TYPES = frozenset({
    "crossroads", "thicket",
    "forest", "field", "steppe", "swamp", "river", "road", "village",
    "temple", "dungeon",
})

# Расклад типа локации по 1d6.
#   str              → один вариант
#   tuple[str, ...]  → уточняющий бросок, индекс = roll_size - 1
# Все 11 типов из LOCATION_TYPES покрываются.
LOCATION_TYPE_ROLLS = {
    1: "forest",
    2: "forest",
    3: "field",
    4: "steppe",
    5: ("swamp", "river", "road"),                        # 1d3
    6: ("temple", "dungeon",
        "village", "village", "crossroads", "thicket"),   # 1d6
}