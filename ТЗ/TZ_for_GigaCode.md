ТЕХНИЧЕСКОЕ ЗАДАНИЕ ДЛЯ ИИ-АГЕНТА (Пункт 2)
Контекст: Проект BURT-AI (текстовая RPG). TDD обязателен. Все тесты сейчас зелёные (1458+ passed). Код, docstrings, имена — только на английском.

Цель: Исправить баги, связанные с сохранением и загрузкой состояния (Save/Load).

Симптомы (из живого прогона Gemma 3n-E4B, 45 ходов):

После save + load Бурт оказывается в другой локации (например, был в node_5, стал в start). Этого быть не должно.

После загрузки бой продолжается (это правильно), но:

Срабатывает повторный триггер засады (ambush) — быть не должно, бой уже идёт.

Волк наносит лишний удар (free strike) — быть не должно, free_strike_done уже True.

Гипотезы для исследования (проверить в первую очередь):

state_io.load_state: теряет ли он hidden["current_node_id"], hidden["location_graph"], hidden["current_mode"], hidden["combat"]?

main.py (загрузка состояния): не вызывает ли он _maybe_start_combat_on_enter или другие функции, которые перезаписывают current_mode/combat?

combat.CombatState.to_dict / from_dict: сохраняется ли флаг free_strike_done? (Судя по коду, сохраняется, но нужно проверить на практике.)

main._ensure_runtime_fields: использует setdefault, не перетирает ли он уже существующие значения?

Файлы для изменения:

burt/state_io.py (или main.py, если баг там).

burt/combat.py (если проблема в сериализации).

tests/test_state_io.py, tests/test_main.py (red-тесты).

План работ (TDD):

В tests/test_state_io.py (или tests/test_main.py, если state_io не хватает) создай класс TestSaveLoadIntegrity.

Напиши тесты:

test_current_node_id_preserved: state с hidden["current_node_id"] = "node_5". Save → Load. Проверить: loaded_state["hidden"]["current_node_id"] == "node_5".

test_location_graph_preserved: state с кастомным графом. Save → Load. Граф идентичен.

test_current_mode_combat_preserved: state с hidden["current_mode"] = "combat". Save → Load. Проверить: current_mode == "combat".

test_combat_state_preserved: state с hidden["combat"] = CombatState(...).to_dict(), где free_strike_done=True. Save → Load. Проверить: free_strike_done всё ещё True.

test_no_ambush_on_load: после загрузки состояния с current_mode="combat" и активным combat, вызов run_turn не должен триггерить засаду (проверить, что hidden["combat"]["free_strike_done"] не сбросился и волк не бьёт «бесплатно»).

Убедись, что тесты падают (red state).

Найди и исправь причину (вероятно, в state_io.py или main.py).

Прогони pytest tests/ -q. Все тесты зелёные (1458 + новые).

Важные ограничения:

Не меняй burt/loop.py, burt/sensory.py, burt/hunger.py, burt/sleep.py. Задача локальная для state_io.py, main.py (загрузка) и combat.py (если нужно).

Если баг в combat.py (сериализация), правь только to_dict/from_dict для CombatState, не трогая боевую логику.

Покажи git diff по изменённым файлам и результат pytest -q.

Формат сдачи:

Все тесты зелёные (укажи число).

git diff с изменениями.

Краткое описание: в чём была причина, что исправил.