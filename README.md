# Market Intelligence — Ingestion, Content Enrichment, Event Engine

Надёжный приём RSS в MariaDB и публикация стабильного контракта `news.raw.v1` в NATS JetStream. Stage 1.5 получает `news.raw.v1`, извлекает HTML/PDF/plain text и публикует `document.enriched.v1`. Без LLM, торговых сигналов и интеграции с биржами.

Python 3.13, FastAPI/Pydantic, SQLAlchemy 2, Alembic, MariaDB 11.8, NATS JetStream 2.12. Прямые зависимости зафиксированы точными версиями в `services/ingestion/pyproject.toml`, транзитивные — в `constraints.txt`; Docker использует оба файла.

## Запуск

Нужны Docker Engine/Desktop и Docker Compose v2.

```sh
cp .env.example .env  # необязательно для локальных значений по умолчанию
docker compose up --build -d
docker compose ps -a
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/sources
docker compose logs -f ingestion
```

`migrate` автоматически выполняет `alembic upgrade head` после готовности MariaDB. Ingestion стартует после успешной миграции и продолжает собирать RSS при недоступности NATS. `nats-init` однократно устанавливает владельца нового volume; NATS работает от UID 1000, приложение — от UID 10001. Официальный MariaDB entrypoint инициализирует каталог и запускает сервер от пользователя mysql.

API опубликован только на `127.0.0.1:8000`. MariaDB и NATS доступны только во внутренней сети Compose. Пароли по умолчанию предназначены для локального прототипа. Credentials в `.env` игнорируются Git и исключены из Docker build context. Укажите собственный контакт в `INGESTION_USER_AGENT`, особенно для SEC.

```sh
docker compose down  # сохраняет volumes
# Не используйте down -v, если нужно сохранить новости и JetStream.
```

## Архитектура

```text
Official RSS → SourceAdapter → raw_payloads (original document bytes)
  → Normalizer → JSON Schema validation → UNIQUE dedup
  → news_items + outbox_events → COMMIT
  → independent OutboxPublisher → JetStream PubAck → published
```

Один ответ feed обрабатывается в транзакции: raw сохраняется первым, новости и outbox — в той же транзакции. Savepoints изолируют конфликты дубликатов; ошибки нормализации сохраняются в `failed_items` с raw ID и индексом элемента. Инфраструктурная ошибка откатывает весь fetch; следующий poll повторит его. Сырой документ сохраняется и при повторном fetch, и при некорректном RSS. Подробнее: [архитектурные решения](docs/architecture/ingestion.md).

## Реальные источники

