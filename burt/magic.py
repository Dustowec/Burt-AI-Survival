"""burt/magic.py — §9 «Магия» (чистая часть).

Что НЕ здесь (отложено):
    - статусы паладин/еретик        -> quests.py
    - цепочки квестов               -> quests.py
    - логика диалога с учителем     -> npc / loop
    - кара богов, паладин->убийца   -> quests / npc

Что здесь:
    - константы каста
    - выбор стихии магом (1d4 при спавне учителя)
    - проверки лимитов слотов
    - проверка условий каста
    - соответствие «учитель -> что даёт»
    - механика «обучение = +1 уровень навыка» (§32, общая)

Модель данных (state.hidden.spells):
    element:    None | fire | water | earth | air
    alignment:  None | light  | dark

Ключевые правила §9:
    - Каст НЕ врождённый. Нужны ТРИ условия: staff + заклинание + учитель.
    - Пока все три не выполнены — навык «Владение магией» не открыт.
    - Лимит: 1 стихия (fire/water/earth/air) + 1 алигмент (light/dark).
    - Dark и light взаимоисключающие. Обе — нельзя.
    - Итого 2 заклинания за жизнь.
    - Mage учит стихии, cleric — свету, necromancer — тьме.
    - Учитель-mage: стихия определяется 1d4 при СПАВНЕ учителя
      (не при обучении).
    - Повторное обучение той же стихии не даёт «второй слот» —
      у нас одна ячейка element, повторное обучение просто
      повышает уровень навыка (§32: обучение = +1 к навыку).
"""
from __future__ import annotations

from typing import Callable

from burt import skills


# ============================================================
# КОНСТАНТЫ
# ============================================================

ELEMENTS: frozenset[str] = frozenset({
    "fire",
    "water",
    "earth",
    "air",
})

ALIGNMENTS: frozenset[str] = frozenset({
    "light",
    "dark",
})

# §9: «каст = 1 MP, урон 3–6 (базовый)».
CAST_MP_COST = 1
CAST_DAMAGE_MIN = 3
CAST_DAMAGE_MAX = 6

# §8: навыки скрыты до 1/10, потолок 10.
SKILL_MAX_LEVEL = skills.MAX_LEVEL

# §9: 2 заклинания за жизнь (1 стихия + 1 алигмент).
MAX_SPELLS = 2


# ============================================================
# УЧИТЕЛЯ — КТО ЧТО ДАЁТ
# ============================================================

# §9: «mage — стихия (одна из четырёх), определяется 1d4 при спавне.
#      cleric — light, necromancer — dark».
#
# Значение для мага — "element" (категория), потому что конкретную
# стихию оркестратор берёт из уже заролленного при спавне учителя
# поля element. Для остальных — конкретный алигмент.
TEACHER_KIND: dict[str, str] = {
    "mage": "element",
    "cleric": "light",
    "necromancer": "dark",
}


# ============================================================
# ВЫБОР СТИХИИ МАГОМ — 1d4 ПРИ СПАВНЕ
# ============================================================

# 1d4 -> стихия. Индекс = roll - 1.
_ELEMENT_BY_ROLL: tuple[str, ...] = (
    "fire",
    "water",
    "earth",
    "air",
)

# The engine has one die and it is d6 (dice.roll_d6). A 5 or a 6 on the
# element die is rolled again: rejection sampling is what turns a d6 into
# a real 1d4, so the four elements stay equally likely.
_MAX_ELEMENT_ROLLS = 4


