#!/usr/bin/env python3
"""main.py — BURT game entry point (async orchestrator).

One turn:
  1. Build sensory report from visible state.
  2. Inject hunger / sleep signals if needed.
  3. Build menu of available actions.
  4. Send report + menu to LLM.
  5. Parse the choice, execute the action.
  6. Post-turn: death check, forced sleep, day wrap, quest expiry.
  7. Save state.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from dataclasses import dataclass, field
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config
from burt import (
    dice,
    epitaphs as epitaphs_mod,
    events,
    faith,
    hunger,
    loop,
    llm_client,
    magic as magic_mod,
    prompts,
    progression,
    quests,
    resurrection,
    sensory,
    sleep as sleep_mod,
    skills,
    state as state_mod,
    state_io,
    search as search_mod,
)
from burt.npc import DialogueEngine, load_replicas
from burt.trace import Trace
from burt.plugin_log import (
    PluginLogger, LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR, preview_payload,
)
from burt.game_session import GameSessionLog


logger = logging.getLogger("burt.main")


# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

DEFAULT_STATE_PATH = Path("state.json")
DEFAULT_MAX_STEPS = 10_000
CONFIG_HASH = "v0.7.0"





@dataclass
class TurnResult:
    """Return value from run_turn including logging metadata."""
    game_over: bool
    history: list[dict]
    start_state: dict = field(default_factory=dict)
    sensory_report: str = ""
    llm_prompt: str = ""
    llm_response: str = ""
    action_key: str = ""
    action_label: str = ""
    result_events: list = field(default_factory=list)
    result_game_over: bool = False
    result_new_hp: int | None = None
    result_search_result: str | None = None
    result_direction_moved: str | None = None
    end_state: dict | None = None
    error: str | None = None
    # new_bug §6: set by run_turn on death, consumed by game_loop when the
    # resurrection roll fails. The epitaph is written only for a final death.
    death_cause: str | None = None

# ---------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------

def _sync_meta_from_hidden(state: dict) -> None:
    hidden = state.setdefault("hidden", {})
    meta = state.setdefault("meta", {})
    if "step" in hidden:
        meta["step"] = hidden["step"]
    if "day" in hidden:
        meta["day"] = hidden["day"]
    visible = state.setdefault("visible", {})
    if "day" in hidden:
        visible["date"] = state_mod.format_date(hidden["day"])


def _sync_hidden_from_meta(state: dict) -> None:
    meta = state.setdefault("meta", {})
    hidden = state.setdefault("hidden", {})
    hidden.setdefault("step", meta.get("step", 0))
    hidden.setdefault("day", meta.get("day", 1))


def _ensure_runtime_fields(state: dict) -> None:
    hidden = state.setdefault("hidden", {})
    hidden.setdefault("resurrection_used_today", False)
    hidden.setdefault("micro_location", {"active": False})
    hidden.setdefault("combat", None)
    hidden.setdefault("combat_npc_role", None)
    hidden.setdefault("current_mode", "exploring")
    hidden.setdefault("last_action", None)
    hidden.setdefault("same_action_count", 0)
    hidden.setdefault("diary", None)
    hidden.setdefault("day_log", [])
    hidden.setdefault("diary_written_today", False)
    hidden.setdefault("diary_skipped_today", False)
    hidden.setdefault("injected_day", 0)
    hidden.setdefault("dot_effects", [])
    hidden.setdefault("pending_encounter", None)
    hidden.setdefault("encounter_revealed", False)
    # §26: tool text is delivered to the next prompt once.
    hidden.setdefault("pending_tool_output", None)
    # §35 economy: price modifiers and the paid room of tonight.
    hidden.setdefault("has_room_tonight", False)
    hidden.setdefault("prices_by_node", {})
    hidden.setdefault("price_modifier", None)
    # §9 magic: state added after skill/trade wiring (old saves keep working).
    magic_mod.ensure_state(hidden)

    visible = state.setdefault("visible", {})
    visible.setdefault("skills_visible", [])
    # new_bug §2: one date format even for old saves (legacy suffix -> "N day").
    day = hidden.get("day", state.get("meta", {}).get("day", 1))
    visible["date"] = state_mod.format_date(day)
    # §7: level/xp for saves made before progression existed.
    progression.ensure_state(visible)
    # §8: repair skill records and re-sync the visible mirror.
    skills.ensure_state(hidden, visible)
    # §33: faith statuses and chain counters (old saves get neutral).
    faith.ensure_runtime(state)
    # §13: repair curse/blessing records and mirror them into visible.
    events.ensure_state(hidden)
    events.sync_visible(hidden, visible)


# ---------------------------------------------------------------------
# New life
# ---------------------------------------------------------------------

def make_new_state(
    life: int = 1,
    memory: str | None = None,
    memory_cause: str | None = None,
    epitaphs_dir: Path | None = None,
) -> dict:
    # Если есть epitaphs_dir — читаем последнюю эпитафию как память
    memory_from_epitaphs = None
    if epitaphs_dir is not None:
        try:
            last = epitaphs_mod.get_last_epitaph(epitaphs_dir)
            if last:
                memory_from_epitaphs = last["epitaph"]
        except (OSError, TypeError, ValueError):
            # Не валидный путь или файл отсутствует — игнорируем
            pass

    # Приоритет: явная memory > epitaphs > None
    final_memory = memory or memory_from_epitaphs
    return state_mod.create_initial_state(
        life=life,
        session_uuid=str(uuid.uuid4()),
        config_hash=CONFIG_HASH,
        session_started=datetime.now(timezone.utc).isoformat(),
        memory=final_memory,
        memory_cause=memory_cause,
    )


def load_dialogue_engine(
    replicas_path: Path | None = None,
) -> DialogueEngine | None:
    """Load and return a DialogueEngine from replicas.json."""
    if replicas_path is None:
        replicas_path = Path("replicas.json")
    if not replicas_path.exists():
        return None
    try:
        return DialogueEngine(load_replicas(str(replicas_path)))
    except (OSError, json.JSONDecodeError, KeyError):
        logger.exception("Failed to load dialogue engine")
        return None


# ---------------------------------------------------------------------
# Logging helpers (П.2, П.3, П.4)
# ---------------------------------------------------------------------

def _determine_death_cause(state: dict, action: loop.Action) -> str:
    """П.2: pure helper to determine what killed Burt."""
    visible = state["visible"]
    hidden = state["hidden"]
    hp = visible.get("hp", 0)

    # §34: a queued god's wrath (paladin -> killer) sets an explicit cause.
    override = hidden.get("death_cause_override")
    if override:
        return override

    # 1. Combat action
    if action.key.startswith("attack_") or action.key in ("block", "flee"):
        return "combat"

    # 2. Micro event (god_wrath, stone, tree, etc.)
    micro = hidden.get("micro_location") or {}
    if micro.get("active") and micro.get("damage", 0) > 0:
        return micro.get("event_type", "micro_event")

    # 3. Osmotret penalty
    if action.key == "osmotret" and hidden.get("same_action_count", 0) >= 3:
        return "osmotret_penalty"

    # 4. Hunger (hp > 0 because hunger doesn't zero HP in state directly)
    if hp > 0 and not visible.get("eat", True) and hidden.get("step") in hunger.HUNGER_DEATH_AT:
        return "hunger"

    return "unknown"


def _log_death(state: dict, action: loop.Action) -> None:
    """П.2: log death with cause, step, day, hp, location."""
    visible = state["visible"]
    hidden = state["hidden"]
    cause = _determine_death_cause(state, action)
    
    logger.warning(
        "Burt died | cause=%s | step=%d day=%d hp=%d | location=%s",
        cause,
        hidden.get("step", 0),
        hidden.get("day", 1),
        visible.get("hp", 0),
        visible.get("location", {}).get("name", "Unknown")
    )


def _format_day_log(day_log: list[dict]) -> str:
    """Format the day's accumulated log for the diary prompt."""
    if not day_log:
        return "(no events)"
    parts: list[str] = []
    for entry in day_log:
        parts.append(
            f"Step {entry.get('step', 0)}, {entry.get('location', '?')}:\n"
            f"Burt: {entry.get('llm_message', '')}\n"
            f"Action: {entry.get('action', '?')}"
        )
    return "\n\n".join(parts)


