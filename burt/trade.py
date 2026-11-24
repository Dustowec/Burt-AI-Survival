"""burt/trade.py — §35 «Матрица торговли».

Чистое ядро. Никакого I/O, никаких NPC, никаких статусов веры.

Модификатор цены локации (один на всех):
    кидается ОДИН РАЗ при входе в локацию, живёт до конца сессии
    в этой локации.
    1-2 -> x1.25 (+25%)
    3-4 -> x1.00 (базовая)
    5-6 -> x0.75 (-25%)

Формулы:
    покупка Буртом:  floor(base * mod)
    продажа Буртом:  floor(floor(base * 0.5) * mod)

Все цены — в монетах (coin):
    1 coin = 1 бывший медяк; старт 5 silver = 50 coin; старый 1 gold = 100 coin
Округление ВНИЗ на каждом шаге (math.floor).

Правило «раз на сделку» = весь диалог:  модификатор роли кидается
один раз и применяется ко всем покупкам/продажам внутри диалога.
Это забота оркестратора, не trade.py — здесь только расчёт.

Правило «necromancer не покупает у паладина» — тоже не здесь.
Это фильтр на уровне npc/loop. trade.py ничего не знает о вере.

Округление и особенности:
    bandage (base=1) при продаже уходит за 0 coin — следствие
    формулы floor(floor(1 * 0.5) * mod) = floor(0 * mod) = 0.
    Никаких минимумов не вводим: формула есть формула.
"""
from __future__ import annotations

import math
from typing import Callable


# ============================================================
# БАЗОВЫЕ ЦЕНЫ — ЧТО БУРТ ПОКУПАЕТ (в медяках)
# ============================================================

BASE_PRICES: dict[str, int] = {
    # еда и расходники
    "bread": 2,
    "fish": 2,
    "dried_fish": 3,
    "waterskin": 2,               # малая, 2/2
    "large_waterskin": 10,      # 5/5, 10 coin
    "bedroll": 5,
    "tavern_room": 5,           # одноразовый товар: ночь

    # оружие
    "club": 10,                     # 10 coin
    "spear": 20,                      # 20 coin
    "low_quality_sword": 10,       # 10 coin
    "ordinary_sword": 30,                # 30 coin
    "high_quality_sword": 60,      # 60 coin
    "staff": 100,                     # 100 coin
}


# ============================================================
# ЦЕНЫ ЛУТА — БАЗА ДЛЯ ПРОДАЖИ (в медяках)
# ============================================================

LOOT_PRICES: dict[str, int] = {
    "goblin_dagger": 3,
    "goblin_staff": 6,
    "bandage": 1,
    "fangs": 3,                        # за пару (2 pcs.)
    "pelt": 10,                       # 10 coin
    "dragon_scale": 1000,             # 1000 coin
    "dragon_fangs": 500,             # 500 coin (за пару)
    "dragon_bone": 1000,             # 1000 coin
}


# ============================================================
# РОЛИ
# ============================================================

TRADE_ROLES: frozenset[str] = frozenset({
    "elder",
    "blacksmith",
    "merchant",
    "fisherman",
    "tavernkeeper",
    "mage",
    "necromancer",
})

# Что каждая роль продаёт Бурту.
# Правило: всё, что в BASE_PRICES, обязано быть у кого-то в ROLE_SELLS
# (иначе товар не купить). См. тест test_all_sold_items_are_buyable.
ROLE_SELLS: dict[str, frozenset[str]] = {
    "elder": frozenset({
        "bedroll",
        "waterskin",
    }),
    "blacksmith": frozenset({
        "club",
        "spear",
        "low_quality_sword",
        "ordinary_sword",
        "high_quality_sword",
    }),
    "merchant": frozenset(BASE_PRICES.keys()),  # всё
    "fisherman": frozenset({
        "fish",
        "dried_fish",
    }),
    "tavernkeeper": frozenset({
        "bread",
        "waterskin",
        "tavern_room",
    }),
    "mage": frozenset({"staff"}),
    "necromancer": frozenset({"staff"}),
}


# ============================================================
# БЛОКИРОВКА ТОРГОВЛИ ПРИ НЕХВАТКЕ ДЕНЕГ
# ============================================================
#
# Пер-торговец: у каждой роли свой счётчик неудачных покупок и свой
# блок диалога. Счётчик живёт в пределах одного игрового дня и НЕ
# сбрасывается успешной покупкой, продажей, сменой товара или
# повторным открытием магазина. На 3-й неудачной покупке диалог с
# этим торговцем обрывается, а поговорить с ним снова можно только
# на следующий день.

