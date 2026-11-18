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
    hunger,
    loop,
    llm_client,
    prompts,
    quests,
    resurrection,
    sensory,
    sleep as sleep_mod,
    state as state_mod,
    state_io,
    search as search_mod,
)
from burt.game_logger import GameLogger


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
        visible["date"] = f"{hidden['day']} day"


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


# ---------------------------------------------------------------------
# Logging helpers (П.2, П.3, П.4)
# ---------------------------------------------------------------------

def _determine_death_cause(state: dict, action: loop.Action) -> str:
    """П.2: pure helper to determine what killed Burt."""
    visible = state["visible"]
    hidden = state["hidden"]
    hp = visible.get("hp", 0)

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


def _build_system_prompt(state: dict) -> str:
    """Build BURT_SYSTEM_PROMPT with optional memory_summary injection."""
    base = prompts.BURT_SYSTEM_PROMPT
    meta = state.get("meta", {})
    summary = meta.get("memory_summary")
    if summary:
        base += f"\n\nAcross all your lives you understood:\n{summary}"
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
# Turn loop
# ---------------------------------------------------------------------

async def run_turn(
    state: dict,
    history: list[dict],
    rng,
    dry_run: bool,
    game_logger: GameLogger | None = None,
    epitaphs_dir: Path | None = None,
) -> TurnResult:
    visible = state["visible"]
    hidden = state["hidden"]
    day_before = hidden.get("day", 1)
    day = hidden.get("day", 1)
    step = hidden.get("step", 0)

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
            await _write_epitaph(state, "diarrhea", epitaphs_dir)
            if game_logger:
                game_logger.log_special_event(
                    day=day,
                    event_type="death",
                    description="Burt died from diarrhea (DoT)",
                    state=state,
                )
            return TurnResult(game_over=True, history=history)

    # -- 1. Sensory report ----------------------------------------
    report = sensory.format_sensory_report(visible)
    if hp_lost > 0:
        report = f"You take {hp_lost} damage from poison.\n\n" + report

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
    menu = loop.build_menu(visible, state)

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

    # -- 5. LLM call ----------------------------------------------
    menu_text = "\n".join(f"{i}. {a.label}" for i, a in enumerate(menu))
    llm_prompt = f"{report}\n\nMENU:\n{menu_text}\n\nCHOICE:"
    
    _log_inject(step, hidden.get("day", 1), hidden.get("current_mode", "exploring"), menu, llm_prompt)
    
    answer, history = await llm_client.call_llm(
        _build_system_prompt(state), llm_prompt, history,
    )
    
    # P.5: No truncation
    logger.info("LLM: %s", answer)

    # -- 6. Parse and execute -------------------------------------
    action = loop.parse_choice(answer, menu)
    logger.info("Action: %s (%s)", action.key, action.label)

    hidden.setdefault("day_log", []).append({
        "step": hidden.get("step", 0),
        "location": visible.get("location", {}).get("name", "?"),
        "llm_message": answer,
        "action": action.key,
    })

    if action.key == "write_diary_and_go_sleep":
        await _write_diary(state, hidden["day_log"])

    result = loop.execute_action(action, state, rng=rng)

    _log_result_events(result)

    # -- 7. Save history (trim if too long) -----------------------
    if len(history) > 40:
        history = history[-20:]

    # -- 8. Game over? --------------------------------------------
    if result.game_over:
        _log_death(state, action)
        await _write_epitaph(
            state, _determine_death_cause(state, action), epitaphs_dir,
        )
        if game_logger:
            game_logger.log_turn(
                day=day,
                start_state=state,
                sensory_report=report,
                llm_prompt=llm_prompt,
                llm_response=answer,
                action_key=action.key,
                action_label=action.label,
                result_events=result.events,
                result_game_over=True,
                result_new_hp=visible.get("hp"),
                end_state=state,
            )
        return TurnResult(game_over=True, history=history,
                         start_state=state, sensory_report=report,
                         llm_prompt=llm_prompt, llm_response=answer,
                         action_key=action.key, action_label=action.label,
                         result_events=result.events, result_game_over=True,
                         result_new_hp=visible.get("hp"), end_state=state)

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
        await _write_epitaph(state, "hunger", epitaphs_dir)
        if game_logger:
            game_logger.log_special_event(
                day=day,
                event_type="death",
                description="Burt died from hunger",
                state=state,
            )
        return TurnResult(game_over=True, history=history,
                         start_state=state, sensory_report=report,
                         llm_prompt=llm_prompt, llm_response=answer,
                         action_key=action.key, action_label=action.label,
                         result_events=result.events, result_game_over=True,
                         result_new_hp=visible.get("hp"), end_state=state)

    # -- 10. Forced sleep on step 20 ------------------------------
    step_now = hidden.get("step", 0)
    chose_sleep = action.key in ("sleep", "write_diary_and_go_sleep")
    if sleep_mod.is_forced_sleep(step_now, chose_sleep):
        if hidden.get("current_mode") != "combat":
            logger.info("Forced sleep (step 20)")
            _do_sleep(state)
        else:
            logger.info("Forced sleep blocked (in combat, step %d)", step_now)

    # -- 11. Daily expiry -----------------------------------------
    quests.expire_blockades(state)
    quests.expire_deceit_penalties(state)

    # -- 12. Context reset on new day -----------------------------
    day_after = hidden.get("day", 1)
    if day_after > day_before:
        history = []

    # -- 13. Sync meta and save -----------------------------------
    _sync_meta_from_hidden(state)

    # -- Log the turn ---------------------------------------------
    if game_logger:
        game_logger.log_turn(
            day=day,
            start_state=state,
            sensory_report=report,
            llm_prompt=llm_prompt,
            llm_response=answer,
            action_key=action.key,
            action_label=action.label,
            result_events=result.events,
            result_game_over=False,
            result_new_hp=visible.get("hp"),
            result_search_result=getattr(result, "search_result", None),
            result_direction_moved=getattr(result, "direction_moved", None),
            end_state=state,
        )

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
    visible = state["visible"]
    hidden = state["hidden"]
    hp_max = visible.get("hp_max", 10)
    mp_max = visible.get("mp_max", 3)
    new_hp, new_mp, new_effects = sleep_mod.apply_sleep(hp_max, mp_max)
    visible["hp"] = new_hp
    visible["mp"] = new_mp
    visible["effects"] = new_effects
    hidden["hp_raw"] = new_hp
    hidden["mp_raw"] = new_mp

    eat, res_used = hunger.reset_hunger_after_sleep()
    visible["eat"] = eat
    visible["sleep_counter"] = 0
    hidden["resurrection_used_today"] = res_used
    hidden["day"] = hidden.get("day", 1) + 1
    hidden["step"] = 0
    visible["date"] = f"{hidden['day']} day"
    hidden["day_log"] = []
    if not hidden.get("diary_written_today", False):
        hidden["diary"] = None
        hidden["diary_skipped_today"] = True
    hidden["diary_written_today"] = False
    hidden["pending_encounter"] = None
    hidden["encounter_revealed"] = False
    logger.info("Slept. day=%d step=0", hidden["day"])