def _store_epitaph(state: dict, cause: str, text: str) -> None:
    """Store the final epitaph in meta['memory']."""
    state.setdefault("meta", {})["memory"] = text
    state["meta"]["memory_cause"] = cause
    logger.info("epitaph cause=%s: %s", cause, text)


async def _write_diary(state: dict, day_log: list[dict]) -> None:
    """Call LLM with DIARY_PROMPT, store result in hidden['diary']."""
    hidden = state["hidden"]
    day = hidden.get("day", 1)
    previous = hidden.get("diary")
    prev_text = previous if previous else "(no previous entry)"
    body = _format_day_log(day_log)
    user_msg = (
        f"Day {day}.\n\n"
        f"Your previous entry: {prev_text}\n\n"
        f"Today's events:\n{body}\n\n"
        f"Write your diary entry for today."
    )
    answer, _ = await llm_client.call_llm(
        prompts.DIARY_PROMPT, user_msg, [],
    )
    hidden["diary"] = answer
    hidden["diary_written_today"] = True
    logger.info("diary day=%d: %s", day, answer)


async def _write_epitaph(
    state: dict, cause: str, epitaphs_dir: Path | None = None,
) -> None:
    """Call LLM with SPIRIT_PROMPT, store epitaph in meta['memory'] and epitaphs.json."""
    hidden = state["hidden"]
    days = hidden.get("day", 1)
    diary = hidden.get("diary")
    user_msg = f"You lived {days} days. You died from {cause}."
    if diary:
        user_msg += f"\n\nYour last diary entry:\n{diary}"
    answer, _ = await llm_client.call_llm(
        prompts.SPIRIT_PROMPT, user_msg, [],
    )
    _store_epitaph(state, cause, answer)

    # Сохраняем в epitaphs.json
    if epitaphs_dir is not None:
        life = state["meta"]["life"]
        epitaphs_mod.add_epitaph(epitaphs_dir, life, answer, cause, days)
        logger.info("epitaph saved to epitaphs.json life=%d", life)