TRADE_BUY_FAIL_LIMIT = 3
TRADE_NO_MONEY_TEXT = "STOP! You have no money! Go work!"


def ensure_state(hidden: dict) -> dict:
    """Repair the per-trader trade block fields (old saves)."""
    failures = hidden.get("trade_buy_failures")
    if not isinstance(failures, dict):
        hidden["trade_buy_failures"] = {}
    blocked = hidden.get("trade_dialog_blocked_until")
    if not isinstance(blocked, dict):
        hidden["trade_dialog_blocked_until"] = {}
    fail_day = hidden.get("trade_fail_day")
    if not isinstance(fail_day, int) or isinstance(fail_day, bool):
        hidden["trade_fail_day"] = hidden.get("day", 1)
    return hidden


def refresh_day(hidden: dict, day: int) -> None:
    """Reset the counters when the game day changes.

    Expired blocks (until <= day) are dropped. The counters are
    per-trader and per-day: a new day gives every trader a clean slate.
    """
    ensure_state(hidden)
    if hidden.get("trade_fail_day") == day:
        return
    hidden["trade_buy_failures"] = {}
    blocked = hidden.get("trade_dialog_blocked_until") or {}
    hidden["trade_dialog_blocked_until"] = {
        role: until
        for role, until in blocked.items()
        if isinstance(until, int) and not isinstance(until, bool)
        and until > day
    }
    hidden["trade_fail_day"] = day


def is_dialog_blocked(hidden: dict, role: str, day: int) -> bool:
    """True while this trader refuses to talk (until the next day).

    Read-only: never rolls a die and never mutates the state, so it is
    safe to call from build_menu.
    """
    blocked = hidden.get("trade_dialog_blocked_until")
    if not isinstance(blocked, dict):
        return False
    until = blocked.get(role)
    if not isinstance(until, int) or isinstance(until, bool):
        return False
    return day < until


def record_failed_buy(hidden: dict, role: str, day: int) -> bool:
    """Count one failed purchase. True when the dialogue must be cut.

    The counter accumulates across items, successful purchases, shop
    closings and repeated dialogue openings within the same day.
    """
    refresh_day(hidden, day)
    ensure_state(hidden)
    failures = hidden["trade_buy_failures"]
    count = failures.get(role, 0)
    if not isinstance(count, int) or isinstance(count, bool):
        count = 0
    count += 1
    failures[role] = count

    if count < TRADE_BUY_FAIL_LIMIT:
        return False

    hidden["trade_dialog_blocked_until"][role] = day + 1
    return True


# ============================================================
# МОДИФИКАТОР ЦЕНЫ ЛОКАЦИИ
# ============================================================

def roll_location_price_modifier(rng: Callable[[], int]) -> float:
    """§35: один бросок при входе в локацию.

    rng — функция без аргументов, возвращает 1-6.
    Вызывается РОВНО ОДИН раз.

    1-2 -> 1.25
    3-4 -> 1.00
    5-6 -> 0.75
    """
    roll = rng()
    if roll <= 2:
        return 1.25
    if roll <= 4:
        return 1.00
    return 0.75


# ============================================================
# ЦЕНА ПОКУПКИ
# ============================================================

def buy_price(item: str, modifier: float) -> int:
    """Цена покупки Буртом. floor(base * modifier).

    item — название из BASE_PRICES.
    modifier — модификатор локации (1.25 / 1.0 / 0.75) или
               любой другой, если оркестратор добавит бонусы.
    KeyError — если предмета нет в BASE_PRICES.
    """
    base = BASE_PRICES[item]
    return math.floor(base * modifier)


# ============================================================
# ЦЕНА ПРОДАЖИ
# ============================================================

def sell_price(item: str, modifier: float) -> int:
    """Цена продажи Буртом. floor(floor(base * 0.5) * modifier).

    item ищется в BASE_PRICES, потом в LOOT_PRICES.
    KeyError — если нигде нет.

    Двойной floor:
        1) base * 0.5 — половина базовой цены
        2) * modifier — модификатор локации
    Округление вниз на каждом шаге.
    """
    if item in BASE_PRICES:
        base = BASE_PRICES[item]
    elif item in LOOT_PRICES:
        base = LOOT_PRICES[item]
    else:
        raise KeyError(item)

    half = math.floor(base * 0.5)
    return math.floor(half * modifier)