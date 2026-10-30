# Stage 1 — отчёт проверки, 2026-09-19

## Что реализовано

- Python 3.13 / FastAPI ingestion service, конфигурационные RSS adapters, строгая Pydantic validation конфигурации.
- Публичный JSON Schema `news.raw.v1`, обязательные validators UUID/RFC3339/URI с отказом старта при отсутствующих validator dependencies.
- MariaDB: raw_payloads, news_items, outbox_events, failed_items; Alembic upgrade/downgrade и проверка соответствия ORM.
- Транзакционный pipeline с savepoints, DB UNIQUE дедупликацией, сохранением исходного RSS документа и dead items.
- Независимый publisher: lease/token, SKIP LOCKED, PubAck, persistent retry/backoff, проверка схемы перед публикацией.
- NATS JetStream file storage и Docker volumes, non-root application/NATS runtime, автоматическая миграция при Compose startup.
- Health/readiness/source endpoints, structured logs, fixtures, unit/integration tests, отдельные test DB и broker.

## Результаты

| Проверка | Результат |
|---|---|
| `docker compose up --build -d` с пустыми volumes | Успех; MariaDB, NATS и ingestion healthy |
| Init владельца JetStream volume | Exit 0; основной NATS UID 1000 |
| Автоматическая миграция | Exit 0; revision 0001 |
| `/health`, `/ready`, `/sources` | HTTP 200; все 3 источника healthy |
| Прямой HTTP GET официальных feed URL | HTTP 200, RSS XML для Fed/SEC/ECB |
| Реальный ingestion после clean startup | Fed 15, SEC 25, ECB 15 |
| MariaDB news / published outbox / JetStream messages | 55 / 55 / 55 |
| Failed items после clean startup | 0 |
| Schema validation всех сохранённых JetStream сообщений | 55 из 55 прошли |
| Пересоздание NATS-контейнера с прежним volume | Все 55 сообщений сохранились |
| Перезапуск ingestion и повторный fetch | Количество новостей не изменилось; message_id совпали |
| Реальный stop/start тестового NATS, новый publisher process | PASS: 2 события pending при остановке; оба опубликованы после восстановления |
| `./scripts/test.sh` на Python 3.13, реальных MariaDB/NATS | **40 passed in 114.49s**, без warnings и skips |

Digest отсортированного набора message_id до и после restart:
`08dab898a2432e6def5fc968333ea6dca17a13f2477e9a5cfc2af9076a2460c0`.

Тесты охватывают нормализацию, whitespace/Unicode/HTML, повторяющиеся официальные заголовки, отсутствующие даты/GUID, hash, config, schema и обязательность format validators; dedup conflict recognition; сохранение, repeated fetch, restart, реальные UNIQUE гонки, rollback; malformed item/feed; независимость источников; offline/recovery outbox, истечение lease и stale ack, concurrent claim, dead outbox; реальный PubAck/dedup/stored JSON; HTTP API; migration roundtrip и metadata drift.

## Исправления, найденные проверкой

- Новый JetStream volume не был доступен UID 1000: добавлен одноразовый init-контейнер; NATS runtime остался без root.
- Jsonschema без optional dependencies молча пропускал date-time/URI formats: зависимости явно зафиксированы, добавлены негативные тесты и fail-fast проверка validators.
- Одинаковые заголовки Fed встречались у разных релизов: canonical hash включает URL и publication date вместе с normalized content.
- HTMLParser буферизовал заголовок ECB с `Q&A`: добавлен close() и regression test.

Промежуточные данные разработки были удалены только из созданных в этой сессии volumes проекта `market-intelligence`. Финальные реальные данные получены чистым запуском после исправлений. Другие проекты и их volumes не изменялись.

## Решения и отклонения от буквальной спецификации

- Raw хранится один раз на fetched document, транзакция охватывает feed, а не отдельную копию XML на каждый item. News и failed records содержат item_index; raw, news и outbox всё равно коммитятся атомарно.
- Неизвестные published_at, external_id и URL допускают null, чтобы не выдумывать данные. Все ключи обязательны, типы и допустимые значения строго заданы схемой.
- API и workers размещены в одном процессе; publisher работает отдельной coroutine, сетевой publish вынесен за пределы DB transaction. Для prototype достаточно одного poller instance.
- Source status хранится в памяти, а все данные доставки/dedup/lease/backoff — в MariaDB.

## Известные ограничения

Доставка at least once: будущие consumers должны быть идемпотентными по message_id. NATS duplicate window — 24 часа, один узел/replica. Нет HA, TLS/auth NATS, автоматической очистки raw/outbox, метрик/alerting, распределённого лидера polling и replay API. Исправления существующего GUID не создают новую normalized news; новые raw сохраняются. События, исчезнувшие из upstream RSS во время downtime, требуют provider-specific backfill. Новости и тестовые broker messages изолированы.

Весь исключённый scope (LLM, Event Engine, торговля, биржи, consumers будущих сервисов) не реализован.
