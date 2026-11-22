"""Структура state.json — §30 ТЗ v0.7.0.

Чистые функции без I/O. Файловые операции — в burt.state_io.

Соглашения:
- create_initial_state(...) — стартовое состояние новой жизни.
- validate_state(state) — инварианты, raise ValueError при нарушении.
- get_visible(state) / get_hidden(state) — изолированные секции.

Все константы §4, §5, §9, §16 собраны здесь.
"""

from __future__ import annotations

import copy
import re
from burt import world
from burt import magic
from burt import progression
from burt import faith
from typing import Any

# ---------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------

ROLE_NAMES: tuple[str, ...] = (
    "merchant",
    "guard",
    "peasant",
    "peasant_woman",
    "elder",
    "tavernkeeper",
    "blacksmith",
    "fisherman",
    "child",
    "veteran",
    "cleric",
    "necromancer",
    "mage",
)

DIRECTIONS: tuple[str, ...] = ("north", "south", "east", "west")

MAX_SKILL_LEVEL: int = 10

HUNGER_HUNGRY_AT: list[int] = [0, 10]
HUNGER_DEATH_AT: list[int] = [8, 18]

SLEEP_FORCED_AT: int = 20
DAY_STEPS: int = 20

REPUTATION_MIN: int = -10
REPUTATION_MAX: int = 10

VALID_STATES: set[str] = {"exploring", "dialog", "combat"}
VALID_ELEMENTS: set[str | None] = {None, "fire", "water", "earth", "air"}
VALID_ALIGNMENTS: set[str | None] = {None, "light", "dark"}

STARTING_LOCATION_NAME: str = "Crossroads"
# Must match world.START_NODE_ID ("start").
STARTING_NODE_ID: str = "start"

STARTING_HP: int = progression.BASE_HP
STARTING_MP: int = progression.BASE_MP
STARTING_HP_PER_LEVEL: int = progression.HP_PER_LEVEL
STARTING_MP_PER_LEVEL: int = progression.MP_PER_LEVEL

STARTING_WALLET: dict[str, int] = {"coin": 50}


# ---------------------------------------------------------------------
# Дата — §2: один формат на всю игру
# ---------------------------------------------------------------------

_DATE_RE = re.compile(r"^\s*(\d+)\s*day(?:\(s\))?\s*$")


def format_date(day: int) -> str:
    """Каноническая дата: '1 day', '2 day', '7 day'.

    Единственный источник формата. Никакого суффикса-множественного.
    """
    return f"{int(day)} day"


def canonical_date(value: Any) -> str:
    """Привести старую запись с суффиксом к 'N day'; прочее не трогать."""
    match = _DATE_RE.match(str(value))
    if match is None:
        return str(value)
    return format_date(int(match.group(1)))


# ---------------------------------------------------------------------
# Создание стартового состояния
# ---------------------------------------------------------------------

def create_initial_state(
    life: int,
    session_uuid: str,
    config_hash: str,
    session_started: str,
    memory: str | None = None,
    memory_cause: str | None = None,
) -> dict[str, Any]:
    """Стартовое состояние новой жизни.

    life, session_uuid, config_hash, session_started — обязательны (§30).
    memory / memory_cause — optional, переносятся из предыдущей жизни.
    Возвращает полностью независимую структуру.
    """
    if not isinstance(life, int) or life < 1:
        raise ValueError(f"life must be int >= 1, got {life!r}")

    starting_graph = world.create_start_graph()

    meta: dict[str, Any] = {
        "life": life,
        "day": 1,
        "step": 0,
        "session_uuid": session_uuid,
        "session_started": session_started,
        "config_hash": config_hash,
    }
    if memory is not None:
        meta["memory"] = memory
    if memory_cause is not None:
        meta["memory_cause"] = memory_cause

    return {
        "meta": meta,
        "visible": {
            "hp": STARTING_HP,
            "hp_max": STARTING_HP,
            "mp": STARTING_MP,
            "mp_max": STARTING_MP,
            "level": 1,
            "xp": 0,
            "eat": False,
            "sleep_counter": 0,
            "date": format_date(1),
            "effects": [],
            "location": {
                "name": STARTING_LOCATION_NAME,
                "exits": list(DIRECTIONS),
            },
            "inventory": [
                {"name": "bread", "count": 2},
                {"name": "water", "count": 1},
                ],
            "wallet": dict(STARTING_WALLET),
            "skills_visible": [],
            "state": "exploring",
            "faith": faith.STATUS_NEUTRAL,
        },
        "hidden": {
            "hp_raw": STARTING_HP,
            "mp_raw": STARTING_MP,
            "hunger_death_at": list(HUNGER_DEATH_AT),
            "sleep_forced_at": SLEEP_FORCED_AT,
            "effects_detail": [],
            "dot_effects": [],
            "reputation": {role: 0 for role in ROLE_NAMES},
            "reputation_overall": 0,
            "faith": faith.new_state(),
            "skills_raw": [],
            "quests_raw": [],
            "quest_counter": 0,
            "location_graph": starting_graph,
            "current_node_id": STARTING_NODE_ID,
            "npcs_here": [],
            "events_here": [],
            "has_room_tonight": False,
            "prices_by_node": {},
            "price_modifier": None,
            "current_mode": "exploring",
            "dialog_state": None,
            "combat": None,
            "combat_npc_role": None,
            "last_action": None,
            "same_action_count": 0,
            "dice_log_last": [],
            "pending_events": [],
            "spells": {"element": None, "alignment": None},
            "has_staff": False,
            "teacher_found": False,
            "trained_by": [],
            "magic": magic.new_state(),
            "diary": None,
            "day_log": [],
            "diary_written_today": False,
            "diary_skipped_today": False,
            "injected_day": 0,
            "pending_encounter": None,
            "encounter_revealed": False,
        },
    }


