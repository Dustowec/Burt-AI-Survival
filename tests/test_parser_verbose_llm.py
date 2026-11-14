"""Тест: парсер + развёрнутый ответ LLM (гипотеза «текстового моста»).

Сценарий:
  - Большая модель пишет только "CHOICE: 0" → всегда индекс 0 (первое действие).
  - Слабая модель пишет развёрнутый текст + "CHOICE: 3" → обдумывает контекст.

Парсер должен:
  1. Корректно извлекать CHOICE: N даже когда перед ним есть текст.
  2. Выбирать действие по номеру, а не по первому в меню.
  3. Fallback (текст без CHOICE:) должен работать корректно.
"""

import pytest

from burt.loop import Action, parse_choice


class TestParserWithVerboseLLM:
    """Проверка: парсер корректно обрабатывает ответы LLM с текстовым мостом."""

    def _menu(self):
        """Меню как в exploring-режиме: osmotret всегда первый."""
        return [
            Action("osmotret", "Look around"),
            Action("go_north", "Go north"),
            Action("go_east", "Go east"),
            Action("go_south", "Go south"),
            Action("go_west", "Go west"),
            Action("search", "Search"),
            Action("eat_food", "Eat food"),
            Action("drink_water", "Drink water"),
        ]

    # ─── Сценарий 1: только CHOICE: N ──────────────────────────

    def test_just_choice_zero(self):
        """Большая модель: только 'CHOICE: 0' → первое действие."""
        menu = self._menu()
        result = parse_choice("CHOICE: 0", menu)
        assert result.key == "osmotret"

    def test_just_choice_three(self):
        """Большая модель: только 'CHOICE: 3' → четвёртое действие."""
        menu = self._menu()
        result = parse_choice("CHOICE: 3", menu)
        assert result.key == "go_south"

    def test_just_choice_seven(self):
        """Большая модель: только 'CHOICE: 7' → последнее действие."""
        menu = self._menu()
        result = parse_choice("CHOICE: 7", menu)
        assert result.key == "drink_water"

    # ─── Сценарий 2: текст + CHOICE: N (текстовый мост) ────────

    def test_verbose_then_choice(self):
        """Слабая модель: развёрнутый текст + CHOICE: 3."""
        menu = self._menu()
        text = (
            "I look around the crossroads. Shadows flicker in the alleys, "
            "and the scent of roasting meat drifts from the east. "
            "A road leads north, a path to the south is quiet. "
            "The wind blows warm.\n\nCHOICE: 3"
        )
        result = parse_choice(text, menu)
        # CHOICE: 3 → go_south, НЕ osmotret (индекс 0)
        assert result.key == "go_south", (
            f"Ожидал go_south, получил {result.key}. "
            "Парсер должен приоритизировать CHOICE: над первым действием."
        )

    def test_verbose_then_choice_one(self):
        """Текст + CHOICE: 1 → go_north."""
        menu = self._menu()
        text = "The crossroads look dangerous. I should head north.\n\nCHOICE: 1"
        result = parse_choice(text, menu)
        assert result.key == "go_north"

    def test_verbose_then_choice_five(self):
        """Текст + CHOICE: 5 → search."""
        menu = self._menu()
        text = "I need supplies. Let me search the area.\n\nCHOICE: 5"
        result = parse_choice(text, menu)
        assert result.key == "search"

    # ─── Сценарий 3: CHOICE: N на первой строке после текста ───

    def test_choice_on_second_line(self):
        """CHOICE: на второй строке (после пустой строки)."""
        menu = self._menu()
        text = "I look around.\n\nCHOICE: 2"
        result = parse_choice(text, menu)
        assert result.key == "go_east"

    def test_choice_on_first_line(self):
        """CHOICE: на первой строке (без текста перед ним)."""
        menu = self._menu()
        result = parse_choice("CHOICE: 4", menu)
        assert result.key == "go_west"

    # ─── Сценарий 4: CHOICE: с пробелами и регистром ───────────

    def test_choice_with_spaces(self):
        """CHOICE:  3 (два пробела)."""
        menu = self._menu()
        result = parse_choice("CHOICE:  3", menu)
        assert result.key == "go_south"

    def test_choice_lowercase(self):
        """choice: 2 (нижний регистр)."""
        menu = self._menu()
        result = parse_choice("choice: 2", menu)
        assert result.key == "go_east"

    def test_choice_mixed_case(self):
        """ChOiCe: 1 (смешанный регистр)."""
        menu = self._menu()
        result = parse_choice("ChOiCe: 1", menu)
        assert result.key == "go_north"

    # ─── Сценарий 5: fallback без CHOICE: ──────────────────────

    def test_no_choice_fallback_text(self):
        """Без CHOICE: fallback ищет ключ/лейбл в тексте."""
        menu = self._menu()
        text = "I should eat some bread."
        result = parse_choice(text, menu)
        assert result.key == "eat_food"

    def test_no_choice_fallback_unknown(self):
        """Без CHOICE: и без ключей → первое действие."""
        menu = self._menu()
        text = "I am just standing here."
        result = parse_choice(text, menu)
        assert result.key == "osmotret"

    # ─── Сценарий 6: невалидный индекс CHOICE: ─────────────────

    def test_invalid_choice_index_too_large(self):
        """CHOICE: 99 → невалидный индекс, fallback."""
        menu = self._menu()
        result = parse_choice("CHOICE: 99", menu)
        # Fallback: ищет ключ/лейбл в тексте "99" → не найдёт → первое действие
        assert result.key == "osmotret"

    def test_invalid_choice_negative(self):
        """CHOICE: -1 → невалидный индекс, fallback."""
        menu = self._menu()
        result = parse_choice("CHOICE: -1", menu)
        assert result.key == "osmotret"

    # ─── Сценарий 7: CHOICE: с текстом после ───────────────────

    def test_choice_with_trailing_text(self):
        """CHOICE: 3 (дальше текст)."""
        menu = self._menu()
        result = parse_choice("CHOICE: 3\nI hope it works", menu)
        assert result.key == "go_south"

    # ─── Сценарий 8: combat меню ───────────────────────────────

    def test_combat_verbose_choice(self):
        """В бою: текст + CHOICE: 1 → block."""
        menu = [
            Action("attack_wolf_1", "Attack wolf"),
            Action("block", "Block"),
            Action("flee", "Flee"),
        ]
        text = "The wolf is fast. I need to defend myself.\n\nCHOICE: 1"
        result = parse_choice(text, menu)
        assert result.key == "block"

    def test_combat_just_choice(self):
        """В бою: только CHOICE: 2 → flee."""
        menu = [
            Action("attack_wolf_1", "Attack wolf"),
            Action("block", "Block"),
            Action("flee", "Flee"),
        ]
        result = parse_choice("CHOICE: 2", menu)
        assert result.key == "flee"


