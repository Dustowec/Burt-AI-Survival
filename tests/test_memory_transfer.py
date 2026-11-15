"""Tests for memory transfer from epitaphs.

План рефакторинга: ТЗ/refactoring_of_epytaph.md.

Память новой жизни берётся из последней эпитафии.
При жизни >= 10 вызывается MEMORY_SUMMARY_PROMPT.
memory_summary инжектится в BURT_SYSTEM_PROMPT.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import main
from burt import epitaphs as epitaphs_mod


# ─── Helpers ───────────────────────────────────────────────────


def _make_epitaphs_file(tmp_path: Path, data: list[dict]) -> Path:
    """Создаёт epitaphs.json в temp-каталоге."""
    p = tmp_path / "epitaphs.json"
    p.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return p


# ─── Memory from epitaphs ─────────────────────────────────────


class TestMemoryFromEpitaphs:
    """Память новой жизни берётся из последней эпитафии."""

    def test_memory_from_last_epitaph(self, tmp_path: Path):
        """Память берётся из epitaphs.json."""
        _make_epitaphs_file(tmp_path, [
            {"life": 1, "epitaph": "I learned patience.", "cause": "hunger", "days": 5},
            {"life": 2, "epitaph": "I learned courage.", "cause": "combat", "days": 12},
        ])
        state = main.make_new_state(life=3, epitaphs_dir=tmp_path)
        assert state["meta"]["memory"] == "I learned courage."

    def test_no_memory_if_no_epitaphs(self, tmp_path: Path):
        """Нет эпитафий → нет памяти."""
        state = main.make_new_state(life=2, epitaphs_dir=tmp_path)
        assert state["meta"].get("memory") is None

    def test_no_memory_if_file_missing(self, tmp_path: Path):
        """Файл отсутствует → нет памяти."""
        state = main.make_new_state(life=2, epitaphs_dir=tmp_path)
        assert state["meta"].get("memory") is None

    def test_explicit_memory_overrides_epitaphs(self, tmp_path: Path):
        """Явная memory имеет приоритет над epitaphs."""
        _make_epitaphs_file(tmp_path, [
            {"life": 1, "epitaph": "from epitaphs", "cause": "x", "days": 1},
        ])
        state = main.make_new_state(
            life=2,
            memory="explicit memory",
            epitaphs_dir=tmp_path,
        )
        assert state["meta"]["memory"] == "explicit memory"

    def test_single_epitaph_transfers_memory(self, tmp_path: Path):
        """Одна эпитафия → память переносится."""
        _make_epitaphs_file(tmp_path, [
            {"life": 1, "epitaph": "First life lesson.", "cause": "hunger", "days": 3},
        ])
        state = main.make_new_state(life=2, epitaphs_dir=tmp_path)
        assert state["meta"]["memory"] == "First life lesson."


# ─── _write_memory_summary ────────────────────────────────────


class TestWriteMemorySummary:
    """_write_memory_summary при жизни >= 10."""

    def test_skipped_below_life_10(self, tmp_path: Path):
        """life < 10 → пропуск."""
        state = main.make_new_state(life=9)
        state["meta"]["life"] = 9
        asyncio = __import__("asyncio")
        asyncio.run(main._write_memory_summary(state, tmp_path))
        assert "memory_summary" not in state["meta"]

    def test_skipped_if_less_than_10_epitaphs(self, tmp_path: Path):
        """Меньше 10 эпитафий → пропуск."""
        _make_epitaphs_file(tmp_path, [
            {"life": i, "epitaph": f"Life {i}", "cause": "x", "days": i}
            for i in range(1, 9)  # 8 эпитафий
        ])
        state = main.make_new_state(life=10, epitaphs_dir=tmp_path)
        state["meta"]["life"] = 10
        asyncio = __import__("asyncio")
        asyncio.run(main._write_memory_summary(state, tmp_path))
        assert "memory_summary" not in state["meta"]

    def test_calls_llm_with_10_epitaphs(self, tmp_path: Path):
        """10 эпитафий → вызов LLM."""
        _make_epitaphs_file(tmp_path, [
            {"life": i, "epitaph": f"Lesson {i}", "cause": "x", "days": i}
            for i in range(1, 11)  # 10 эпитафий
        ])
        state = main.make_new_state(life=10, epitaphs_dir=tmp_path)
        state["meta"]["life"] = 10

        mock = AsyncMock(return_value=("Wisdom across lives.", []))
        with patch("main.llm_client.call_llm", new=mock):
            asyncio = __import__("asyncio")
            asyncio.run(main._write_memory_summary(state, tmp_path))

        assert mock.called
        user_msg = mock.call_args[0][1]
        assert "Life 1" in user_msg
        assert "Life 10" in user_msg
        assert state["meta"]["memory_summary"] == "Wisdom across lives."


# ─── _build_system_prompt ─────────────────────────────────────


class TestBuildSystemPrompt:
    """Инжект memory_summary в BURT_SYSTEM_PROMPT."""

    def test_no_summary_without_memory_summary(self):
        """Без memory_summary → базовый промпт."""
        state = {"meta": {"life": 1}}
        prompt = main._build_system_prompt(state)
        assert "Across all your lives" not in prompt

    def test_includes_summary_when_present(self):
        """С memory_summary → добавляется в промпт."""
        state = {
            "meta": {
                "life": 15,
                "memory_summary": "I have learned to be patient.",
            }
        }
        prompt = main._build_system_prompt(state)
        assert "Across all your lives you understood:" in prompt
        assert "I have learned to be patient." in prompt

    def test_summary_appended_after_base_prompt(self):
        """memory_summary добавляется ПОСЛЕ базового промпта."""
        state = {
            "meta": {
                "life": 12,
                "memory_summary": "Patience is key.",
            }
        }
        prompt = main._build_system_prompt(state)
        # Базовый промпт должен быть в начале
        assert "You are Burt." in prompt
        # Summary — после
        assert prompt.index("You are Burt.") < prompt.index("Across all your lives")
