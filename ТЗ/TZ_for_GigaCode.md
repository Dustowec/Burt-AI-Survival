ТЕХНИЧЕСКОЕ ЗАДАНИЕ ДЛЯ ИИ-АГЕНТА (Пункт 4)
Контекст: Проект BURT-AI (текстовая RPG). TDD обязателен. Все тесты сейчас зелёные (1467+ passed). Код, docstrings, имена — только на английском.

Цель: Убрать бесполезный счётчик сна из сенсорного отчёта и починить появление пункта «Sleep» в меню.

Текущие проблемы (Баг):

В burt/sensory.py в секции [STATE] выводится Sleep: 0/20. Но visible["sleep_counter"] никогда не инкрементируется и всегда равен 0. Это дезинформирует модель (она думает, что день только начался, даже если шаг 15).

В burt/loop.py в функции build_menu условие появления пункта sleep завязано на visible.get("sleep_counter", 0) >= 19. Так как счётчик всегда 0, этот пункт меню никогда не появляется (кроме случая, когда HP < 25%).

Требуемое поведение:

Убрать счётчик сна из сенсорики. В [STATE] должна остаться только строка Hunger: full/hungry. Никаких Sleep: ....

Удалить флаг SHOW_SLEEP_TIMER из config.py (он больше не нужен).

Починить меню. В build_menu использовать hidden.get("step", 0) вместо visible.get("sleep_counter", 0). Пункт sleep должен появляться, когда step >= 19 или hp < 25% от hp_max.

Синхронизация не нужна. Поле visible["sleep_counter"] можно оставить в структуре state (чтобы не ломать сохранения), но в логике оно больше не участвует.

Файлы для изменения:

burt/sensory.py

burt/loop.py

config.py

Тесты: tests/test_sensory.py, tests/test_loop.py, tests/test_config.py.

План работ (TDD):

Напиши/обнови red-тесты:

tests/test_sensory.py: в тестах [STATE] проверь, что строки "Sleep:" нет в отчёте.

tests/test_loop.py (класс TestBuildMenuExploring):

Удали/переименуй старый тест test_sleep_present_at_sc_19.

Добавь test_sleep_present_at_step_19: установи st["hidden"]["step"] = 19, проверь, что sleep есть в меню.

Добавь test_sleep_present_at_critical_hp (оставь как есть, но убедись, что он работает).

tests/test_config.py: удали тест test_show_sleep_timer_is_true, если он есть.

Убедись, что новые тесты падают (red state).

Отредактируй burt/sensory.py: убери вывод Sleep: из _format_hunger_sleep.

Отредактируй burt/loop.py: в build_menu замени sc = visible.get("sleep_counter", 0) на step = hidden.get("step", 0).

Удали SHOW_SLEEP_TIMER из config.py.

Прогони .\.venv\Scripts\pytest.exe tests/ -q. Все тесты зелёные (1467 + новые).

Важные ограничения:

Не меняй main.py, burt/combat.py, burt/hunger.py, burt/sleep.py.

Не удаляй sleep_counter из state.py (это сломает валидацию старых сейвов, оставь как legacy-поле).

Покажи git diff по всем изменённым файлам и результат pytest -q.