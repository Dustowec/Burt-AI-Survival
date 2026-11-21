"""Faith, statuses and crimes -- §33/§34 spec v0.7.0.

Pure core: no I/O, no asyncio, no LLM. Reads and writes the state dict.

Statuses: neutral (start) / paladin / heretic / killer.
Burt sees only paladin / heretic / killer ([STATE] -> "Faith: ...").

Chains (§33):
    paladin (cleric)      K1 20 goblin daggers + 2 goblin staffs
                          K2 help 5 (completed role quests, reset on fail)
                          K3 donate all money (0 coins -> auto) -> paladin
    heretic (necromancer) K1 10 goblin daggers
                          K2 deceive 3 NPCs (roll >= 3, one try per NPC)
                          K3 insult the cleric + donate all money -> heretic
    killer goes straight to K3 (heretic_3) and becomes heretic.

Crime (§34): killing a resident -> killer; all active quests fail;
rep -5 overall / -10 the victim's role; the victim's role is blocked
for life when it hands out quests; paladin -> killer also queues god's
wrath (1 * level, applied at the first cleric meeting) and blocks the
paladin chain.

NPC hostility (guard fight, cleric punishment + fight, necromancer
against a paladin, cleric against a heretic) is exported as a predicate
and a dialogue gate. NPC combat itself lives in npc_combat / loop.
"""
from __future__ import annotations

from burt import reputation


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

STATUS_NEUTRAL = "neutral"
STATUS_PALADIN = "paladin"
STATUS_HERETIC = "heretic"
STATUS_KILLER = "killer"

STATUSES: tuple[str, ...] = (
    STATUS_NEUTRAL, STATUS_PALADIN, STATUS_HERETIC, STATUS_KILLER,
)

# Who a killer used to be ("heretic-killer" is killer + heretic).
KILLER_FROM: tuple[str, ...] = (
    STATUS_NEUTRAL, STATUS_PALADIN, STATUS_HERETIC,
)

GOD_WRATH_PER_LEVEL: int = 1

CHAIN_PALADIN = "pala"
CHAIN_HERETIC = "heretic"

FAITH_ROLES: tuple[str, ...] = ("cleric", "necromancer")
CHAIN_BY_ROLE: dict[str, str] = {
    "cleric": CHAIN_PALADIN,
    "necromancer": CHAIN_HERETIC,
}
CHAIN_FIRST_STEP: dict[str, str] = {
    CHAIN_PALADIN: "pala_1",
    CHAIN_HERETIC: "heretic_1",
}
CHAIN_BY_QUEST: dict[str, str] = {
    "pala_1": CHAIN_PALADIN, "pala_2": CHAIN_PALADIN,
    "pala_3": CHAIN_PALADIN,
    "heretic_1": CHAIN_HERETIC, "heretic_2": CHAIN_HERETIC,
    "heretic_3": CHAIN_HERETIC,
}

K2_QUEST: dict[str, str] = {
    CHAIN_PALADIN: "pala_2",
    CHAIN_HERETIC: "heretic_2",
}
K3_QUEST: dict[str, str] = {
    CHAIN_PALADIN: "pala_3",
    CHAIN_HERETIC: "heretic_3",
}
KILLER_FIRST_STEP = "heretic_3"

# §32/§34: every named NPC is a resident (events are not).
RESIDENT_ROLES: frozenset[str] = frozenset({
    "merchant", "guard", "peasant", "peasant_woman", "elder",
    "tavernkeeper", "blacksmith", "fisherman", "child", "veteran",
    "cleric", "necromancer",
})

# After a crime: children and peasants flee, the rest have no dialogue.
FLEE_ROLES: frozenset[str] = frozenset({
    "child", "peasant", "peasant_woman",
})

# After a crime residents have no dialogue. The necromancer is the only
# exception: a killer may still take K3 from him. The cleric step of that
# chain stays unreachable on purpose -- the cleric fights the killer on
# sight, so the killer status is an execution, not a resettable state.
NO_TALK_AFTER_CRIME: frozenset[str] = RESIDENT_ROLES - {"necromancer"}

# Roles that hand out quests: 7 role-quest givers + the two chain givers.
QUEST_GIVERS: frozenset[str] = frozenset({
    "elder", "blacksmith", "merchant", "guard", "fisherman",
    "veteran", "tavernkeeper", "cleric", "necromancer",
})

