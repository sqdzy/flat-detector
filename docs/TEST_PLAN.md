# Тест-план flat-detector v0.1

**Статус:** Draft; тесты сформированы из SPEC, реализация ещё не выполнялась. Критерий релиза — подтверждённые разрешения на источники, прохождение AC и 7-дневный пилот.

## Матрица трассировки

| Требования | Критерии | Тип | Основные фикстуры |
|---|---|---|---|
| FR-1..FR-5 | AC-1, AC-2 | policy/integration | disabled, missing_permission, 403, 429, CAPTCHA |
| FR-6..FR-8 | AC-3, AC-4, AC-24 | parser/contract | renamed CSS, duplicate IDs, price history, missing price |
| FR-9..FR-10 | AC-5, AC-6, AC-19 | state/evidence | live, reserved, removed, independent/duplicated copies |
| FR-11..FR-13 | AC-7..AC-9 | geometry/route | inside/outside polygons, real walking route, unavailable provider |
| FR-14, FR-15, FR-23 | AC-10, AC-23 | interpretation/licensing | outlier, no photo reuse, conflicting facts |
| FR-16..FR-17 | AC-11 | Telegram handler | first start, consent, settings, replayed update |
| FR-18 | AC-12 | clock/DST | last Sunday of March and October in Europe/Berlin |
| FR-19..FR-20 | AC-13..AC-15, AC-20 | delivery | duplicate scheduler, 429, timeout, 403, stop/delete |
| FR-21..FR-22 | AC-16, AC-17, AC-21, AC-22 | MCP/permissions | readonly, malicious URL, non-owner, consent false |
| FR-24 | AC-18, AC-24 | operations | parser drift, dead source, sanitized logs |

## Наборы тестов

### T1 — правила источников (blocking)
- Все source registry записи по умолчанию disabled; требование policy gate тестируется unit и integration.
- Утверждённый fixture API / HTML под контролируемым mock host способен сканироваться; неразрешённые живые домены никогда не запрашиваются в CI.
- 401, 403, 429, CAPTCHA, HTML после redirect на login, HTTP 200 с пустой заглушкой блокировки не трактуются как пустая выдача.
- Проверка разрешения на хранение/публикацию метаданных делается до snapshot/уведомления.

### T2 — корректность данных
- JSON Schema нормализации rejects price <= 0, area <= 0, rooms != 1 (для shortlist), неполный исходный объект маркируется `UNVERIFIED`.
- Fixture replay покрывает diff цены, обновление времени, простое повторение, расхождение цены в двух источниках, расхождение этажей и почти одинаковые объявления.
- Property tests проверяют, что негативное событие снятия не создаётся из сетевой ошибки или отсутствия в одной поисковой выдаче.
- Независимые кластеры evidence и удалённые stale snapshots не порождают `ACTIVE_INDIRECT`.

### T3 — география/транспорт
- Контрольный набор точек/адресов на границах polygon включает и исключает соседние районы согласно утверждённому fixture GeoJSON.
- Известный пешеходный маршрут с обходом преграды длиннее расстояния по прямой; система не выводит режим `WALK_ROUTE`, если получила только геодезическое расстояние.
- Недоступный routing provider, исчерпанная quota или null-coordinate дают `ROUTE_UNVERIFIED`, а не число, сгенерированное моделью.

### T4 — Telegram подписки/доставка
- `/start` без согласия не подписывает; повторное `/start` не создаёт дубль; callback data подписаны/проверяются.
- `/stop` между созданием outbox и отправкой предотвращает отправку при повторной проверке subscriber state.
- `sendMessage 429` выдерживает `retry_after`; `403 blocked` переводит subscriber в inactive; после ответного 200 сохраняется `telegram_message_id`.
- Fault injection: подтверждённый sendMessage + crash до commit создаёт `UNCERTAIN`, но не бесконечный retry. Документировать вероятную потерю сообщения при выборе no-duplicate policy.
- Два scheduler одновременно не формируют два daily digest: unique (`subscription_id`,`local_day`) + лидерство.
- Нагрузочный прогон ≥100 подписчиков соблюдает 1/с на чат и настроенный глобальный токен-бакет.