async def _write_memory_summary(
    state: dict, epitaphs_dir: Path,
) -> None:
    """При жизни >= 10, читаем все эпитафии и вызываем MEMORY_SUMMARY_PROMPT."""
    meta = state["meta"]
    if meta.get("life", 1) < 10:
        return

    epitaphs = epitaphs_mod.load_epitaphs(epitaphs_dir)
    if len(epitaphs) < 10:
        return

    # Собираем все эпитафии
    user_msg = "\n\n".join(
        f"Life {e['life']} ({e['days']} days, {e['cause']}):\n{e['epitaph']}"
        for e in epitaphs
    )

    answer, _ = await llm_client.call_llm(
        prompts.MEMORY_SUMMARY_PROMPT, user_msg, [],
    )
    meta["memory_summary"] = answer
    logger.info("memory_summary written life=%d", meta["life"])


def _build_system_prompt(state: dict, menu: list | None = None) -> str:
    """Build BURT_SYSTEM_PROMPT with optional memory_summary injection.

    Spec 9/23: cast is a gated choice (staff + spell + teacher). It is
    mentioned only when the current menu really offers it, so the hint
    and the option always appear together.
    """
    base = prompts.BURT_SYSTEM_PROMPT
    meta = state.get("meta", {})
    summary = meta.get("memory_summary")
    if summary:
        base += f"\n\nAcross all your lives you understood:\n{summary}"
    if menu and any(a.key == "cast" for a in menu):
        base += "\n\nYour magic is ready: cast is in the menu."
    return base


def _log_result_events(result: loop.ActionResult) -> None:
    """П.3: log all result events at INFO (noisy but explicit)."""
    for ev in result.events:
        logger.info("event: %s", ev)


def _log_inject(step: int, day: int, mode: str, menu: list[loop.Action], user_msg: str) -> None:
    """П.4: log LLM inject (header+menu INFO, full DEBUG)."""
    actions_str = ", ".join(f"{i}={a.key}" for i, a in enumerate(menu))
    logger.info(
        "inject | mode=%s | step=%d day=%d | actions=%d",
        mode, step, day, len(menu)
    )
    logger.info("inject menu: %s", actions_str)
    logger.debug("inject full:\n%s", user_msg)


# ---------------------------------------------------------------------
# Logging helpers (§38, §39)
# ---------------------------------------------------------------------

def plugin_preview_chars(plugin: PluginLogger | None) -> int:
    """Preview length for react payloads when DEBUG=False (§38)."""
    if plugin is None:
        return config.LOG_PREVIEW_CHARS
    return getattr(plugin, "_preview_chars", config.LOG_PREVIEW_CHARS)


def plugin_level_for_parse(plugin: PluginLogger, choice_found: bool) -> int:
    """INFO when CHOICE parsed, WARN otherwise (§39)."""
    if choice_found:
        return LEVEL_INFO
    return LEVEL_WARN


# ---------------------------------------------------------------------
# Turn loop
# ---------------------------------------------------------------------

