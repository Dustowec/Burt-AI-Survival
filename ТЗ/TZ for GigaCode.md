ТЕХНИЧЕСКОЕ ЗАДАНИЕ ДЛЯ ИИ-АГЕНТА (v2)
Контекст: Проект BURT-AI (текстовая RPG). TDD обязателен. Все тесты сейчас зелёные (1455+ passed). Код, docstrings, имена — только на английском.

Цель: Исправить баг «принудительный сон срабатывает во время боя», но при этом сохранить сон сразу после победы в бою на 20-м шаге.

Текущая проблема:
В main.py в run_turn проверка sleep_mod.is_forced_sleep(step_now, chose_sleep) не учитывает current_mode. Если Бурт входит в бой на 19-м шаге (step становится 20), сон срабатывает прямо посреди боя.

Требуемое поведение (ВАЖНО):

Если current_mode == "combat" — forced sleep не срабатывает (бой замораживает время).

Если бой закончился победой (burt_won) в этом же ходу — current_mode становится "exploring" внутри execute_action, и forced sleep срабатывает сразу в этом же ходу (потому что шаг уже 20, а бой закончился).

Если бой продолжается (current_mode == "combat") — сон не срабатывает, step остается 20.

Если бой закончился поражением (burt_died) — game_over=True, сон не нужен.

Файлы для изменения:

main.py (run_turn, блок «Forced sleep on step 20»).

tests/test_main.py (red-тесты).

План работ (TDD):

В tests/test_main.py создай класс TestForcedSleepBlockedInCombat.

Напиши тесты:

test_no_forced_sleep_during_ongoing_combat: state с current_mode="combat", step=20. run_turn (мок llm_client.call_llm возвращает боевое действие, например "attack_wolf_1"). Проверить: hp не восстановился до hp_max, step остался 20.

test_forced_sleep_after_combat_win: state с current_mode="combat", step=20, но execute_action возвращает burt_won (нужно замокать loop.execute_action или настроить hidden["combat"] так, чтобы волк умер от одного удара). Проверить: current_mode стал "exploring", hp восстановился, step стал 0, day увеличился.

test_forced_sleep_in_exploring_mode: state с current_mode="exploring", step=20. Проверить: _do_sleep сработал.

Убедись, что новые тесты падают.

Отредактируй main.py: перед _do_sleep(state) добавь проверку if hidden.get("current_mode") != "combat":.

Прогони pytest tests/ -q. Все тесты зелёные (1455 + новые).

Важные ограничения:

Не меняй combat.py, loop.py, sensory.py, sleep.py, hunger.py. Только main.py + tests/test_main.py.

Не трогай _do_sleep — она работает правильно.

Для теста test_forced_sleep_after_combat_win можешь использовать unittest.mock.patch для loop.execute_action, чтобы он вернул ActionResult(events=[], game_over=False) и явно установил hidden["current_mode"] = "exploring". Или настрой hidden["combat"] так, чтобы враг умирал с одного удара (hp=1).

Покажи git diff main.py и результат pytest -q.

Формат сдачи:

Все тесты зелёные (укажи точное число).

git diff main.py с изменениями.

Краткое описание: что было, что стало, где именно сработала проверка.