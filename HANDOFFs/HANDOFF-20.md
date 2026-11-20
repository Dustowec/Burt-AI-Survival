=====================================================================
BURT -- HANDOFF 20
Date: 20.11.2026
Project: BURT-AI (E:\Butr-Ai)
Spec: v0.7.0
Status: IN DEVELOPMENT, TDD
Previous: HANDOFF-19 (social layer, NPC spawn, role quests, reputation)
Uncommitted at handoff write: YES (economy + magic, see below)
=====================================================================

---------------------------------------------------------------------
SESSION SUMMARY
---------------------------------------------------------------------

Point B of the roadmap: economy + magic.
Spec sections: §35 (trade matrix), §19 (coin), §16 (reputation
prices), §5 (sleep gate), §9 (magic), §32 (teachers), §8 (skills),
§22 (loot).

1. burt/economy.py (NEW, pure core)
   - inventory stacks: item_count / has_item / add_item / remove_item
   - sellable_items: только то, у чего есть цена (BASE_PRICES или
     LOOT_PRICES); berries/mushrooms не продаются
   - compose(): floor(base * m1 * m2 ...) через fractions.Fraction(str(m)),
     чтобы 1.25 * 0.9 было ровно 1.125, а floor не зависел от float
   - buy_price / sell_price с тремя множителями: location, reputation,
     trade_bonus (§35 + §16 + npc.py trade_discount)
   - modifier_for_node(hidden, node_id, rng) — один бросок на ноду,
     кеш hidden["prices_by_node"], зеркало hidden["price_modifier"]
   - cached_modifier(hidden, node_id) — никогда не бросает кубик
     (можно звать из build_menu)

2. loop.py — trade wired (§35)
   - магазин — под-режим диалога: hidden["dialog_state"]["shop"]
   - _build_dialog_menu: при открытом магазине показывает
     dialog_buy_<item> / dialog_sell_<item> / dialog_trade_close
     вместо тем разговора
   - _open_shop: сначала обычный ответ на категорию "trade" (npc.py
     может выдать trade_discount), бонус запоминается в ds["last_bonus"]
     и превращается в множитель 0.8 на весь диалог
   - _execute_trade_buy: проверки (роль продаёт, хватает монет,
     комната ещё не куплена) → coin -= price, step += 1
   - _execute_trade_sell: удаляет 1 шт. (fangs/dragon_fangs — пара в
     одном слоте, продаются поштучно), coin += price
   - tavern_room — одноразовый товар: hidden["has_room_tonight"] = True,
     в инвентарь не попадает; вторая покупка в ту же ночь — отказ
   - sleep (и loop, и main._do_sleep) сбрасывает has_room_tonight
   - staff: покупка ставит hidden["has_staff"] = True
   - §9 трофейный путь: два goblin_staff, проданных чернокнижнику →
     он выдаёт настоящий staff (magic.record_loot_staff_sale)
   - ошибка покупки/продажи step НЕ двигает (иначе LLM зацикливается)
   - модификатор локации кидается в _execute_talk_to при первой встрече
     с торговой ролью: порядок кубиков движения/встречи не тронут

3. state.py / main.py
   - hidden: prices_by_node, price_modifier, magic (magic.new_state())
   - validate_state: мягкие проверки hidden.magic / hidden.prices_by_node
   - main._ensure_runtime_fields: setdefault для всех новых ключей
     (старые сейвы грузятся) + magic_mod.ensure_state(hidden)

4. burt/magic.py — обвязка (ядро не тронуто)
   - new_state / ensure_state: mage_met, teachers, loot_sold, granted
   - teacher_key: mage_event -> mage (ключ TEACHER_KIND)
   - record_teacher_spawn: стихия мага 1d4 в момент СПАВНА
   - spell_slots / spells_open / cast_ready(hidden, has_staff)
   - record_loot_staff_sale: 2 продажи goblin_staff -> True
   - train(hidden, visible, role): 1 раз за жизнь у учителя
     (trained_by), cleric->light, necromancer->dark, mage_event->его
     стихия, лимиты can_learn_*, навык +1 (кап 10) и видимость в
     visible["skills_visible"]