# ---------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------

async def game_loop(
    state: dict,
    history: list[dict],
    max_steps: int,
    dry_run: bool,
    state_path: Path,
    game_logger: GameLogger | None = None,
    epitaphs_dir: Path | None = None,
) -> None:
    rng = dice.roll_d6
    step_count = 0
    epitaphs_dir = epitaphs_dir or state_path.parent

    while step_count < max_steps:
        try:
            turn_result = await run_turn(
                state, history, rng, dry_run, game_logger,
                epitaphs_dir,
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

        try:
            state_io.save_state(state_path, state)
        except Exception:
            logger.exception("Failed to save state")

        if game_over:
            # Воскрешение: 1d6 -> решение
            outcome = resurrection.check_resurrection(rng)

            if outcome == resurrection.ResurrectionOutcome.SUCCESS:
                # Бурт воскресает в том же мире
                visible = state.setdefault("visible", {})
                hidden = state.setdefault("hidden", {})
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
                if game_logger:
                    game_logger.log_special_event(
                        day=hidden.get("day", 1),
                        event_type="resurrection",
                        description="Burt resurrected by dice roll",
                        state=state,
                    )
                # game_over=False → продолжаем цикл
                continue

            # Если FAILED — пишем эпитафию и создаём новую жизнь
            old_memory = state["meta"].get("memory")
            old_life = state["meta"]["life"]
            new_life = old_life + 1

            # Пишем память в новую жизнь из epitaphs
            state = make_new_state(
                life=new_life,
                epitaphs_dir=epitaphs_dir,
            )
            _sync_hidden_from_meta(state)
            _ensure_runtime_fields(state)
            history = []  # <-- wipe LLM context between lives (bug fix)

            # Проверяем memory_summary при жизни >= 10
            if state["meta"].get("life", 1) >= 10 and epitaphs_dir is not None:
                await _write_memory_summary(state, epitaphs_dir)

            logger.info(
                "Game over (life %d) → new life %d started (memory=%s)",
                old_life, new_life, "yes" if old_memory else "no",
            )
            continue

    logger.info("Loop finished after %d turns", step_count)
# CLI
# ---------------------------------------------------------------------

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
    game_logger = GameLogger(Path("LOGS"))
    logger.info("GameLogger initialized at LOGS/")
    try:
        await game_loop(
            state, history, args.max_steps, args.dry_run, state_path,
            game_logger,
            epitaphs_dir=state_path.parent,
        )
    except KeyboardInterrupt:
        logger.info("Ctrl+C received; saving state")
    except Exception:
        logger.exception("Fatal error in game loop")
        return 1

    try:
        _sync_meta_from_hidden(state)
        state_io.save_state(state_path, state)
        logger.info("State saved to %s", state_path)
    except Exception:
        logger.exception("Failed final save")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))