class TestParserBehavioralDifference:
    """Сравнение: что выберет парсер для разных моделей.

    Ключевой вопрос:
      - Большая модель: "CHOICE: 0" → всегда osmotret (индекс 0).
      - Слабая модель: текст + "CHOICE: 3" → go_south (индекс 3).

    Это подтверждает гипотезу: развёрнутый ответ = более разнообразный выбор.
    """

    def test_big_model_always_first_action(self):
        """Большая модель пишет только CHOICE: 0 → всегда первое действие."""
        menu = [
            Action("osmotret", "Look around"),
            Action("go_north", "Go north"),
            Action("go_east", "Go east"),
            Action("go_south", "Go south"),
        ]
        # 10 вызовов "CHOICE: 0" → всегда одно и то же
        results = {parse_choice("CHOICE: 0", menu).key for _ in range(10)}
        assert results == {"osmotret"}, (
            "Большая модель всегда выбирает первое действие (osmotret)."
        )

    def test_small_model_varies_choice(self):
        """Слабая модель: разные CHOICE: → разные действия."""
        menu = [
            Action("osmotret", "Look around"),
            Action("go_north", "Go north"),
            Action("go_east", "Go east"),
            Action("go_south", "Go south"),
        ]
        results = set()
        for i in range(4):
            text = f"I look around. The world is vast.\n\nCHOICE: {i}"
            results.add(parse_choice(text, menu).key)
        assert results == {"osmotret", "go_north", "go_east", "go_south"}, (
            "Слабая модель выбирает разные действия в зависимости от CHOICE:."
        )

    def test_verbose_text_changes_selection(self):
        """Один и тот же CHOICE: 0 с разным текстом → один результат."""
        menu = [
            Action("osmotret", "Look around"),
            Action("go_north", "Go north"),
        ]
        # CHOICE: 0 всегда → osmotret, независимо от текста
        r1 = parse_choice("I look around.\n\nCHOICE: 0", menu)
        r2 = parse_choice("CHOICE: 0", menu)
        assert r1.key == r2.key == "osmotret"

    def test_different_choice_numbers_with_same_text(self):
        """Разные CHOICE: с одинаковым текстом → разные действия."""
        menu = [
            Action("osmotret", "Look around"),
            Action("go_north", "Go north"),
            Action("go_south", "Go south"),
        ]
        base_text = "The crossroads are quiet.\n\n"
        r1 = parse_choice(base_text + "CHOICE: 1", menu)
        r2 = parse_choice(base_text + "CHOICE: 2", menu)
        assert r1.key == "go_north"
        assert r2.key == "go_south"