# ---------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------

def validate_state(state: dict[str, Any]) -> None:
    """Проверяет инварианты. Raise ValueError при нарушении.

    Не мутирует вход.
    """
    if not isinstance(state, dict):
        raise ValueError("state must be dict")

    for section in ("meta", "visible", "hidden"):
        if section not in state:
            raise ValueError(f"state missing section: {section}")
        if not isinstance(state[section], dict):
            raise ValueError(f"state[{section}] must be dict")

    meta = state["meta"]
    visible = state["visible"]
    hidden = state["hidden"]

    # meta
    _require_int(meta, "life", minimum=1)
    _require_int(meta, "day", minimum=1)
    _require_int(meta, "step", minimum=0, maximum=DAY_STEPS)

    # visible: HP / MP
    _require_int(visible, "hp", minimum=0)
    _require_int(visible, "hp_max", minimum=1)
    _require_int(visible, "mp", minimum=0)
    _require_int(visible, "mp_max", minimum=0)

    if visible["hp"] > visible["hp_max"]:
        raise ValueError(
            f"visible.hp ({visible['hp']}) > hp_max ({visible['hp_max']})"
        )
    if visible["mp"] > visible["mp_max"]:
        raise ValueError(
            f"visible.mp ({visible['mp']}) > mp_max ({visible['mp_max']})"
        )

    # §7: level/xp are optional for saves made before progression existed;
    # main._ensure_runtime_fields fills them on load.
    if "level" in visible:
        _require_int(visible, "level", minimum=1)
    if "xp" in visible:
        _require_int(visible, "xp", minimum=0)

    # visible: сон
    _require_int(visible, "sleep_counter", minimum=0, maximum=SLEEP_FORCED_AT)

    # visible/hidden: вера (§33). Old saves may miss the field; main
    # repairs them via faith.ensure_runtime before the next save.
    if "faith" in visible:
        if visible["faith"] not in faith.STATUSES:
            raise ValueError(
                f"visible.faith must be one of {faith.STATUSES}, "
                f"got {visible['faith']!r}"
            )
    if "faith" in hidden:
        block = hidden["faith"]
        if not isinstance(block, dict):
            raise ValueError("hidden.faith must be dict")
        if block.get("status") not in faith.STATUSES:
            raise ValueError(
                f"hidden.faith.status must be one of {faith.STATUSES}, "
                f"got {block.get('status')!r}"
            )
        kfrom = block.get("killer_from")
        if kfrom is not None and kfrom not in faith.KILLER_FROM:
            raise ValueError(
                f"hidden.faith.killer_from must be one of "
                f"{faith.KILLER_FROM} or None, got {kfrom!r}"
            )
    if "reputation_overall" in hidden:
        _require_int(hidden, "reputation_overall")

    # hidden: current_mode + dialog_state consistency
    if hidden.get("current_mode") not in VALID_STATES:
        raise ValueError(
            f"hidden.current_mode must be one of {VALID_STATES}, "
            f"got {hidden.get('current_mode')!r}"
        )
    # dialog_state: None when exploring, dict when in dialog mode
    ds = hidden.get("dialog_state")
    if ds is not None and not isinstance(ds, dict):
        raise ValueError(
            f"hidden.dialog_state must be None or dict, got {type(ds).__name__}"
        )
    if hidden.get("current_mode") == "dialog" and ds is None:
        raise ValueError(
            "hidden.current_mode is 'dialog' but dialog_state is None"
        )
    if ds is not None:
        for key in ("role_key", "is_angry", "turn", "anger_lock_until",
                    "bonus_used", "quest_state"):
            if key not in ds:
                raise ValueError(
                    f"dialog_state missing required key: {key!r}"
                )

    # visible: кошелёк
    wallet = visible.get("wallet")
    if not isinstance(wallet, dict):
        raise ValueError("visible.wallet must be dict")
    if "coin" not in wallet:
        raise ValueError("visible.wallet missing coin")
    if not isinstance(wallet["coin"], int) or wallet["coin"] < 0:
        raise ValueError("visible.wallet.coin must be int >= 0")
    extra = set(wallet.keys()) - {"coin"}
    if extra:
        raise ValueError(f"visible.wallet has unknown keys: {sorted(extra)}")

    # visible: локация без id
    location = visible.get("location")
    if not isinstance(location, dict):
        raise ValueError("visible.location must be dict")
    if "id" in location or "node_id" in location:
        raise ValueError("visible.location must not contain id/node_id")

    # hidden: hp_raw / mp_raw совпадают с visible
    if hidden.get("hp_raw") != visible["hp"]:
        raise ValueError(
            f"hidden.hp_raw ({hidden.get('hp_raw')}) "
            f"!= visible.hp ({visible['hp']})"
        )
    if hidden.get("mp_raw") != visible["mp"]:
        raise ValueError(
            f"hidden.mp_raw ({hidden.get('mp_raw')}) "
            f"!= visible.mp ({visible['mp']})"
        )

    # hidden: репутация
    reputation = hidden.get("reputation")
    if not isinstance(reputation, dict):
        raise ValueError("hidden.reputation must be dict")
    for role, value in reputation.items():
        if role not in ROLE_NAMES:
            raise ValueError(f"hidden.reputation unknown role: {role!r}")
        if not isinstance(value, int):
            raise ValueError(
                f"hidden.reputation[{role}] must be int, got {value!r}"
            )
        if not REPUTATION_MIN <= value <= REPUTATION_MAX:
            raise ValueError(
                f"hidden.reputation[{role}] ({value}) out of "
                f"[{REPUTATION_MIN}, {REPUTATION_MAX}]"
            )

    # hidden: spells
    spells = hidden.get("spells")
    if not isinstance(spells, dict):
        raise ValueError("hidden.spells must be dict")
    if spells.get("element") not in VALID_ELEMENTS:
        raise ValueError(
            f"hidden.spells.element must be one of {VALID_ELEMENTS}, "
            f"got {spells.get('element')!r}"
        )
    if spells.get("alignment") not in VALID_ALIGNMENTS:
        raise ValueError(
            f"hidden.spells.alignment must be one of {VALID_ALIGNMENTS}, "
            f"got {spells.get('alignment')!r}"
        )

    # hidden: magic (§9) — optional for saves made before magic existed
    mstate = hidden.get("magic")
    if mstate is not None:
        if not isinstance(mstate, dict):
            raise ValueError("hidden.magic must be dict")
        if "mage_met" in mstate and not isinstance(mstate["mage_met"], bool):
            raise ValueError("hidden.magic.mage_met must be bool")

    # hidden: location price modifiers (§35)
    prices = hidden.get("prices_by_node")
    if prices is not None and not isinstance(prices, dict):
        raise ValueError("hidden.prices_by_node must be dict")

    # hidden: граф локаций (world.py shape: {type, entered, exits})
    graph = hidden.get("location_graph")
    if not isinstance(graph, dict) or not graph:
        raise ValueError("hidden.location_graph must be non-empty dict")
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            raise ValueError(
                f"hidden.location_graph[{node_id}] must be dict"
            )
        if "exits" not in node or not isinstance(node["exits"], dict):
            raise ValueError(
                f"hidden.location_graph[{node_id}] missing 'exits' dict"
            )
        if set(node["exits"].keys()) != set(DIRECTIONS):
            raise ValueError(
                f"hidden.location_graph[{node_id}].exits must have "
                f"exactly directions {DIRECTIONS}, "
                f"got {set(node['exits'].keys())}"
            )

    # hidden: current_node_id
    current = hidden.get("current_node_id")
    if current not in graph:
        raise ValueError(
            f"hidden.current_node_id ({current!r}) not in location_graph"
        )


def _require_int(
    d: dict[str, Any],
    key: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> None:
    if key not in d:
        raise ValueError(f"missing key: {key}")
    value = d[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} ({value}) < minimum ({minimum})")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} ({value}) > maximum ({maximum})")


# ---------------------------------------------------------------------
# Изоляция секций
# ---------------------------------------------------------------------

def get_visible(state: dict[str, Any]) -> dict[str, Any]:
    """Возвращает копию секции visible. Hidden не утекает."""
    if "visible" not in state:
        raise ValueError("state missing visible section")
    return copy.deepcopy(state["visible"])


def get_hidden(state: dict[str, Any]) -> dict[str, Any]:
    """Возвращает копию секции hidden. Visible не утекает."""
    if "hidden" not in state:
        raise ValueError("state missing hidden section")
    return copy.deepcopy(state["hidden"])