| ID | Официальный feed | Poll |
|---|---|---|
| `fed_monetary_policy` | [Federal Reserve](https://www.federalreserve.gov/feeds/press_monetary.xml) | 60 сек |
| `sec_press_releases` | [SEC](https://www.sec.gov/news/pressreleases.rss) | 120 сек |
| `ecb_press` | [ECB](https://www.ecb.europa.eu/rss/press.html) | 120 сек |

Все URL проверены прямым HTTP GET 19 сентября 2026: HTTP 200 и валидный RSS XML (15 / 25 / 15 элементов соответственно). Доступность может зависеть от сети и политики провайдера. Автоматические тесты используют локальные fixtures и mocks; внешняя сеть им не нужна после сборки образов.

## Конфигурация

Source YAML находятся в `config/sources`, монтируются read-only. Конфигурация проверяется при запуске, включая отключённые источники. Неизвестные поля/adapter types, повторные ID, некорректные URL и интервалы вызывают понятную ошибку с именем файла/полем; значения credentials не выводятся.

| Environment variable приложения | По умолчанию | Назначение |
|---|---|---|
| `INGESTION_DATABASE_URL` | локальный Compose MariaDB URL | SQLAlchemy URL |
| `INGESTION_NATS_URL` | `nats://nats:4222` | адрес NATS |
| `INGESTION_SOURCES_DIR` | `/workspace/config/sources` | YAML каталог |
| `INGESTION_SCHEMA_PATH` | `/workspace/contracts/news/raw/v1.schema.json` | контракт |
| `INGESTION_USER_AGENT` | `MarketIntelligencePrototype/0.1 (local research)` | HTTP идентификация |
| `INGESTION_HTTP_TIMEOUT_SECONDS` | `20` | HTTP timeout |
| `INGESTION_MAX_FEED_BYTES` | `5000000` | лимит распакованного HTTP body |
| `INGESTION_PUBLISHER_INTERVAL_SECONDS` | `1` | ожидание при пустой очереди/ошибке БД |
| `INGESTION_WORKERS_ENABLED` | `true` | отключение фоновых workers для диагностики |

Compose подставляет `MARIADB_PASSWORD`, `MARIADB_ROOT_PASSWORD`, `INGESTION_PORT`, `INGESTION_USER_AGENT` из `.env`. Остальные значения передавайте в environment сервиса или Compose override; `.env` сам по себе не экспортирует произвольные параметры внутрь контейнера. Пароль в URL должен быть percent-encoded; примеры используют URL-safe значения. При смене пароля существующего MariaDB volume нужно отдельно изменить пользователя БД.

### Добавить стандартный RSS

Создайте `config/sources/example.yaml`:

```yaml
id: example_authority
name: Example Authority
enabled: true
connector:
  type: rss
  url: https://example.org/news.rss
poll:
  interval_seconds: 120
classification:
  categories: [macro]
priority: normal
language: en
```

Затем `docker compose restart ingestion`. Новый Python-класс не нужен. `priority` — пока только конфигурационные метаданные, не порядок обработки; категории декларативные, language — доверенный hint (`und`, если неизвестен). REST/WebSocket/HTML адаптеры позже реализуют `SourceAdapter` и собственный normalizer. Публичная схема допускает новые source types без изменения consumer контракта.

## Контракт и identity

[contracts/news/raw/v1.schema.json](contracts/news/raw/v1.schema.json) — единственный источник истины: Draft 2020-12, обязательные поля, `additionalProperties: false` на всех объектах, UUID, RFC3339 dates, ограничения строк. Validator включает `FormatChecker` и `rfc3339-validator`/`rfc3986-validator`; приложение отказывается запускаться при отсутствии любого используемого format validator. Форматы действительно проверяются.

- `message_id` — UUID, неизменен при повторных публикациях outbox.
- `source.external_id` — ID/GUID источника или `null`; URL не выдаётся за внешний ID.
- `timestamps.published_at` — UTC либо `null`, если дата отсутствует/не распознана. `received_at` всегда UTC. Дата receive никогда не заменяет дату публикации.
- `content` — plain text: HTML удалён, whitespace схлопнут, Unicode NFC. `body` может быть пустым; `title` обязателен.
- `url` — HTTP(S) URL либо `null`; относительные ссылки разрешаются относительно URL feed, fragment удаляется.
- `integrity.content_hash` — SHA-256 UTF-8 canonical JSON с sorted keys и компактными separators: `{content, url, published_at}`. Receive time, message/raw IDs и категории исключены. URL и дата различают повторяющиеся официальные релизы с одинаковым текстом.
- `raw.payload_id` указывает на исходный feed в БД. `news_items.item_index` помогает найти элемент. Payload event не содержит raw XML.

UNIQUE `(source_id, SHA256(external_id))` и `(source_id, content_hash)` работают в БД при конкурентной записи. Nullable external hash позволяет источники без GUID. Hash хранится в hex, исключая зависимость от case-insensitive collation внешнего ID. Дедупликация только внутри источника. Исправления существующего GUID в Stage 1 не создают новую новость; новый raw при этом сохраняется. Versioned updates — отдельное будущее решение.

## Доставка и восстановление

Publisher короткой транзакцией захватывает одну due-запись через `FOR UPDATE SKIP LOCKED`, выдаёт lease/token на 60 сек, затем публикует вне транзакции (deadline 15 сек). После PubAck условный UPDATE по token отмечает `published`; старый worker не может завершить чужой lease. Crash или cancel оставляют запись до истечения lease. Ошибки сети используют exponential backoff с jitter до 300 секунд; число попыток сохраняется. Невалидный persisted event становится `dead`, другие продолжают публиковаться.

JetStream: stream `NEWS_RAW`, subject `news.raw.v1`, file storage, volume, одна replica, duplicate window 24 часа, `Nats-Msg-Id=message_id`. Лимит 1 GiB, `DiscardNew`: при заполнении новые события остаются pending в MariaDB, старые не удаляются автоматически. Это **at least once**, а не глобальный exactly once: после crash между PubAck и DB UPDATE возможна повторная доставка за пределами duplicate window. Будущие consumers обязаны дедуплицировать по message_id.

Fetch: максимум 3 попытки для transport errors/408/429/5xx; затем per-source backoff до 30 минут. Постоянные HTTP errors не повторяются внутри fetch. Источники имеют отдельные asyncio tasks, DB операции выполняются в threads. Нет consumers будущих сервисов.

## API и логи

- `/health`: liveness процесса, HTTP 200.
- `/ready`: проверяет БД/ревизию миграции, JetStream и живость фоновых tasks; HTTP 503 при проблеме. Падение NATS не отключает сбор RSS.
- `/sources`: enabled/status/last_success/error type/счётчики последнего fetch.
- `/sources/{id}/health`: сохранённый статус последнего poll, без дополнительного HTTP запроса к провайдеру.

Статусы источников находятся в памяти и сбрасываются на restart. Логи JSON содержат UTC timestamp, event, source_id, payload_id, message_id/outbox_id, error_type по этапу. `item_staged` означает ещё не committed; подтверждение — `feed_committed`. Тексты сетевых исключений/URL credentials/raw content не логируются.

## Миграции и тесты

```sh
docker compose run --rm migrate
# Проверка соответствия ORM и миграции:
docker compose run --rm migrate alembic check
# Вся suite: создаёт отдельную ingestion_test DB, применяет миграции и запускает pytest.
./scripts/test.sh
# Настоящая остановка/запуск изолированного брокера и restart publisher:
./scripts/fault-test.sh
```

Fault test запускайте после suite; suite очищает test DB перед каждым DB-тестом. Скрипты не удаляют production data. Test broker `nats-test` из профиля `test` не публикует тестовые новости в рабочий stream. Для повторного fault test сначала повторите suite, чтобы очистить fixture IDs.

Локальные unit tests с Python 3.13:

```sh
cd services/ingestion
python3.13 -m venv .venv
. .venv/bin/activate
pip install -c constraints.txt '.[test]'
pytest -q tests/test_unit.py tests/test_adapter.py
```

Integration tests без `TEST_DATABASE_URL`/`TEST_NATS_URL` пропускаются; полный результат подтверждается только Compose suite. Проверяются реальные MariaDB unique constraints, гонки, savepoints, rollback, restart, lease expiry/stale ack, schema, malformed RSS, isolated source failure, pending/recovery, реальный JetStream PubAck/dedup/stored payload, API и migration roundtrip.

## Troubleshooting и ограничения

- `ready=503`: проверьте `docker compose ps -a`, `logs migrate`, `logs nats`. При offline NATS pending сохраняется и повторяется автоматически; source polling продолжается.
- HTTP 403 SEC: проверьте свой User-Agent/contact и сетевую политику. Обход блокировок не реализован.
- `source=failed/degraded`: error type и raw ID находятся в structured logs/`failed_items`; raw документ и item_index позволяют воспроизвести сбой. Невалидные элементы не ретраятся в tight loop, но могут снова появиться при очередном fetch. Автоматического replay/admin API пока нет.
- `outbox=dead`: исправьте причину schema validation до ручного replay. Не удаляйте raw/новости/outbox ради повторной отправки.
- Заполнен NEWS_RAW: освободите/увеличьте stream storage согласно политике хранения; pending DB event не теряется. Контролируйте и свободное место MariaDB.
- Raw каждого poll сохраняется, включая дубликаты: нужны будущие retention/archival policies. Prototype не имеет автоочистки, metrics/alerting, распределённого scheduler, TLS/auth NATS или HA.
- Нет гарантии получения новостей, которые исчезли из upstream RSS во время длительного downtime; backfill зависит от возможностей источника.
- Используйте один ingestion процесс для polling (без `uvicorn --workers N`). UNIQUE/leases защищают данные при дополнительных экземплярах, но лидерство poller не реализовано.

Фактические результаты запусков, исправления и отклонения от спецификации: [отчёт проверки](docs/verification.md).


## Stage 1.5 — Content Enrichment

Независимый сервис `services/enrichment`, база `enrichment`, API `127.0.0.1:8001`. Единственная граница с Stage 1 — NATS. Контракт `news.raw.v1` и код ingestion не изменены.

```sh
docker compose up --build -d
curl http://localhost:8001/health
curl http://localhost:8001/ready
curl http://localhost:8001/stats
docker compose logs -f enrichment
# Отдельные миграции, включая существующий MariaDB volume:
docker compose run --rm enrichment-migrate
docker compose run --rm enrichment-migrate alembic check
# Deterministic suite (отдельная enrichment_test DB и nats-test):
./scripts/test-enrichment.sh
./scripts/fault-test-enrichment.sh
# Регрессия Stage 1; suites/fault scripts запускать последовательно:
./scripts/test.sh
# Read-only smoke по уже обработанным реальным событиям:
docker compose exec -T enrichment python - < scripts/enrichment-smoke.py
```

`enrichment-bootstrap` создаёт собственную БД/пользователя; `enrichment-migrate` применяет `e0001`. Enrichment стартует после миграции. Root пароль не передаётся runtime. MariaDB packet limit увеличен до64MiB для snapshots PDF. Смена `ENRICHMENT_DB_PASSWORD` на существующем volume требует отдельного ALTER USER, как и для ingestion.

Source policies: `config/enrichment/policies.yaml`, ID точно совпадают с `config/sources`. Поддерживаются `always`, `when_needed`, `never`; порог240 символов; exact allowlist. После изменения — `docker compose restart enrichment`. Новый source без policy получает rejected document.

| Environment приложения | Default |
|---|---|
| ENRICHMENT_DATABASE_URL / ENRICHMENT_NATS_URL | собственная DB / nats:4222 |
| ENRICHMENT_POLICY_PATH | /workspace/config/enrichment/policies.yaml |
| ENRICHMENT_USER_AGENT | MarketIntelligenceEnrichment/0.1 |
| ENRICHMENT_CONNECT_TIMEOUT_SECONDS / READ_TIMEOUT_SECONDS / REQUEST_TIMEOUT_SECONDS | 5 / 15 / 45 |
| ENRICHMENT_HTML_MAX_BYTES / PDF_MAX_BYTES | 5000000 / 20000000 |
| ENRICHMENT_MAX_REDIRECTS | 3 |
| ENRICHMENT_MAX_REQUESTS_PER_SECOND_PER_HOST | 1 |
| ENRICHMENT_MAX_ATTEMPTS / RETRY_BASE_SECONDS | 3 / 5 |
| ENRICHMENT_LEASE_SECONDS | 180 |
| ENRICHMENT_EXTRACTION_TIMEOUT_SECONDS / EXTRACTION_MEMORY_MB | 30 / 768 |
| ENRICHMENT_MAX_PDF_PAGES / MAX_OUTPUT_CHARACTERS | 100 / 200000 |
| ENRICHMENT_MINIMUM_EXTRACTED_CHARACTERS | 100 |
| ENRICHMENT_DURABLE_NAME / WORKERS_ENABLED | ENRICHMENT_V1 / true |

В таблице сокращённые имена после `/` также имеют prefix `ENRICHMENT_`. Все env задаются внутри container environment; `.env` автоматически подставляет только `ENRICHMENT_DB_PASSWORD`, `ENRICHMENT_PORT`, `ENRICHMENT_USER_AGENT`. Для остальных используйте Compose override. Полные поля/validation — `app/config.py`.

Output schema: [document.enriched.v1](contracts/document/enriched/v1.schema.json). Исходные title/categories/timestamps сохраняются, extracted_title отдельно, body plain text с абзацами. Lineage связывает input→snapshot→document→stable output message ID. `ready/partial/failed/rejected` и отдельные fetch/extraction statuses доступны в event; future Event Engine должен использовать этот контракт.

При `ready=503` проверьте database/migration/NATS через `docker compose ps -a` и logs. При HTTP403/404 исходный RSS остаётся fallback; SEC в smoke вернул403 и 25 документов partial. Это не сбой readiness. При transient errors видны retry_wait/next_retry_at через `/jobs/{id}`. Pending outbox автоматически восстанавливается после NATS outage. Rejected URL не обходится; проверьте allowlist/DNS/redirect. Snapshot reuse исключает повторный fetch после его commit. На завершённые jobs изменение policy не влияет.

Ограничения: без OCR/JS rendering/обхода антибота; HTTP compression, нестандартные порты, encrypted PDFs не поддерживаются; generic extraction не гарантирует смысловой полноты и не следует по ссылкам на приложения. Raw/snapshots требуют будущей retention policy. Подробности безопасности, retries и транзакций: [архитектура Stage 1.5](docs/architecture/content-enrichment.md). Результаты тестов и реальные Fed/SEC/ECB: [проверка Stage 1.5](docs/enrichment-verification.md).


## Stage 2 — Event Engine

Независимый сервис `services/events`, собственная database `events`, API `127.0.0.1:8002`. Получает `document.enriched.v1` только через NATS и публикует `event.detected.v1` / `event.updated.v1` по одному строгому [event.canonical.v1](contracts/event/canonical/v1.schema.json). Описывает событие без sentiment, impact, confidence, trading или LLM.

```sh
docker compose up --build -d
curl http://localhost:8002/health
curl http://localhost:8002/ready
curl http://localhost:8002/stats
docker compose logs -f events
# Собственные bootstrap/migration с существующим или пустым volume:
docker compose run --rm events-migrate
docker compose exec events alembic check
# Suites/fault scripts используют общую test-инфраструктуру: запускать последовательно.
./scripts/test-events.sh
./scripts/fault-test-events.sh
./scripts/test.sh
./scripts/test-enrichment.sh
# Read-only проверка существующих 55 реальных документов, событий и lineage:
docker compose exec -T events python - < scripts/events-smoke.py
```

Exact input/job фиксируются до ACK. Quality Gate допускает usable partial/failed документы. RuleBasedEventExtractor создаёт список EventCandidate; Event Core отдельно ведёт many-to-many event_documents, canonical identities, immutable revisions и outbox. Same document_id не создаёт повторную обработку. Exact key защищён UNIQUE/row lock; fuzzy token Jaccard создаёт только suggestions. Разные даты/типы FOMC не объединяются. Первый source — detected, второй независимый source.id через exact key — corroborated.

Настройки: `config/events/taxonomy.v1.yaml`, `entities.v1.yaml`, `sources.yaml`, `rules/core.yaml`. Все версии и полный config snapshot/hash сохраняются у extraction run. Правила Fed statement/minutes/projections; ECB interview/policy/wages/speech; SEC proposal/adoption/guidance/enforcement/meeting/report/personnel. Interview имеет приоритет над speech. Незнакомые person mentions unresolved с null entity_id.

`.env`: EVENTS_DB_PASSWORD=local_events, EVENTS_PORT=8002. Runtime environment: EVENTS_DATABASE_URL, EVENTS_NATS_URL, EVENTS_CONFIG_DIR, EVENTS_DURABLE_NAME=EVENTS_V1, EVENTS_WORKERS_ENABLED=true, EVENTS_LEASE_SECONDS=120, EVENTS_MAX_ATTEMPTS=3, EVENTS_RETRY_BASE_SECONDS=2. Остальные env передавайте через Compose override; `.env` автоматически не экспортирует их в container. Source quality/correlation thresholds в YAML. После изменения config — restart events; completed inputs автоматически не переобрабатываются. При смене пароля на существующем DB volume отдельно измените пользователя.

Read-only API: `/events/{id}`, `/events/{id}/revisions?limit=100&offset=0`, `/documents/{document_id}/extraction`, `/correlation-suggestions?limit=100&offset=0`. Полный document body в canonical output не копируется. Publication timestamps отделены от event_time; неизвестный event time остаётся null. Source title нормализуется минимально, summary не генерируется.

Troubleshooting:

- ready503: проверить logs events/events-migrate/events-bootstrap и зависимости DB/NATS. Публичные сайты не участвуют в readiness.
- failed processing: `/documents/{id}/extraction` показывает attempts/error и immutable run; точный input и configuration позволяют воспроизвести ошибку. Детерминированный poison input ограничен3 attempts.
- malformed/identity-conflicting input: dead_inputs, ACK только после quarantine commit. Нет автоматического replay/admin edit API.
- pending outbox при NATS outage: сохраняется и повторяется автоматически с тем же message_id. Revision N+1 ждёт published N; dead revision требует расследования, не пропускается молча.
- не произошло merge: без сильного exact key это ожидаемо. Одинаковые source/date/title не являются identity. Suggestions не меняют canonical events.
- низкий quality у ready документа: high требует≥500 body chars; quality не является статистической confidence.

Ограничения: deterministic English title/URL patterns, небольшой registry, люди преимущественно unresolved; ограниченный date parser, отсутствие automatic replay/merge/retention/HA. До32 candidates на обработку и1000 evidence documents на event; payload≤1MB. Current fuzzy scan ограничен500 recent same-type/actor events. Полная спецификация semantics и расширения extractor: [архитектура Stage2](docs/architecture/event-engine.md). Результаты всех suites, smoke counts, false-merge inspection и четыре полных canonical JSON: [отчёт Stage2](docs/events-verification.md).

## Stage 3 — Market Data

Independent Binance Spot BTCUSDT collector on `http://127.0.0.1:8003`. Stores sampled market snapshots, closed minute candles and transactional `market.snapshot.v1` outbox events in its own `market_data` database. Historical backfill supplies candles only; bid/ask and spread before live collection remain unavailable.

```sh
docker compose up -d --build market-data
./scripts/test-market-data.sh
./scripts/test-market-data-faults.sh
docker compose exec market-data python -m app.backfill --symbol BTCUSDT --interval 1m --from 2026-04-29T17:58:00Z --to 2026-04-29T18:03:00Z
curl 'http://127.0.0.1:8003/market/snapshot?symbol=BTCUSDT&at=2026-04-29T18:00:00Z'
```

See [architecture and API](docs/architecture/market-data.md), [verification](docs/market-data-verification.md), and [strict event contract](contracts/market/snapshot/v1.schema.json). Test and fault scripts share the isolated test broker: run suites sequentially. Production NATS is not stopped by the fault script.

## Stage 3.5 — Market Context Resolver

Independent service on `http://127.0.0.1:8004`, own `market_context` DB. Consumes canonical event creations/updates and resolves seven BTCUSDT market points through the Stage 3 API. Context identity includes canonical event revision; future points are scheduled and updates are versioned with transactional outbox. Candle-only history never invents bid/ask or spread.

```sh
docker compose up -d --build market-context
./scripts/test-market-context.sh
./scripts/test-market-context-faults.sh
curl 'http://127.0.0.1:8004/stats'
```

See [architecture and API](docs/architecture/market-context.md), [verification and real examples](docs/market-context-verification.md), and [strict contract](contracts/market/context/v1.schema.json). Run regression/fault scripts sequentially because they share the isolated test broker.


## Stage 3.5.1 — Causal context / Stage 4 boundary

The resolver now uses `mode=causal`: snapshots observed no later than target, or the last candle closed no later than target. Legacy context revisions remain immutable; migration c35101 schedules new causal revisions.

**Stage 4 LLM market input must use `GET /contexts/{context_id}/decision`. Never pass the full context, its NATS payload, or revision history to the LLM.** The decision projection contains only offsets −15m, −5m and T. Positive offsets are outcomes for later evaluation. Public `market.context.v1` and previous contracts are unchanged; roles are deterministic internal metadata and are explicit in the new decision projection.

See [causal policy and upgrade](docs/architecture/market-context.md), [verification / Fed example](docs/causal-context-verification.md).


## Stage 3.5.2 — Decision Time

The Stage 4 projection now separates event occurrence from actual joint input availability. `GET /contexts/{context_id}/decision?basis=live` (default) returns `decision_basis=live_observed`, `historical_simulation=false`, exact pinned evidence and only three causal market points relative to `decision_at`. Late backfilled candles are excluded from live knowledge.

Use `?basis=research_hypothetical` explicitly for publication-time simulations. These carry `decision_basis=source_published_at`, `historical_simulation=true` and `historical_content_verified=false`, with actual fetch/availability timestamps preserved. Existing NATS schemas and immutable context revisions are unchanged.

See [Decision Time semantics](docs/architecture/decision-time.md) and [verification](docs/decision-time-verification.md). Run `python3 scripts/decision-time-smoke.py` for the read-only real-data proof.


## Stage 3.5.3 — Market Data Freshness

The decision endpoint applies `causal_asof_fresh_v1`: realtime observations must be at most 3 seconds old and closed candles at most 60 seconds old relative to each target (configurable). Stale prices and derived fields are removed. Stage 4 must require `decision_ready=true` (fresh T); use `complete=true` when all three causal points are required. Sparse coverage is explicitly `market_data_unavailable`.

See [policy and configuration](docs/architecture/market-freshness.md), [verification](docs/market-freshness-verification.md), and run `python3 scripts/freshness-smoke.py` for real examples. Existing revisions and NATS contracts remain unchanged.


## Stage 4 — LLM Analysis

Independent service `llm-analysis` on localhost:8005 uses only a validated Stage 3.5.3 decision package, pinned evidence and fresh causal market points. It freezes canonical JSON + SHA-256 before a no-tools OpenAI Responses request. Default model is `gpt-6-astra`, reasoning effort `medium`; prompt `btc_event_analysis_v1`. Outputs use strict `contracts/analysis/v1.schema.json` and transactional outbox → `analysis.completed.v1`. No signals or trades are created.

Set `OPENAI_API_KEY` in ignored `.env`; `docker compose up -d --build llm-analysis` provisions its separate DB. Automatic live event consumption defaults off (`LLM_ANALYSIS_AUTO_LIVE_ENABLED=false`) to avoid an unbounded initial paid run. Submit specific contexts through `POST /analyses`; historical research requires explicit mode and run UUID. Readiness is 503 without provider credentials.

Run `scripts/test-llm-analysis.sh` and `scripts/test-llm-analysis-faults.sh` sequentially. Bounded three-event preflight: `docker compose exec -T llm-analysis python -m app.smoke --prepare-only`; remove the flag only for the authorized real API smoke. See [architecture/API/reliability](docs/architecture/llm-analysis.md) and [verification](docs/llm-analysis-verification.md).

## Stage 4.5 — Research Dashboard

Authenticated, read-only Laravel + Filament panel at `http://localhost:8006`. It reads the six service HTTP APIs; its own SQLite stores local login users only. Includes Overview, searchable/filterable Events and detail, Analyses and detail, Market, Sources and System. LIVE and RESEARCH HYPOTHETICAL decisions are explicit; causal market data and evaluation-only outcomes are separate.

Set `DASHBOARD_APP_KEY`, `DASHBOARD_ADMIN_EMAIL` and `DASHBOARD_ADMIN_PASSWORD` in root `.env` (already generated in the current workspace). Run `docker compose up -d --build dashboard`; sign in with `research@local.test` and the password from `.env`. No analysis/provider request can be started from this dashboard.

Run `./scripts/test-dashboard.sh`. See [setup, architecture and API mapping](docs/architecture/research-dashboard.md) and [test / real UI smoke results](docs/dashboard-verification.md).

## Stage 5 — Evaluation Engine

Independent service on `http://localhost:8007`, own `evaluation` DB, consumes `analysis.completed.v1`. Compares four forecasts with fresh decision-time-relative outcomes from Market Context using Decimal arithmetic, frozen configurable thresholds, immutable revisions and transactional outbox. `unclear` is not scored. `/metrics` always reports sample size and excludes labelled fixtures by default. Dashboard adds Evaluations and an event-detail evaluation section.

```sh
docker compose up -d --build evaluation
./scripts/test-evaluation.sh
./scripts/test-evaluation-faults.sh
curl 'http://localhost:8007/metrics?group_by=horizon'
```

Optional fixture smoke: explicitly enable `EVALUATION_FIXTURES_ENABLED=true`, recreate evaluation, then `docker compose exec -T evaluation python -m app.smoke`. It uses separate fixture subjects and real market outcomes; no model API is called. Read [architecture, semantics and APIs](docs/architecture/evaluation.md) and [verification](docs/evaluation-verification.md). Run backend/fault suites sequentially.

## Stage 5.5 — Event Intelligence

Independent deterministic service at localhost:8008 enriches canonical event revisions with BTC relevance, novelty, evidence quality, specificity and explicit unavailable surprise/expectations. Config-driven ruleset 1.1, strict `event.intelligence.v1`, own DB, immutable versioned results and transactional outbox. No LLM call is made by this stage.

The dashboard Event Detail includes Event Intelligence. Stage 4 optionally accepts `intelligence_id` using a separate prompt and frozen input; legacy analyses are unchanged. Live decisions account for intelligence publication availability and re-resolve fresh causal market data. Historical derivations are explicitly hypothetical.

See [architecture and API](docs/architecture/event-intelligence.md), [verification and 55-event distribution](docs/event-intelligence-verification.md), [full smoke payloads](docs/event-intelligence-verification.json). Run `scripts/test-event-intelligence.sh` and `scripts/test-event-intelligence-faults.sh` sequentially.

## Document Intelligence — DI-1

Independent local EN/RU NLP service on localhost:8009. Consumes full `document.enriched.v1`, extracts versioned entities, measurements, dates, dependency relations, domain facts and topics, and publishes strict `document.intelligence.v1` with exact evidence spans. Own DB, immutable runs and transactional outbox; no LLM requests, routing or trading.

Event Detail includes Document Intelligence with click-to-expand highlighted evidence. Run `scripts/test-document-intelligence.sh`, `scripts/test-document-intelligence-faults.sh`, and `scripts/evaluate-document-intelligence.sh` sequentially. See [architecture/API](docs/architecture/document-intelligence.md), [verification](docs/document-intelligence-verification.md), and [10-document gold bootstrap](datasets/document_intelligence/gold/manifest.json).

## Document Intelligence — DI-2 Article Router

Article Router at localhost:8010 consumes `document.intelligence.v1` and publishes immutable, explainable `article.routing.v1`. Separate `article_routing` database, versioned rules/high-value registry, five route classes and transactional outbox. No LLM requests.

Dashboard adds **News Feed** and **News Detail**, including full observed text and DI evidence. Its only new writes are human labels/review status; `send_to_llm` saves a flag without calling a model. Set a random `ARTICLE_ROUTER_REVIEW_TOKEN` in root `.env` (already generated locally); dashboard and router share it server-side.

```sh
docker compose up -d --build article-router dashboard
./scripts/test-article-router.sh
./scripts/test-dashboard.sh
docker compose exec -T article-router python < scripts/smoke-article-router.py
```

See [architecture, APIs and research replay](docs/architecture/article-router.md), [55-document and manual UI verification](docs/article-router-verification.md), and [machine-readable results](docs/article-router-verification.json).

## Document Intelligence — DI-3 Event Engine v2

Parallel `event-research` service at localhost:8011 consumes DI-1 facts and publishes strict `event.research.v2`. Fact evidence takes precedence, metadata rules remain supporting/fallback, classification conflicts are explicit, and different candidate types are preserved. Production canonical v1 and correlation are unchanged.

News Detail and Event Detail add read-only **Event Engine Comparison**, including fact provenance and frozen human evaluation. No LLM calls. Start with `docker compose up -d --build document-intelligence article-router event-research dashboard`; test with `scripts/test-event-research.sh` and dashboard tests.

See [architecture, contracts and replay](docs/architecture/event-engine-v2.md), [55-document comparison and changed classifications](docs/event-engine-v2-verification.md), and [full research results](docs/event-engine-v2-verification.json).

### DI-4 — Correlation v2 (parallel research)

Event Research now builds versioned fact fingerprints and isolated canonical research revisions. Only complete exact identity auto-merges; suggestions never do. Production events and DI-3 outputs remain immutable. News Detail and Event Detail show a read-only **Correlation** block.

See [architecture / API / replay](docs/architecture/correlation-v2.md) and [verification](docs/correlation-v2-verification.md). Configuration: `config/event_research/correlation.v1.json`.

### DI-5 — Semantic Article Intelligence

Local BGE-M3 + multilingual GLiNER enrich DI-1 into immutable `article.semantic.v1` research profiles. Read-only Article Insight API on localhost:8012 and an **ARTICLE INSIGHT** block at the top of News Detail. Full stored-body chunk coverage, exact evidence, versioned bilingual ontology, separate review labels and parallel routing comparison; no external LLM calls or production router switch.

See [architecture, model pins, setup and APIs](docs/architecture/article-semantic.md) and [DI-5 verification, pilot review and limitations](docs/article-semantic-verification.md). Tests: `scripts/test-article-semantic.sh`, `scripts/test-dashboard.sh`.

### DI-5.1 — Semantic precision and real Russian sources

Versioned contrastive examples and deterministic evidence aggregation filter article concepts, claims and assets while retaining DI-5 history. Official Bank of Russia and MOEX RSS use the shared pipeline. Dashboard supports Russian Article Insights, DI-5 vs DI-5.1 comparison and append-only concept/false-positive review.

See [architecture and operational limits](docs/architecture/semantic-precision.md), [verification and EN/RU metrics](docs/semantic-precision-verification.md), and [ten Russian source articles with explained insights](docs/semantic-precision-ru-examples.md). The fixed RU corpus contains 20 CBR and 20 MOEX real documents; Codex pilot labels are not independent human validation. No external LLM API calls or production-router switch.