5. npc_spawn.py — редкий учитель-маг (§9)
   - maybe_add_mage(hidden, loc_type, node_id, rng):
     temple / dungeon, d6 >= 5, один раз за жизнь, стихия 1d4
   - вызывается в _arrive_at_node ПОСЛЕ ensure_npcs (порядок кубиков
     движения и спавна не меняется), кеш ноды обновляется

6. Сон (§5, закрывает #13)
   - loop._sleep_available: sleep.is_sleep_available(step, in_combat,
     has_bedroll, has_room) — иначе пункта "Sleep" нет
   - write_diary_and_go_sleep — та же проверка + step >= 19
   - сохранено отклонение: при HP < 25% сон доступен без постели
   - принудительный сон на шаге 20 работает всегда (иначе день виснет)

7. Каст в бою
   - _build_burt_stats: spells_available = magic.cast_ready(...)
     (staff + заклинание + учитель), а не просто «есть стихия»
   - бой уже умел каст: 1 MP, 3-6 урона, без self-penalty

8. Tests: 2099 -> 2222 passed (+123)
   - test_economy.py (33)
   - test_trade_loop.py (41)
   - test_sleep_availability.py (15)
   - test_magic_wiring.py (34)
   - фикстуры обновлены точечно: test_loop.py (bedroll в одном тесте),
     test_diary_epitaph.py (bedroll по умолчанию), test_integration.py
     (bedroll в тесте сна), test_loop_combat.py и test_cast_in_combat.py
     (has_staff + teacher_found для §9-гейта)
---------------------------------------------------------------------
CURRENT STATE (20.11.2026, end of session)
---------------------------------------------------------------------

- 2222 passed, 0 failed
- В реальной игре: встретил торговца → Trade → купил спальник/комнату/
  посох → продал лут; ночью сон доступен только с постелью или комнатой
- Магия: посох (покупка у мага/чернокнижника или 2 goblin_staff) +
  обучение (cleric/necromancer/маг) → в бою появляется "cast"
- Маг-учитель встречается в temple/dungeon на d6 >= 5, один раз за жизнь
- known_issues: 17 open (было 19), закрыты #4 trade, #8 magic, #13 sleep
- Не сделано намеренно: XP/уровни (#5), полная система навыков (#6),
  таблица урона оружия (#7), вера/статусы (#10), события (#11)

---------------------------------------------------------------------
QUICK START COMMANDS
---------------------------------------------------------------------

  cd E:\Butr-Ai
  .\.venv\Scripts\pytest.exe tests/ -q          # 2222 pass
  python main.py --new --dry-run                # inspect menu (no sleep at step 0)
  python main.py --new --max-steps 20           # walk, meet, talk, trade
  git --no-pager log --oneline -5

---------------------------------------------------------------------
MEMORY AID (all English)
---------------------------------------------------------------------

  # --- Economy (§35, §19) ---
  # economy.buy_price(item, location=, reputation=, trade_bonus=)
  # economy.sell_price(...) = floor(floor(base*0.5) * modifiers)
  # one modifier per node: hidden["prices_by_node"][node_id]
  # rolled on the first trade talk on that node (movement dice untouched)
  # shop lives in hidden["dialog_state"]["shop"] = {"bonus": 0.8 | 1.0}
  # keys: dialog_trade / dialog_buy_<item> / dialog_sell_<item> /
  #       dialog_trade_close

  # --- Tavern room (§5, §35) ---
  # one-shot goods: hidden["has_room_tonight"] = True, no inventory item
  # reset on sleep in BOTH loop and main._do_sleep
  # bedroll is a normal inventory item (5 coin)

  # --- Sleep gate (§5) ---
  # loop._sleep_available: sleep.is_sleep_available(step, in_combat,
  #     has_bedroll, has_room) OR critical HP (deviation)
  # forced sleep at step 20 ignores the gate

  # --- Magic (§9, §32) ---
  # cast_ready(hidden, has_staff) = staff + spell + teacher_found
  # hidden["magic"]: mage_met, teachers{mage_event: {element}}, loot_sold
  # mage spawn: temple/dungeon, d6 >= 5, once per life (1d4 element)
  # train: trained_by once per teacher per life; light/dark exclusive
  # trophy staff: 2 goblin_staff sold to the necromancer

TEST COUNTER: 2222 passed
  Last verified: 20.11.2026

=====================================================================
END OF HANDOFF 20.
=====================================================================