def roll_mage_element(rng: Callable[[], int]) -> str:
    """Spec 9: the mage's element is one of four, decided by 1d4 at spawn.

    The engine has a single die and it is d6 (dice.roll_d6), so 5 and 6
    are simply rolled again: rejection sampling is what turns a d6 into a
    real 1d4, and the four elements stay equally likely. Rerolls are
    capped at _MAX_ELEMENT_ROLLS; if the die is stuck above 4 (a scripted
    rng, or 1/27 in a live run) the value wraps 5->1, 6->2 instead of
    crashing the run.

    Anything outside 1..6 is a caller bug: it still raises.
    """
    roll = 0
    for _ in range(_MAX_ELEMENT_ROLLS):
        roll = rng()
        if not isinstance(roll, int) or isinstance(roll, bool):
            raise ValueError(
                f"roll_mage_element: expected 1-6, got {roll!r}"
            )
        if not 1 <= roll <= 6:
            raise ValueError(
                f"roll_mage_element: expected 1-6, got {roll!r}"
            )
        if roll <= len(_ELEMENT_BY_ROLL):
            return _ELEMENT_BY_ROLL[roll - 1]
    return _ELEMENT_BY_ROLL[(roll - 1) % len(_ELEMENT_BY_ROLL)]


# ============================================================
# УСЛОВИЯ КАСТА
# ============================================================

def can_cast(
    has_staff: bool,
    has_spell: bool,
    has_teacher: bool,
) -> bool:
    """§9: каст возможен, если есть ВСЕ ТРИ условия.

    Пока все три не выполнены — навык «Владение магией» не открыт.
    """
    return has_staff and has_spell and has_teacher


# ============================================================
# ЛИМИТЫ СЛОТОВ
# ============================================================

def can_learn_element(current: str | None, new: str) -> bool:
    """§9: 1 стихия за жизнь.

    Правила:
        - current is None и new — валидная стихия -> True
        - current уже есть (любая) -> False (лимит 1)
        - new не из ELEMENTS -> False (мусорный вход)
        - current не из ELEMENTS и не None -> False
    """
    if new not in ELEMENTS:
        return False
    if current is None:
        return True
    # current уже стоит (валидный или мусор) — второй слот не даём.
    return False


def can_learn_alignment(current: str | None, new: str) -> bool:
    """§9: 1 алигмент за жизнь. Dark и light взаимоисключающие.

    Правила:
        - current is None и new из ALIGNMENTS -> True
        - current уже есть -> False (и light, и dark занимают слот)
        - new не из ALIGNMENTS -> False
        - current не из ALIGNMENTS и не None -> False
    """
    if new not in ALIGNMENTS:
        return False
    if current is None:
        return True
    return False


def total_spells(
    element: str | None,
    alignment: str | None,
) -> int:
    """Сколько заклинаний открыто (0/1/2).

    Считаем по факту не-None. Валидацию значений делает
    can_learn_*, сюда мусор попадать не должен — но если попадёт,
    функция честно посчитает его как «что-то есть».
    """
    count = 0
    if element is not None:
        count += 1
    if alignment is not None:
        count += 1
    return count


# ============================================================
# ОБУЧЕНИЕ — +1 УРОВЕНЬ НАВЫКА
# ============================================================

def next_skill_level(current: int) -> int:
    """§32: обучение у учителя = +1 к навыку, 1 раз за мир.

    Применяется не только к магии — общая механика для мага,
    чернокнижника, служителя и ветерана.

    Кап — SKILL_MAX_LEVEL (10, §8).
    Значения выше капа и мусор (отрицательные) — ужимаются.
    """
    if current >= SKILL_MAX_LEVEL:
        return SKILL_MAX_LEVEL
    if current < 0:
        return 1
    return current + 1
# ============================================================
# СОСТОЯНИЕ МАГИИ — hidden["magic"]
# ============================================================
#
# Ядро выше остаётся чистым (числа и правила). Ниже — обвязка,
# которую вызывает loop.py: она читает/пишет словари state, но
# по-прежнему без I/O, без asyncio и без LLM.
#
# hidden["magic"] = {
#     "mage_met": False,      # учитель-маг встречался в этой жизни
#     "teachers": {},         # role -> {"element": str|None}
#     "loot_sold": 0,         # goblin_staff, проданных чернокнижнику
#     "granted": [],          # история выданных element/alignment
# }

