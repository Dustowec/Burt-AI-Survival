"""Хранилище эпитафий — отдельный JSON-файл.

Эпитафии живут в epitaphs.json рядом с state.json,
чтобы не теряться между жизнями и быть доступными для анализа.

Формат epitaphs.json:
    [
      {
        "life": 1,
        "epitaph": "Я прожил 5 дней...",
        "cause": "hunger",
        "days": 5
      }
    ]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EPITAPHS_FILENAME = "epitaphs.json"


def _epitaphs_path(state_dir: Path) -> Path:
    """Путь к файлу epitaphs.json внутри каталога state."""
    return state_dir / EPITAPHS_FILENAME


def load_epitaphs(state_dir: Path) -> list[dict[str, Any]]:
    """Читает epitaphs.json, возвращает список эпитафий.

    Если файл отсутствует или пуст — возвращает пустой список.
    Возвращает копию списка (мутации не влияют на файл).
    """
    path = _epitaphs_path(state_dir)
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return list(data)  # копия


def save_epitaphs(state_dir: Path, epitaphs: list[dict[str, Any]]) -> None:
    """Записывает список эпитафий в epitaphs.json."""
    path = _epitaphs_path(state_dir)
    path.write_text(
        json.dumps(epitaphs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_epitaph(
    state_dir: Path,
    life: int,
    epitaph: str,
    cause: str,
    days: int,
) -> None:
    """Append-ит новую эпитафию в epitaphs.json."""
    epitaphs = load_epitaphs(state_dir)
    epitaphs.append({
        "life": life,
        "epitaph": epitaph,
        "cause": cause,
        "days": days,
    })
    save_epitaphs(state_dir, epitaphs)


def get_all_epitaphs(state_dir: Path) -> list[dict[str, Any]]:
    """Все эпитафии (alias для load_epitaphs)."""
    return load_epitaphs(state_dir)


def get_last_epitaph(state_dir: Path) -> dict[str, Any] | None:
    """Последняя эпитафия (для memory transfer).

    Возвращает None, если эпитафий нет.
    """
    epitaphs = load_epitaphs(state_dir)
    if not epitaphs:
        return None
    return epitaphs[-1]