DECEIVE_SUCCESS_MIN = 3


# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------

def new_state() -> dict:
    """Fresh faith block for a new life."""
    return {
        "status": STATUS_NEUTRAL,
        "killer_from": None,
        "chain": None,
        "k2_helped": 0,
        "k3_insulted": False,
        "paladin_chain_blocked": False,
        "heretic_chain_blocked": False,
        "punishment_pending": False,
        "deceive_attempts": {},
    }


def ensure_state(hidden: dict) -> dict:
    """Add missing faith keys (old saves) and return the block."""
    faith = hidden.setdefault("faith", {})
    if not isinstance(faith, dict):
        faith = {}
        hidden["faith"] = faith
    for key, value in new_state().items():
        faith.setdefault(key, value)
    return faith


def ensure_runtime(state: dict) -> None:
    """Sync hidden["faith"] and visible["faith"] (old saves included)."""
    hidden = state.setdefault("hidden", {})
    faith = ensure_state(hidden)
    status = faith.get("status", STATUS_NEUTRAL)
    if status not in STATUSES:
        status = STATUS_NEUTRAL
    faith["status"] = status
    state.setdefault("visible", {})["faith"] = status


def get_status(state: dict) -> str:
    faith = state.get("hidden", {}).get("faith") or {}
    status = faith.get("status", STATUS_NEUTRAL)
    return status if status in STATUSES else STATUS_NEUTRAL


def get_killer_from(state: dict) -> str | None:
    faith = state.get("hidden", {}).get("faith") or {}
    value = faith.get("killer_from")
    return value if value in KILLER_FROM else None