### T5 — MCP/security
- MCP Inspector: initialize, tools/list, каждый tool happy/invalid/not found, JSON Schema, tool annotations, объект `ErrorResponse`.
- `analyst_readonly` не может вызвать `request_listing_recheck` и не может отправить сообщение/получить чужой Telegram ID.
- SSRF-пакет: `http://127.0.0.1`, `http://169.254.169.254`, `http://[::1]`, DNS rebinding и цепочки 302 в приватную сеть отвергаются; каждый URL перепроверяется по фактическому разрешённому IP до connect.
- Контрольные prompt injection в HTML заголовках, описаниях, названиях файлов не запускают админский recheck и не открывают чужие ресурсы.
- Никаких bot/источниковых токенов в schema, tool results, журналах ошибок, trace ZIP или fixture snapshots.
- `request_listing_recheck` разрешён только owner, `confirmed=true`, уже сохранённому ID и активному разрешённому источнику; repeated calls dedup/rate-limit.

### T6 — нагрузка/восстановление
- CI: миграция вверх на пустой БД, повторный запуск миграции, rollback предварительно определённой обратимой миграции.
- Kill collector во время lease, restart после ttl: ровно одна завершённая нормализация без потерянной истории.
- Kill scheduler на DST переходе: за локальный день одна запись daily digest.
- Restore с зашифрованного backup на отдельном тестовом PostgreSQL; сверить row counts, FK, outbox.
- p95 MCP <=2s на 1000 fixtures; доля доставленных дайджестов за 10 мин >=95% во время пилота при исправных внешних API.

## Релизные блокеры

1. Нет прав/разрешённого канала для автоматизированного источника — блокируется только конкретный адаптер; бот можно запускать на разрешённых/ручных/тестовых данных, честно сообщая неполное покрытие.
2. Любой fail-open по source permission, SSRF, секретам или отправке неподписанному пользователю — blocker всего релиза.
3. Любая ошибка, при которой 403/тайм-аут означает «объявление снято», — blocker релиза рекомендаций.
4. Не пройдены тесты на повторные Telegram сообщения, 429 и отписку — blocker внешней рассылки.
5. Нет подтверждения прав на републикацию фото — не блокирует ссылочную рассылку, но блокирует фото/полные тексты.

## Пилот и критерии приёмки

Сначала 2–5 согласных пользователей и контролируемый набор разрешённых источников/фикстур. Длительность — ≥7 последовательных суток. Фиксировать: доставку после 11 по timezone, метки источников, точность геофильтра, долю подтверждённой актуальности, дубли физических сообщений и длительность деградаций.

Целевые критерии при доступности зависимостей: не менее 95% дайджестов доставляются в ≤10 мин; 0 заведомо снятых/забронированных в основных рекомендациях; 0 уведомлений после `/stop`; 0 известных повторных доставок уже подтверждённого event; 0 источников, опрошенных без legal gate. После пилота owner рассматривает перевод существующего ChatGPT-мониторинга в резерв и утверждает SPEC `Approved`.


## v0.2 evidence additions (2026-09-23)

- Real in-memory MCP SDK 2.2.0 Client enumerates four tools, invokes each against seeded SQLite data, rejects a non-existent command tool and does not return subscriber IDs (`tests/test_mcp_live_sdk.py`).
- MCP streamable-HTTP initialize uses explicit local Host (`200 OK`) and rejects unexpected Host (`421 Misdirected Request`) (`tests/test_mcp_http_security.py`). Host checks are not an identity/auth layer.
- Outbox crash recovery marks stale `CLAIMED` sends `UNCERTAIN` and does not automatically repeat them (`tests/test_delivery_recovery.py`). Worker wiring tests require recovery before a new delivery attempt.
- Real PostgreSQL migration and competing-worker `SKIP LOCKED` test added to CI but skipped locally because the current test container has no PostgreSQL server (`tests/test_postgres_integration.py`, `docs/POSTGRESQL_CI.md`). Do not claim this integration gate has passed until CI proves it.
- Latest observed local command: `PYTHONPATH=/opt/pyvenv/lib/python3.13/site-packages .venv/bin/python -m pytest -q --cov=flat_detector --cov-report=term`; outcome **39 passed, 1 skipped; 84% measured line coverage**.