async def run_turn(
    state: dict,
    history: list[dict],
    rng,
    dry_run: bool,
    game_session: GameSessionLog | None = None,
    epitaphs_dir: Path | None = None,
    dialogue_engine: DialogueEngine | None = None,
    plugin: PluginLogger | None = None,
    trace: Trace | None = None,
) -> TurnResult:
    visible = state["visible"]
    hidden = state["hidden"]
    day_before = hidden.get("day", 1)
    day = hidden.get("day", 1)
    step = hidden.get("step", 0)

    # -- -1. Open a new floor (§38): one turn = one turn_uuid.
    turn = None
    if not dry_run and trace is not None:
        turn = trace.new_turn()
        if plugin is not None:
            plugin.event(LEVEL_INFO, "turn_start", {
                "day": day, "step": step, "mode": hidden.get("current_mode"),
            })

    # -- 0. DoT tick at start of turn ----------------------------
    hp_lost = 0
    if not dry_run:
        hp_lost, dot_game_over = search_mod.tick_dot(state)
        search_mod.sync_poisoned_effect(state)
        if dot_game_over:
            logger.warning(
                "Burt died | cause=diarrhea | step=%d day=%d hp=0 | location=%s",
                hidden.get("step", 0),
                hidden.get("day", 1),
                visible.get("location", {}).get("name", "Unknown"),
            )
            if game_session:
                game_session.append_special(
                    day=day,
                    event="death",
                    description="Burt died from diarrhea (DoT)",
                )
            # new_bug §6: the epitaph is written by game_loop only when
            # the resurrection roll fails (roll != 6).
            _sync_meta_from_hidden(state)
            return TurnResult(game_over=True, history=history,
                              death_cause="diarrhea")

    # -- 1. Sensory report ----------------------------------------
    # §11: the reason comes first, the report after it. It is a fact
    # produced by the previous turn, so it is read straight from state.
    report = sensory.format_sensory_report(visible)
    inject_text = hidden.pop("pending_event_inject", None)
    if inject_text:
        report = f"{inject_text}\n\n{report}"
    if hp_lost > 0:
        report = f"You take {hp_lost} damage from poison.\n\n" + report

    # -- 1a. §26: the previous free tool result (ReAct observation) --
    pending_tool = hidden.pop("pending_tool_output", None)
    if pending_tool:
        report = f"{pending_tool}\n\n{report}"

    # -- 1b. Diary / punishment injection on new day --------------
    if hidden.get("injected_day", 0) != hidden.get("day", 1):
        if hidden.get("diary_skipped_today", False):
            report += (
                "\n\nYou are punished by the gods of oblivion "
                "for irresponsibility."
            )
            hidden["diary_skipped_today"] = False
        elif hidden.get("diary"):
            report += f"\n\nYour last diary entry:\n{hidden['diary']}"
        hidden["injected_day"] = hidden.get("day", 1)

    # -- 1c. Memory injection from previous lives -----------------
    meta = state.get("meta", {})
    if meta.get("memory") and meta.get("life", 1) > 1:
        report += f"\n\nYou remember your past life:\n{meta['memory']}"

    # -- 2. Hunger / sleep injection ------------------------------
    if hunger.should_inject_hunger(step, visible.get("eat", False)):
        report += "\n\nYou are hungry."
    if sleep_mod.should_inject_tired(step):
        report += "\n\nYou are tired." if step < 20 else "\n\nYou are very tired."

    # -- 2b. Repetition signal ------------------------------------
    same = hidden.get("same_action_count", 0)
    if same >= 2:
        report += f"\n\nYou have done this {same + 1} times in a row. Do something else."

    # -- 3. Menu --------------------------------------------------
    menu = loop.build_menu(visible, state, dialogue_engine=dialogue_engine)

    # -- 4. Dry run: just print -----------------------------------
    if dry_run:
        print("=" * 60)
        print(f"[STEP {step}] day={hidden.get('day', 1)} mode={hidden.get('current_mode')}")
        print("-" * 60)
        print(report)
        print("-" * 60)
        print("Menu:")
        for i, a in enumerate(menu):
            print(f"  {i}. [{a.key}] {a.label}")
        print("=" * 60)
        return TurnResult(game_over=False, history=history,
                         start_state=state, sensory_report=report)

    # -- 5. LLM call (layer: react, §38) ---------------------------
    menu_text = "\n".join(f"{i}. {a.label}" for i, a in enumerate(menu))
    llm_prompt = f"{report}\n\nMENU:\n{menu_text}\n\nCHOICE:"

    _log_inject(step, hidden.get("day", 1), hidden.get("current_mode", "exploring"), menu, llm_prompt)

    call_uuid = trace.new_call() if (trace is not None and not dry_run) else None
    if plugin is not None:
        plugin.state_change("running", "waiting_llm")
        plugin.react_exchange("llm_request", prompt=llm_prompt, call_uuid=call_uuid)

    try:
        answer, history = await llm_client.call_llm(
            _build_system_prompt(state, menu), llm_prompt, history,
        )
    except Exception as exc:
        if plugin is not None:
            plugin.die("LLM call failed", exc, event="llm_error",
                       layer="react", call_uuid=call_uuid)
        raise

    if plugin is not None:
        plugin.state_change("waiting_llm", "running")
        plugin.react_exchange("llm_response", response=answer, call_uuid=call_uuid)

    # P.5: No truncation
    logger.info("LLM: %s", answer)

    # -- 6. Parse and execute (layers: interaction, tool) ----------
    # new_bug §8: strict parse, one re-ask with a kick, then a
    # deterministic fallback. Prose without a CHOICE line is not guessed.
    action, parse_reason = loop.parse_choice_strict(answer, menu)
    if action is None:
        logger.warning(
            "Invalid CHOICE (attempt 1/2): %s | answer=%s",
            parse_reason, answer,
        )
        retry_call_uuid = (
            trace.new_call() if (trace is not None and not dry_run) else None
        )
        if plugin is not None:
            plugin.state_change("running", "waiting_llm")
            plugin.react_exchange(
                "llm_request", prompt=loop.INVALID_CHOICE_KICK,
                call_uuid=retry_call_uuid,
            )
        try:
            answer, history = await llm_client.call_llm(
                _build_system_prompt(state, menu), loop.INVALID_CHOICE_KICK, history,
            )
        except Exception as exc:
            if plugin is not None:
                plugin.die("LLM retry call failed", exc, event="llm_error",
                           layer="react", call_uuid=retry_call_uuid)
            raise
        if plugin is not None:
            plugin.state_change("waiting_llm", "running")
            plugin.react_exchange(
                "llm_response", response=answer, call_uuid=retry_call_uuid,
            )
        logger.info("LLM (retry): %s", answer)

        action, parse_reason = loop.parse_choice_strict(answer, menu)
        if action is None:
            logger.warning(
                "Invalid CHOICE (attempt 2/2): %s | answer=%s",
                parse_reason, answer,
            )
            action = loop.fallback_action(menu)
            fallback_used = True
        else:
            fallback_used = False
        call_uuid = retry_call_uuid
    else:
        fallback_used = False

    logger.info("Action: %s (%s)", action.key, action.label)

    if plugin is not None:
        has_choice = any(
            line.strip().upper().startswith("CHOICE:")
            for line in answer.splitlines()
        )
        plugin.interaction(
            "parse_ok" if not fallback_used else "parse_warn",
            {
                "choice_found": has_choice,
                "fallback_used": fallback_used,
                "action": action.key,
                "menu_size": len(menu),
            },
            level=plugin_level_for_parse(plugin, not fallback_used),
            call_uuid=call_uuid,
        )
        if plugin.debug:
            plugin.state_change("running", "writing_state")

    hidden.setdefault("day_log", []).append({
        "step": hidden.get("step", 0),
        "location": visible.get("location", {}).get("name", "?"),
        "llm_message": answer,
        "action": action.key,
    })

    if action.key == "write_diary_and_go_sleep":
        await _write_diary(state, hidden["day_log"])

    tool_call_uuid = trace.new_call() if (trace is not None and not dry_run) else None
    if plugin is not None:
        plugin.tool("tool_call", {"action": action.key, "label": action.label},
                    call_uuid=tool_call_uuid)

    result = loop.execute_action(action, state, rng=rng,
                                 dialogue_engine=dialogue_engine)

    # §11: the world event of this turn is shown to the model once,
    # as the first line of the next prompt (not kept in history).
    if result.inject:
        hidden["pending_event_inject"] = result.inject

    # §26: a free tool ends the turn but its text goes to the next prompt.
    if (action.key in loop.TOOL_KEYS
            and not (result.events
                     and result.events[0].startswith("Error:"))):
        hidden["pending_tool_output"] = "\n".join(result.events) or None

    if plugin is not None:
        plugin.tool(
            "tool_result",
            {
                "action": action.key,
                "events": len(result.events),
                "game_over": result.game_over,
                "hp": visible.get("hp", 0),
            },
            call_uuid=tool_call_uuid,
        )
        if plugin.debug:
            plugin.state_change("writing_state", "running")

    _log_result_events(result)

    # -- 7. Save history (trim if too long) -----------------------
    if len(history) > 40:
        history = history[-20:]

    # -- 8. Game over? --------------------------------------------
    if result.game_over:
        death_cause = _determine_death_cause(state, action)
        _log_death(state, action)
        # new_bug §6: the epitaph belongs to a FINAL death; game_loop
        # writes it only when the resurrection roll fails (roll != 6).
        _sync_meta_from_hidden(state)
        # §34: the god's wrath cause is consumed by this death only.
        hidden.pop("death_cause_override", None)
        if game_session:
            game_session.append_turn(
                day=day,
                step=hidden.get("step", 0),
                mode=hidden.get("current_mode", "exploring"),
                location=visible.get("location", {}).get("name", "?"),
                prompt=llm_prompt,
                response=answer,
                action_key=action.key,
                action_label=action.label,
                events=result.events,
                hp=visible.get("hp", 0),
                hp_max=visible.get("hp_max", 0),
                game_over=True,
            )
        if plugin is not None:
            plugin.event(LEVEL_INFO, "death", {"cause": death_cause})
            plugin.event(LEVEL_INFO, "turn_complete", {
                "game_over": True, "hp": visible.get("hp", 0),
            })
        return TurnResult(game_over=True, history=history,
                         start_state=state, sensory_report=report,
                         llm_prompt=llm_prompt, llm_response=answer,
                         action_key=action.key, action_label=action.label,
                         result_events=result.events, result_game_over=True,
                         result_new_hp=visible.get("hp"), end_state=state,
                         death_cause=death_cause)

    # -- 9. Post-turn: hunger death check -------------------------
    death_outcome = _check_hunger_death(state)
    if death_outcome == "final_death":
        logger.warning(
            "Burt died | cause=hunger | step=%d day=%d hp=%d | location=%s",
            hidden.get("step", 0),
            hidden.get("day", 1),
            visible.get("hp", 0),
            visible.get("location", {}).get("name", "Unknown")
        )
        # new_bug §6: the epitaph is written by game_loop only when
        # the resurrection roll fails (roll != 6).
        if game_session:
            game_session.append_special(
                day=day,
                event="death",
                description="Burt died from hunger",
            )
        if plugin is not None:
            plugin.event(LEVEL_INFO, "death", {"cause": "hunger"})
        _sync_meta_from_hidden(state)
        return TurnResult(game_over=True, history=history,
                         start_state=state, sensory_report=report,
                         llm_prompt=llm_prompt, llm_response=answer,
                         action_key=action.key, action_label=action.label,
                         result_events=result.events, result_game_over=True,
                         result_new_hp=visible.get("hp"), end_state=state,
                         death_cause="hunger")

    # -- 10. Forced sleep on step 20 ------------------------------
    step_now = hidden.get("step", 0)
    chose_sleep = action.key in ("sleep", "write_diary_and_go_sleep")
    if sleep_mod.is_forced_sleep(step_now, chose_sleep):
        if hidden.get("current_mode") != "combat":
            logger.info("Forced sleep (step %d)", step_now)
            _do_sleep(state)
        else:
            logger.info("Forced sleep blocked (in combat, step %d)", step_now)
            # Invariant: a state on disk never has step > DAY_STEPS.
            # The tick that pushed the counter past the day was the
            # combat entry; the day wraps on the turn the fight ends.
            if step_now > state_mod.DAY_STEPS:
                hidden["step"] = state_mod.DAY_STEPS
                logger.warning(
                    "Step clamped to %d while in combat; "
                    "the day wraps after the fight",
                    state_mod.DAY_STEPS,
                )

    # -- 11. Daily expiry -----------------------------------------
    quests.expire_blockades(state)
    quests.expire_deceit_penalties(state)

    # -- 12. Context reset on new day -----------------------------
    day_after = hidden.get("day", 1)
    if day_after > day_before:
        history = []

    # -- 13. Sync meta and save -----------------------------------
    _sync_meta_from_hidden(state)

    # -- Log the turn (§2: gameplay log, §38: floor closed) --------
    if game_session:
        game_session.append_turn(
            day=day,
            step=hidden.get("step", 0),
            mode=hidden.get("current_mode", "exploring"),
            location=visible.get("location", {}).get("name", "?"),
            prompt=llm_prompt,
            response=answer,
            action_key=action.key,
            action_label=action.label,
            events=result.events,
            hp=visible.get("hp", 0),
            hp_max=visible.get("hp_max", 0),
            game_over=False,
        )
    if plugin is not None:
        plugin.event(LEVEL_INFO, "turn_complete", {
            "day": day,
            "step": hidden.get("step", 0),
            "action": action.key,
            "hp": visible.get("hp", 0),
        })

    return TurnResult(game_over=False, history=history,
                     start_state=state, sensory_report=report,
                     llm_prompt=llm_prompt, llm_response=answer,
                     action_key=action.key, action_label=action.label,
                     result_events=result.events, result_game_over=False,
                     result_new_hp=visible.get("hp"),
                     result_search_result=getattr(result, "search_result", None),
                     result_direction_moved=getattr(result, "direction_moved", None),
                     end_state=state)