# §9: третий путь к посоху (согласовано 20.11.2026) —
# два goblin_staff, проданных чернокнижнику, и он выдаёт настоящий staff.
LOOT_TRADES_FOR_STAFF = 2

from dataclasses import dataclass


def new_state() -> dict:
    """Пустое состояние магии для hidden["magic"]."""
    return {
        "mage_met": False,
        "teachers": {},
        "loot_sold": 0,
        "granted": [],
    }


def ensure_state(hidden: dict) -> dict:
    """Вернуть hidden["magic"], починив отсутствующие поля.

    Нужна для сейвов, созданных до появления магии.
    """
    mstate = hidden.get("magic")
    if not isinstance(mstate, dict):
        mstate = new_state()
        hidden["magic"] = mstate
    for key, default in new_state().items():
        mstate.setdefault(key, default)
    if not isinstance(mstate.get("teachers"), dict):
        mstate["teachers"] = {}
    if not isinstance(mstate.get("granted"), list):
        mstate["granted"] = []
    return mstate


def can_teach(role: str) -> bool:
    """§9: магии учат только mage / cleric / necromancer."""
    return teacher_key(role) in TEACHER_KIND


# Спавн-ключ учителя-мага — `mage_event` (replicas.json -> events),
# а в TEACHER_KIND роль называется `mage`. Держим соответствие в одном месте.
_TEACHER_KEY_ALIAS: dict[str, str] = {"mage_event": "mage"}


def teacher_key(role: str) -> str:
    """Роль учителя для TEACHER_KIND (mage_event -> mage)."""
    return _TEACHER_KEY_ALIAS.get(role, role)


# Названия навыков для visible["skills_visible"] (§8).
# The veteran teaches a random weapon skill (§32): sword / spear / club.
VETERAN_WEAPON_SKILLS: tuple[str, ...] = ("Sword", "Club", "Spear")

SKILL_NAME_BY_ROLE: dict[str, str] = {
    "mage_event": "Magic",
    "cleric": "Magic",
    "necromancer": "Magic",
}


def veteran_skill_name(rng: Callable[[], int] | None = None) -> str:
    """§32: the veteran teaches a random weapon skill."""
    if rng is None:
        return VETERAN_WEAPON_SKILLS[0]
    roll = rng()
    if not 1 <= roll <= 6:
        raise ValueError(f"veteran skill roll must be 1..6, got {roll!r}")
    return VETERAN_WEAPON_SKILLS[(roll - 1) % len(VETERAN_WEAPON_SKILLS)]


def record_teacher_spawn(mstate: dict, role: str, rng: Callable[[], int]) -> str | None:
    """§9: стихия мага кидается 1d4 в момент СПАВНА учителя.

    Возвращает выпавшую стихию (только для mage_event).
    """
    if role == "mage_event":
        element = roll_mage_element(rng)
        mstate["mage_met"] = True
        mstate["teachers"][role] = {"element": element}
        return element
    mstate["teachers"].setdefault(role, {"element": None})
    return None


def teacher_element(mstate: dict, role: str) -> str | None:
    """Стихия, которой владеет маг (None для остальных учителей)."""
    teachers = mstate.get("teachers") or {}
    entry = teachers.get(role) or {}
    value = entry.get("element")
    return value if value in ELEMENTS else None


def mage_spawned(mstate: dict) -> bool:
    """Маг уже встречался в этой жизни."""
    return bool(mstate.get("mage_met"))


# ------------------------------------------------------------
# Слоты заклинаний
# ------------------------------------------------------------

def spell_slots(hidden: dict) -> tuple[str | None, str | None]:
    """(element, alignment) из hidden["spells"] с защитой от мусора."""
    spells = hidden.get("spells") or {}
    if not isinstance(spells, dict):
        spells = {}
    element = spells.get("element")
    alignment = spells.get("alignment")
    return (
        element if element in ELEMENTS else None,
        alignment if alignment in ALIGNMENTS else None,
    )


