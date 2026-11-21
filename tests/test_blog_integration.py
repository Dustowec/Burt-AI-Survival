"""Blog chronicle wired into run_turn / game_loop (burt/blog_log.py)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import main
from burt import loop, resurrection as res_mod, state as state_mod
from burt.blog_log import BlogLog
from burt.loop import Action, ActionResult
from burt.trace import Trace

_REAL = res_mod.ResurrectionOutcome


def _state() -> dict:
    st = state_mod.create_initial_state(
        life=1, session_uuid="blog-it", config_hash="v0.9.3",
        session_started="2026-11-22T00:00:00+00:00",
    )
    main._sync_hidden_from_meta(st)
    main._ensure_runtime_fields(st)
    st["visible"]["hp"] = 5
    st["hidden"]["step"] = 7
    return st


def _blog(tmp_path) -> BlogLog:
    return BlogLog(tmp_path / "blog.md", trace=Trace(session_uuid="blog-it"))


def _text(blog) -> str:
    return Path(blog.path).read_text(encoding="utf-8")


def _run(st, blog, *, result=None, answer="I move.\n\nCHOICE: 1"):
    async def fake_llm(system, user, history):
        return answer, history

    with patch.object(
        main.loop, "execute_action",
        return_value=result or ActionResult(events=[], game_over=False),
    ), patch.object(main.llm_client, "call_llm", new=fake_llm):
        return asyncio.run(
            main.run_turn(st, [], rng=lambda: 4, dry_run=False, blog=blog)
        )


class TestTurnIsWritten:
    def test_turn_block_written(self, tmp_path):
        st = _state()
        blog = _blog(tmp_path)
        _run(st, blog)
        text = _text(blog)
        assert "· day 1 · step 7 · Crossroads" in text
        assert "**Status:** HP: 5/10" in text
        assert "> I move." in text
        assert "**Choice:**" in text
        assert "**After:**" in text

    def test_event_line_from_inject(self, tmp_path):
        st = _state()
        blog = _blog(tmp_path)
        _run(st, blog, result=ActionResult(
            events=[], game_over=False,
            inject="You stumbled over a sharp stone.",
        ))
        assert "**Event:** You stumbled over a sharp stone." in _text(blog)

    def test_tool_turn_is_folded(self, tmp_path):
        st = _state()
        blog = _blog(tmp_path)
        _run(st, blog, result=ActionResult(events=["[INVENTORY]\nempty"]),
             answer="I check.\nCHOICE: 4")
        # execute_action is mocked, so the action comes from the parsed CHOICE
        assert "**Choice:**" in _text(blog) or "**Action:**" in _text(blog)


class TestCombatBlock:
    def test_ambush_creates_combat_block(self, tmp_path):
        st = _state()
        blog = _blog(tmp_path)

        def fake_execute(action, state, rng=None, dialogue_engine=None):
            state["hidden"]["current_mode"] = "combat"
            state["hidden"]["combat"] = {"initiative": "enemy", "enemies": []}
            return ActionResult(
                events=["[COMBAT]\nEnemy: young goblin\nYour turn."],
                inject="You fell into an ambush.",
            )

        async def fake_llm(system, user, history):
            return "I stand ready.\nCHOICE: 0", history

        with patch.object(main.loop, "execute_action",
                          side_effect=fake_execute), \
                patch.object(main.llm_client, "call_llm", new=fake_llm):
            asyncio.run(main.run_turn(st, [], rng=lambda: 4,
                                      dry_run=False, blog=blog))

        text = _text(blog)
        assert "### ⚔ Combat — ambush" in text
        assert "enemies: young goblin" in text
        assert "initiative: enemy" in text


class TestDeathEpitaphNewLife:
    def test_full_death_cycle(self, tmp_path):
        st = _state()
        blog = _blog(tmp_path)
        calls = {"n": 0}

        async def fake_run_turn(state, history, rng, dry_run, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return main.TurnResult(game_over=True, history=history,
                                       death_cause="hunger")
            return main.TurnResult(game_over=False, history=history)

        async def fake_epitaph(state, cause, epitaphs_dir=None, blog=None):
            state["meta"]["memory"] = "I carried bread and did not eat it."
            if blog is not None:
                blog.epitaph(life=1, days=1, cause=cause,
                             text="I carried bread and did not eat it.")

        new_life = state_mod.create_initial_state(
            life=2, session_uuid="blog-it", config_hash="v0.9.3",
            session_started="2026-11-22T00:00:00+00:00",
        )
        new_life["meta"]["memory"] = "I carried bread and did not eat it."

        res_mod.ResurrectionOutcome = type(
            "E", (), {"SUCCESS": "success", "FAILED": "failed"}
        )
        try:
            with patch("main.run_turn", side_effect=fake_run_turn), \
                    patch("main.resurrection.check_resurrection",
                          return_value="failed"), \
                    patch("main.state_io.save_state"), \
                    patch("main._write_epitaph", side_effect=fake_epitaph), \
                    patch("main.make_new_state", return_value=new_life):
                asyncio.run(main.game_loop(
                    st, [], max_steps=2, dry_run=False,
                    state_path=tmp_path / "state.json", blog=blog,
                ))
        finally:
            res_mod.ResurrectionOutcome = _REAL

        text = _text(blog)
        assert "## ☠ Death — life 1" in text
        assert "- cause: **hunger**" in text
        assert "### 🪦 Epitaph — life 1" in text
        assert "> I carried bread and did not eat it." in text
        assert "## 🔄 New life — 2" in text
        assert "- memory: **yes**" in text