def _check_hunger_death(state: dict) -> str:
    """Проверка смерти от голода.

    Возвращает "final_death" если смерть от голода, иначе "no_death".
    Воскрешение обрабатывается отдельно в game_loop.
    """
    visible = state["visible"]
    hidden = state["hidden"]
    step = hidden.get("step", 0)
    eat = visible.get("eat", False)

    if step not in hunger.HUNGER_DEATH_AT:
        return "no_death"
    if eat:
        return "no_death"

    return "final_death"


def _do_sleep(state: dict) -> None:
    """Forced sleep — same helper as voluntary sleep (new_bug §7)."""
    loop._apply_sleep_state(state)
    logger.info("Slept. day=%d step=0", state["hidden"].get("day", 1))


# ---------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------

async def game_loop(
    state: dict,
    history: list[dict],
    max_steps: int,
    dry_run: bool,
    state_path: Path,
    game_session: GameSessionLog | None = None,
    epitaphs_dir: Path | None = None,
    dialogue_engine: DialogueEngine | None = None,
    plugin: PluginLogger | None = None,
    trace: Trace | None = None,
) -> dict:
    """Run turns until max_steps / Ctrl+C. Returns the CURRENT state.

    new_bug §0: after any number of deaths the returned state is the last
    life, so main() saves the actual life, not life 1.
    """
    rng = dice.roll_d6
    step_count = 0
    epitaphs_dir = epitaphs_dir or state_path.parent

    if plugin is not None:
        plugin.event(LEVEL_INFO, "loop_start", {"max_steps": max_steps})
        plugin.state_change("init", "running")

    while step_count < max_steps:
        try:
            turn_result = await run_turn(
                state, history, rng, dry_run, game_session,
                epitaphs_dir, dialogue_engine, plugin, trace,
            )
            game_over = turn_result.game_over
            history = turn_result.history
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception:
            logger.exception("Unhandled error in turn")
            raise

        step_count += 1

        if dry_run:
            break

        if game_over:
            hidden = state.setdefault("hidden", {})
            # Resurrection mercy is one per day (§4, hunger.py).
            if hidden.get("resurrection_used_today", False):
                logger.info(
                    "Death after a resurrection today - final death, no roll",
                )
                outcome = resurrection.ResurrectionOutcome.FAILED
            else:
                outcome = resurrection.check_resurrection(rng)
                logger.info("Resurrection roll -> %s", outcome)

            if outcome == resurrection.ResurrectionOutcome.SUCCESS:
                # Бурт воскресает в том же мире
                visible = state.setdefault("visible", {})
                visible["hp"] = resurrection.RESURRECTION_HP
                visible["hp_max"] = max(
                    resurrection.RESURRECTION_HP,
                    visible.get("hp_max", 10),
                )
                hidden["hp_raw"] = resurrection.RESURRECTION_HP
                hidden["resurrection_used_today"] = True
                logger.info(
                    "Resurrected by divine mercy (roll=6, %d HP)",
                    resurrection.RESURRECTION_HP,
                )
                if game_session:
                    game_session.append_special(
                        day=hidden.get("day", 1),
                        event="resurrection",
                        description="Burt resurrected by dice roll",
                    )
                if plugin is not None:
                    plugin.event(LEVEL_INFO, "resurrection", {
                        "hp": resurrection.RESURRECTION_HP,
                    })
            else:
                # Если FAILED — пишем эпитафию и создаём новую жизнь.
                # new_bug §6: только окончательная смерть (roll != 6).
                old_life = state["meta"]["life"]
                try:
                    await _write_epitaph(
                        state,
                        turn_result.death_cause or "unknown",
                        epitaphs_dir,
                    )
                except Exception:
                    logger.exception(
                        "Failed to write epitaph; new life without memory"
                    )
                new_life = old_life + 1

                # Пишем память в новую жизнь из epitaphs
                new_state = make_new_state(
                    life=new_life,
                    epitaphs_dir=epitaphs_dir,
                )
                _sync_hidden_from_meta(new_state)
                _ensure_runtime_fields(new_state)
                # new_bug §0: replace the state in place so the caller's
                # reference and the final save always see the current life.
                state.clear()
                state.update(new_state)
                history = []  # <-- wipe LLM context between lives (bug fix)

                # Проверяем memory_summary при жизни >= 10
                if state["meta"].get("life", 1) >= 10 and epitaphs_dir is not None:
                    await _write_memory_summary(state, epitaphs_dir)

                # The new life inherits the epitaph of the dead one, so
                # the flag describes the NEW state, not the dying life.
                inherited = bool(state["meta"].get("memory"))
                logger.info(
                    "Game over (life %d) → new life %d started (memory=%s)",
                    old_life, new_life, "yes" if inherited else "no",
                )

        # Save the CURRENT life (after resurrection or a new life), so a
        # Ctrl+C / crash right here never leaves a dead state on disk.
        _sync_meta_from_hidden(state)
        try:
            state_io.save_state(state_path, state)
        except Exception:
            logger.exception("Failed to save state")

    logger.info("Loop finished after %d turns", step_count)
    return state