def spells_open(hidden: dict) -> int:
    """Сколько заклинаний открыто (0/1/2) — §9."""
    element, alignment = spell_slots(hidden)
    return total_spells(element, alignment)


def cast_ready(hidden: dict, has_staff: bool) -> bool:
    """§9: каст открыт только при всех трёх условиях.

    staff + хотя бы одно заклинание + найденный учитель.
    """
    teacher = bool(hidden.get("teacher_found"))
    return can_cast(has_staff, spells_open(hidden) > 0, teacher)


# ------------------------------------------------------------
# Трофейный посох — третий путь (§9, согласовано 20.11.2026)
# ------------------------------------------------------------

def record_loot_staff_sale(mstate: dict) -> bool:
    """Учесть проданный goblin_staff. True — чернокнижник выдаёт staff."""
    sold = int(mstate.get("loot_sold", 0)) + 1
    mstate["loot_sold"] = sold
    return sold >= LOOT_TRADES_FOR_STAFF
# ------------------------------------------------------------
# Обучение (§32: обучение = +1 к навыку, 1 раз за жизнь у учителя)
# ------------------------------------------------------------

@dataclass
class TrainingOutcome:
    """Результат одной попытки обучения."""

    applied: bool
    skill_name: str = ""
    skill_level: int = 0
    granted: str | None = None
    note: str = ""


def _bump_skill(hidden: dict, visible: dict, name: str) -> int:
    """+1 к навыку (делегирует в skills.award_level, §8)."""
    return skills.award_level(hidden, visible, name)


def train(
    hidden: dict,
    visible: dict,
    role: str,
    rng: Callable[[], int] | None = None,
) -> TrainingOutcome:
    """Обучиться у учителя (§9, §32).

    Правила:
      - один раз за жизнь у каждого учителя (hidden["trained_by"]);
      - cleric -> light, necromancer -> dark, mage_event -> его стихия;
      - ветеран -> случайное владение (меч / дубина / копьё);
      - лимит 1 стихия + 1 алигмент (can_learn_*);
      - любой учитель ещё и поднимает навык на +1 (кап 10).

    Мутирует hidden/visible — как quests.py.
    """
    mstate = ensure_state(hidden)
    trained = hidden.setdefault("trained_by", [])
    if not isinstance(trained, list):
        trained = []
        hidden["trained_by"] = trained

    if role == "veteran":
        skill_name = veteran_skill_name(rng)
    else:
        skill_name = SKILL_NAME_BY_ROLE.get(role, "")

    if role in trained:
        level = _bump_skill(hidden, visible, skill_name) if skill_name else 0
        return TrainingOutcome(
            applied=False, skill_name=skill_name, skill_level=level,
            note=f"the {role} has already taught you once in this life",
        )

    kind = TEACHER_KIND.get(teacher_key(role))
    element, alignment = spell_slots(hidden)
    granted: str | None = None
    note = ""

    if kind == "element":
        new_element = teacher_element(mstate, role)
        if new_element is None:
            note = "the mage has no element to teach"
        elif can_learn_element(element, new_element):
            hidden.setdefault("spells", {})["element"] = new_element
            granted = new_element
        else:
            note = f"you already command another element ({element})"
    elif kind in ALIGNMENTS:
        if can_learn_alignment(alignment, kind):
            hidden.setdefault("spells", {})["alignment"] = kind
            granted = kind
        else:
            note = f"you already follow another path ({alignment})"

    trained.append(role)
    if can_teach(role):
        hidden["teacher_found"] = True
    if granted is not None:
        mstate["granted"].append(granted)

    level = _bump_skill(hidden, visible, skill_name) if skill_name else 0
    return TrainingOutcome(
        applied=True, skill_name=skill_name,
        skill_level=level, granted=granted, note=note,
    )