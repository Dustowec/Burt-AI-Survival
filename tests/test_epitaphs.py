"""Tests for burt/epitaphs.py — epitaphs JSON store.

План рефакторинга: ТЗ/refactoring_of_epytaph.md.

Эпитафии хранятся в отдельном JSON-файле рядом с state.json,
чтобы не теряться между жизнями.
"""

import json
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from burt.epitaphs import (
    EPITAPHS_FILENAME,
    load_epitaphs,
    save_epitaphs,
    add_epitaph,
    get_all_epitaphs,
    get_last_epitaph,
)


# ─── Helpers ───────────────────────────────────────────────────


def _tmp_epitaphs_dir(tmp_path: Path) -> Path:
    """Create a temp directory and return it."""
    return tmp_path


# ─── load_epitaphs ───────────────────────────────────────────


class TestLoadEpitaphs:
    """Чтение epitaphs.json."""

    def test_empty_file(self, tmp_path: Path):
        """Пустой файл → пустой список."""
        epitaphs_file = tmp_path / EPITAPHS_FILENAME
        epitaphs_file.write_text("[]", encoding="utf-8")
        result = load_epitaphs(tmp_path)
        assert result == []

    def test_missing_file(self, tmp_path: Path):
        """Файл отсутствует → пустой список."""
        result = load_epitaphs(tmp_path)
        assert result == []

    def test_valid_json(self, tmp_path: Path):
        """Валидный JSON → список словарей."""
        epitaphs_file = tmp_path / EPITAPHS_FILENAME
        data = [
            {
                "life": 1,
                "epitaph": "Я прожил 5 дней.",
                "cause": "hunger",
                "days": 5,
            },
            {
                "life": 2,
                "epitaph": "Я прожил 12 дней.",
                "cause": "combat",
                "days": 12,
            },
        ]
        epitaphs_file.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        result = load_epitaphs(tmp_path)
        assert len(result) == 2
        assert result[0]["life"] == 1
        assert result[0]["epitaph"] == "Я прожил 5 дней."
        assert result[0]["cause"] == "hunger"
        assert result[0]["days"] == 5
        assert result[1]["cause"] == "combat"

    def test_returns_copy_not_reference(self, tmp_path: Path):
        """Возвращённый список — копия, мутации не влияют на файл."""
        epitaphs_file = tmp_path / EPITAPHS_FILENAME
        epitaphs_file.write_text("[]", encoding="utf-8")
        result1 = load_epitaphs(tmp_path)
        result1.append({"life": 99})
        result2 = load_epitaphs(tmp_path)
        assert result2 == []


# ─── save_epitaphs ───────────────────────────────────────────


class TestSaveEpitaphs:
    """Запись epitaphs.json."""

    def test_save_creates_file(self, tmp_path: Path):
        """save_epitaphs создаёт файл."""
        epitaphs = [
            {"life": 1, "epitaph": "first", "cause": "hunger", "days": 3}
        ]
        save_epitaphs(tmp_path, epitaphs)
        epitaphs_file = tmp_path / EPITAPHS_FILENAME
        assert epitaphs_file.exists()

    def test_save_writes_valid_json(self, tmp_path: Path):
        """save_epitaphs записывает валидный JSON."""
        epitaphs = [
            {"life": 1, "epitaph": "first", "cause": "hunger", "days": 3}
        ]
        save_epitaphs(tmp_path, epitaphs)
        epitaphs_file = tmp_path / EPITAPHS_FILENAME
        data = json.loads(epitaphs_file.read_text(encoding="utf-8"))
        assert data == epitaphs

    def test_save_overwrites_existing(self, tmp_path: Path):
        """save_epitaphs перезаписывает существующий файл."""
        save_epitaphs(tmp_path, [{"life": 1, "epitaph": "old", "cause": "x", "days": 1}])
        save_epitaphs(tmp_path, [{"life": 2, "epitaph": "new", "cause": "y", "days": 2}])
        result = load_epitaphs(tmp_path)
        assert len(result) == 1
        assert result[0]["life"] == 2
        assert result[0]["epitaph"] == "new"


# ─── add_epitaph ─────────────────────────────────────────────


class TestAddEpitaph:
    """Добавление эпитафии (append)."""

    def test_add_first_epitaph(self, tmp_path: Path):
        """Добавление первой эпитафии."""
        add_epitaph(tmp_path, life=1, epitaph="I lived 3 days.", cause="hunger", days=3)
        result = get_all_epitaphs(tmp_path)
        assert len(result) == 1
        assert result[0]["life"] == 1
        assert result[0]["epitaph"] == "I lived 3 days."
        assert result[0]["cause"] == "hunger"
        assert result[0]["days"] == 3

    def test_add_second_epitaph_appends(self, tmp_path: Path):
        """Добавление второй эпитафии — append."""
        add_epitaph(tmp_path, life=1, epitaph="first life", cause="hunger", days=3)
        add_epitaph(tmp_path, life=2, epitaph="second life", cause="combat", days=7)
        result = get_all_epitaphs(tmp_path)
        assert len(result) == 2
        assert result[0]["life"] == 1
        assert result[1]["life"] == 2

    def test_add_preserves_existing(self, tmp_path: Path):
        """add_epitaph не удаляет существующие."""
        add_epitaph(tmp_path, life=1, epitaph="first", cause="x", days=1)
        add_epitaph(tmp_path, life=2, epitaph="second", cause="y", days=2)
        add_epitaph(tmp_path, life=3, epitaph="third", cause="z", days=3)
        result = get_all_epitaphs(tmp_path)
        assert len(result) == 3
        assert result[0]["cause"] == "x"
        assert result[1]["cause"] == "y"
        assert result[2]["cause"] == "z"


# ─── get_all_epitaphs ────────────────────────────────────────


class TestGetAllEpitaphs:
    """Получение всех эпитафий."""

    def test_empty(self, tmp_path: Path):
        assert get_all_epitaphs(tmp_path) == []

    def test_returns_all(self, tmp_path: Path):
        add_epitaph(tmp_path, 1, "a", "x", 1)
        add_epitaph(tmp_path, 2, "b", "y", 2)
        add_epitaph(tmp_path, 3, "c", "z", 3)
        result = get_all_epitaphs(tmp_path)
        assert len(result) == 3


# ─── get_last_epitaph ────────────────────────────────────────


class TestGetLastEpitaph:
    """Получение последней эпитафии."""

    def test_none_when_empty(self, tmp_path: Path):
        assert get_last_epitaph(tmp_path) is None

    def test_returns_last(self, tmp_path: Path):
        add_epitaph(tmp_path, 1, "first", "hunger", 3)
        add_epitaph(tmp_path, 2, "second", "combat", 7)
        result = get_last_epitaph(tmp_path)
        assert result is not None
        assert result["life"] == 2
        assert result["epitaph"] == "second"
        assert result["cause"] == "combat"
        assert result["days"] == 7

    def test_returns_none_if_only_one(self, tmp_path: Path):
        add_epitaph(tmp_path, 1, "only one", "hunger", 5)
        result = get_last_epitaph(tmp_path)
        assert result is not None
        assert result["life"] == 1