# CLI
# ---------------------------------------------------------------------

def _save_after_crash(state: dict, state_path: Path) -> None:
    """A crash must not cost the run: save what we have (spec 30).

    save_state validates before writing, so a half-mutated state never
    overwrites a good file. When validation fails the raw copy goes to
    crashes/ for a post-mortem and state.json stays untouched.
    """
    try:
        _sync_meta_from_hidden(state)
        state_io.save_state(state_path, state)
        logger.info("State saved after crash to %s", state_path)
        return
    except Exception:
        logger.exception("Failed to save state after crash")

    try:
        crash_dir = Path(config.CRASH_DIR)
        crash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump = crash_dir / f"state_{stamp}.json"
        dump.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Crash state dumped to %s", dump)
    except Exception:
        logger.exception("Failed to dump crash state")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="BURT game entry point")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH,
                        help=f"State file (default: {DEFAULT_STATE_PATH})")
    parser.add_argument("--new", action="store_true",
                        help="Start a new life (ignore existing state)")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                        help=f"Stop after N turns (default: {DEFAULT_MAX_STEPS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report+menu, no LLM call")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(args.log_level)

    state_path = args.state
    if args.new:
        state = make_new_state(life=1)
        _sync_hidden_from_meta(state)
        _ensure_runtime_fields(state)
        logger.info("New state created (life=1)")
    elif state_io.state_exists(state_path):
        try:
            state = state_io.load_state(state_path)
            _sync_hidden_from_meta(state)
            _ensure_runtime_fields(state)
            logger.info("Loaded state from %s (life=%d, day=%d)",
                        state_path, state["meta"]["life"], state["meta"]["day"])
        except Exception:
            logger.exception("Failed to load state; starting new")
            state = make_new_state(life=1)
            _sync_hidden_from_meta(state)
            _ensure_runtime_fields(state)
    else:
        logger.info("No state at %s; starting new life", state_path)
        state = make_new_state(life=1)
        _sync_hidden_from_meta(state)
        _ensure_runtime_fields(state)

    if args.new or not state_io.state_exists(state_path):
        try:
            _sync_meta_from_hidden(state)
            state_io.save_state(state_path, state)
            logger.info("Initial state saved to %s", state_path)
        except Exception:
            logger.exception("Failed to save initial state")
            return 1

    history: list[dict] = []
    trace = Trace()
    plugin = PluginLogger(
        log_dir=config.LOG_DIR,
        crash_dir=config.CRASH_DIR,
        trace=trace,
        level=config.LOG_LEVEL,
        debug=config.DEBUG,
        rotate_hours=config.LOG_ROTATE_HOURS,
        ring_size=config.RING_BUFFER_SIZE,
        preview_chars=config.LOG_PREVIEW_CHARS,
        queue_maxsize=config.LOG_QUEUE_MAXSIZE,
        version=CONFIG_HASH,
    )
    plugin.register_atexit()
    plugin.install_signal_handlers()
    game_session = GameSessionLog(
        state_path.parent / config.GAME_SESSION_PATH,
        trace=trace,
        fsync=config.LOG_FSYNC,
    )
    logger.info("Plugin fields: logs=%s crashes=%s gameplay=%s",
                config.LOG_DIR, config.CRASH_DIR, game_session.path)
    engine = load_dialogue_engine()
    try:
        state = await game_loop(
            state, history, args.max_steps, args.dry_run, state_path,
            game_session,
            epitaphs_dir=state_path.parent,
            dialogue_engine=engine,
            plugin=plugin,
            trace=trace,
        )
    except KeyboardInterrupt:
        logger.info("Ctrl+C received; saving state")
        if plugin is not None:
            plugin.event(LEVEL_INFO, "interrupted")
    except Exception as exc:
        logger.exception("Fatal error in game loop")
        if plugin is not None:
            plugin.state_change("running", "crashed")
            plugin.die("Fatal error in game loop", exc)
        _save_after_crash(state, state_path)
        await plugin.stop()
        return 1

    try:
        _sync_meta_from_hidden(state)
        state_io.save_state(state_path, state)
        logger.info("State saved to %s", state_path)
    except Exception as exc:
        logger.exception("Failed final save")
        if plugin is not None:
            plugin.event(LEVEL_ERROR, "state_invalid", {"message": str(exc)})
        await plugin.stop()
        return 1

    plugin.event(LEVEL_INFO, "state_saved", {"path": str(state_path)})
    plugin.state_change("running", "stopped")
    await plugin.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))