def set_status(state: dict, status: str,
               killer_from: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown faith status: {status!r}")
    faith = ensure_state(state.setdefault("hidden", {}))
    faith["status"] = status
    faith["killer_from"] = killer_from if status == STATUS_KILLER else None
    state.setdefault("visible", {})["faith"] = status


def status_line(state: dict) -> str | None:
    """[STATE] line; neutral is hidden from Burt."""
    status = get_status(state)
    if status == STATUS_NEUTRAL:
        return None
    return f"Faith: {status}"


# ---------------------------------------------------------------------
# Chain helpers
# ---------------------------------------------------------------------

def _all_quests(state: dict) -> list[dict]:
    return state.setdefault("hidden", {}).setdefault("quests_raw", [])


def _active_quest(state: dict, quest_id: str) -> dict | None:
    for entry in _all_quests(state):
        if entry.get("id") == quest_id and entry.get("status") == "active":
            return entry
    return None


def _set_progress(state: dict, quest_id: str, value: int) -> bool:
    entry = _active_quest(state, quest_id)
    if entry is None:
        return False
    entry["progress"] = int(value)
    return True


def active_chain(state: dict) -> str | None:
    for entry in _all_quests(state):
        if entry.get("status") == "active" and entry.get("chain"):
            return entry["chain"]
    return None


def active_chain_for_role(role: str, state: dict) -> bool:
    chain = CHAIN_BY_ROLE.get(role)
    if chain is None:
        return False
    return any(
        entry.get("status") == "active" and entry.get("chain") == chain
        for entry in _all_quests(state)
    )


def next_chain_step(role: str, state: dict) -> str | None:
    """Quest id this chain giver offers right now (None = no work)."""
    chain = CHAIN_BY_ROLE.get(role)
    if chain is None:
        return None
    faith = ensure_state(state.setdefault("hidden", {}))
    status = get_status(state)

    if active_chain_for_role(role, state):
        return None

    if status == STATUS_KILLER:
        if chain != CHAIN_HERETIC or faith.get("heretic_chain_blocked"):
            return None
        return KILLER_FIRST_STEP

    if status != STATUS_NEUTRAL:
        return None

    if chain == CHAIN_PALADIN and faith.get("paladin_chain_blocked"):
        return None
    if chain == CHAIN_HERETIC and faith.get("heretic_chain_blocked"):
        return None
    return CHAIN_FIRST_STEP[chain]


# ---------------------------------------------------------------------
# Chain progress (§33)
# ---------------------------------------------------------------------

def on_chain_issued(quest_id: str, state: dict) -> None:
    """The chain giver just handed out this step."""
    faith = ensure_state(state.setdefault("hidden", {}))
    faith["chain"] = CHAIN_BY_QUEST.get(quest_id)
    faith["k2_helped"] = 0
    faith["k3_insulted"] = False


def on_chain_complete(chain: str, state: dict) -> None:
    """The final step was completed: award the status.

    §33 + rules: the finale kills the parallel chain.
    """
    faith = ensure_state(state.setdefault("hidden", {}))
    if chain == CHAIN_PALADIN:
        set_status(state, STATUS_PALADIN)
    elif chain == CHAIN_HERETIC:
        set_status(state, STATUS_HERETIC)
    other = CHAIN_HERETIC if chain == CHAIN_PALADIN else CHAIN_PALADIN
    for entry in _all_quests(state):
        if entry.get("status") == "active" and entry.get("chain") == other:
            entry["status"] = "failed"
    faith["chain"] = None
    faith["k2_helped"] = 0
    faith["k3_insulted"] = False


def on_help_completed(state: dict, is_chain: bool = False) -> None:
    """K2 paladin: one fully closed role quest (chains do not count)."""
    if is_chain:
        return
    entry = _active_quest(state, K2_QUEST[CHAIN_PALADIN])
    if entry is None:
        return
    required = int(entry.get("required") or 0)
    progress = int(entry.get("progress", 0)) + 1
    entry["progress"] = min(required, progress) if required else progress


def on_quest_failed(state: dict) -> None:
    """K2 paladin: a failed quest resets the counter to 0."""
    _set_progress(state, K2_QUEST[CHAIN_PALADIN], 0)


def heretic_k2_active(state: dict) -> bool:
    """K2 heretic is the active step (lie counts, roll >= 3)."""
    return _active_quest(state, K2_QUEST[CHAIN_HERETIC]) is not None


def on_deceive(rep_role: str, node_id: str, roll: int,
               state: dict) -> tuple[bool, str]:
    """K2 heretic: roll >= 3, one attempt per NPC, failure -1 rep."""
    entry = _active_quest(state, K2_QUEST[CHAIN_HERETIC])
    if entry is None:
        return (False, "no quest")
    faith = ensure_state(state.setdefault("hidden", {}))
    attempts = faith.setdefault("deceive_attempts", {})
    key = f"{node_id}::{rep_role}"
    if key in attempts:
        return (False, "already tried")
    attempts[key] = True
    if roll >= DECEIVE_SUCCESS_MIN:
        required = int(entry.get("required") or 0)
        entry["progress"] = min(required, int(entry.get("progress", 0)) + 1)
        return (True, "deceived")
    reputation.change(state, rep_role, -1)
    return (False, "failed")


def on_insult_to_cleric(state: dict) -> bool:
    """K3 heretic: the successful threat against the cleric (step 1)."""
    entry = _active_quest(state, K3_QUEST[CHAIN_HERETIC])
    if entry is None:
        return False
    faith = ensure_state(state.setdefault("hidden", {}))
    if faith.get("k3_insulted"):
        return False
    faith["k3_insulted"] = True
    entry["progress"] = max(int(entry.get("progress", 0)), 1)
    return True


def donate_available(state: dict, role_key: str) -> bool:
    """The donate action belongs to the cleric (§33 K3)."""
    if role_key != "cleric":
        return False
    if _active_quest(state, K3_QUEST[CHAIN_PALADIN]) is not None:
        return True
    if _active_quest(state, K3_QUEST[CHAIN_HERETIC]) is None:
        return False
    faith = ensure_state(state.setdefault("hidden", {}))
    return bool(faith.get("k3_insulted"))


def donate(state: dict, role_key: str) -> dict | None:
    """Give every coin to the temple.

    Paladin: 0 coins auto-completes. Heretic/killer: the action is always
    required (0 coins do not auto-complete); the chain is handed in to the
    necromancer afterwards.
    """
    if not donate_available(state, role_key):
        return None
    wallet = state.setdefault("visible", {}).setdefault("wallet", {})
    coins = int(wallet.get("coin", 0))
    wallet["coin"] = 0

    pala = _active_quest(state, K3_QUEST[CHAIN_PALADIN])
    if pala is not None:
        pala["progress"] = max(1, int(pala.get("required") or 1))
        return {
            "chain": CHAIN_PALADIN,
            "quest_id": K3_QUEST[CHAIN_PALADIN],
            "coins": coins,
            "complete_now": True,
        }

    heretic = _active_quest(state, K3_QUEST[CHAIN_HERETIC])
    required = max(2, int(heretic.get("required") or 2))
    heretic["progress"] = required
    return {
        "chain": CHAIN_HERETIC,
        "quest_id": K3_QUEST[CHAIN_HERETIC],
        "coins": coins,
        "complete_now": False,
    }




# ---------------------------------------------------------------------
# Crime (§34)
# ---------------------------------------------------------------------

def on_resident_killed(role_key: str, rep_role: str, state: dict) -> dict:
    """Killing a resident: status, quests, reputation, quest-giver block."""
    hidden = state.setdefault("hidden", {})
    faith = ensure_state(hidden)
    prior = get_status(state)

    if prior == STATUS_KILLER:
        killer_from = faith.get("killer_from") or STATUS_NEUTRAL
    elif prior in KILLER_FROM:
        killer_from = prior
    else:
        killer_from = STATUS_NEUTRAL

    pending = bool(faith.get("punishment_pending")) or (
        prior == STATUS_PALADIN
    )
    set_status(state, STATUS_KILLER, killer_from)
    faith["punishment_pending"] = pending
    # A killer can never walk the paladin chain again.
    faith["paladin_chain_blocked"] = True
    faith["chain"] = None
    faith["k2_helped"] = 0
    faith["k3_insulted"] = False

    failed: list[str] = []
    for entry in _all_quests(state):
        if entry.get("status") == "active":
            entry["status"] = "failed"
            failed.append(entry.get("id", ""))

    hidden["reputation_overall"] = (
        int(hidden.get("reputation_overall", 0)) - 5
    )
    reputation.change(state, rep_role, -10)

    quest_giver = role_key in QUEST_GIVERS
    if quest_giver:
        killed = hidden.setdefault("killed_quest_givers", [])
        if role_key not in killed:
            killed.append(role_key)
        hidden.setdefault("role_quest_block", {})[role_key] = -1

    if role_key == "necromancer":
        faith["heretic_chain_blocked"] = True

    return {
        "status": STATUS_KILLER,
        "killer_from": killer_from,
        "failed_quests": failed,
        "quest_giver": quest_giver,
    }


def god_wrath(level: int) -> int:
    """§34: 1 * level, once."""
    return max(0, int(level)) * GOD_WRATH_PER_LEVEL


def take_punishment(state: dict) -> int:
    """Consume the queued god's wrath; 0 when nothing is pending."""
    faith = ensure_state(state.setdefault("hidden", {}))
    if not faith.get("punishment_pending"):
        return 0
    faith["punishment_pending"] = False
    level = int(state.get("visible", {}).get("level", 1))
    return god_wrath(level)


def hostility(status: str, role: str) -> str:
    """How this NPC reacts on a meeting (§34).

    Exported for the NPC-combat task: fight / flee / none.
    """
    if status == STATUS_KILLER:
        if role in ("guard", "cleric"):
            return "fight"
        if role in FLEE_ROLES:
            return "flee"
        return "none"
    if status == STATUS_PALADIN and role == "necromancer":
        return "fight"
    if status == STATUS_HERETIC and role == "cleric":
        return "fight"
    return "none"


def is_killer(state: dict) -> bool:
    return get_status(state) == STATUS_KILLER


def cannot_talk_after_crime(role_key: str) -> bool:
    """§34: residents stop talking after the crime.

    Status-free check: the caller already knows it is dealing with a
    killer. The necromancer is the only resident left out (K3 giver).
    """
    return role_key in NO_TALK_AFTER_CRIME


def can_talk_to(state: dict, role_key: str) -> bool:
    """§34: may Burt open a dialogue with this role right now?

    - a hostile resident is handled by combat, not dialogue;
    - non-residents (mage_event / preacher_event) stay talkable;
    - after a crime only the necromancer remains talkable: a killer can
      still take K3 from him (the cleric step is intentionally blocked
      because the cleric fights the killer on sight).
    """
    if hostility(get_status(state), role_key) == "fight":
        return False
    if role_key not in RESIDENT_ROLES:
        return True
    if get_status(state) == STATUS_KILLER:
        return role_key == "necromancer"
    return True

