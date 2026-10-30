# Stage 1.5 — Content Enrichment

Самостоятельный Python 3.13/FastAPI сервис в `services/enrichment`. Получает только публичный `news.raw.v1`, публикует только `document.enriched.v1`; не читает ingestion DB и не импортирует код Stage 1. Никакой рыночной интерпретации или semantic classification.

```text
news.raw.v1 / NEWS_RAW
  → durable ENRICHMENT_V1 (explicit ACK)
  → validate → [exact input bytes + unique job] → COMMIT → ACK
  → claim DB job (lease/token, SKIP LOCKED)
  → source policy / content sufficiency
  → URL guard → rate limiter → bounded HTTP fetch
  → immutable snapshot → isolated extractor → normalized document
  → [document + outbox + final job state] → COMMIT
  → independent publisher → JetStream PubAck → published
  → document.enriched.v1 / DOCUMENT_ENRICHED
```

## Данные и транзакции

Отдельная logical database `enrichment`, отдельный пользователь с правами только на неё и отдельная Alembic revision `e0001`. Таблицы:

| Таблица | Назначение / ограничения |
|---|---|
| `enrichment_inputs` | original bytes (LONGBLOB), decoded JSON, SHA-256, stream sequence; PK `source_message_id` |
| `invalid_inputs` | quarantine malformed/schema-invalid input или identity conflict; exact bytes; PK payload hash |
| `enrichment_jobs` | UNIQUE source_message_id; pending/processing/retry_wait/completed/failed; attempts, retry time, lease/token, error, failed_at |
| `fetch_snapshots` | UNIQUE job_id; original response bytes, SHA-256, URLs, timestamp, HTTP/type/length, redirects, safe headers |
| `enriched_documents` | UNIQUE source_message_id и job_id; strict output payload и status |
| `outbox_events` | UNIQUE document_id и message_id; immutable payload, attempts, lease, next retry, published_at |
| `fetch_host_slots` | shared per-host reservations; row lock удерживается только при резервировании |

Input transaction атомарно создаёт input/job. Дубликат не создаёт job, snapshot, document или outbox. Same identity с изменённым JSON помещается в quarantine и не переписывает первое событие. Различающееся форматирование того же JSON считается дубликатом; exact bytes первого accepted input неизменны. Malformed input ACK только после сохранения quarantine. При DB failure — NAK с delay 5 секунд. Crash после commit до ACK приводит к безопасной повторной доставке.

Worker использует lease 180 секунд с уникальным token. Claim — короткая транзакция `FOR UPDATE SKIP LOCKED`; DNS/HTTP/extraction проходят вне неё. Сохранение snapshot и финальная транзакция проверяют актуальный token и срок lease. Snapshot создаётся один раз на job, повторный worker читает его вместо нового fetch. Устаревший worker не может завершить чужую работу. Crash до commit snapshot может привести к повторному HTTP GET; exactly-once внешнего HTTP не обещается.

Каждый валидный input даёт один terminal document, включая отказы. Невалидный input остаётся в quarantine. Job `completed` означает завершённую обработку, поэтому включает `partial`; `failed` соответствует document `failed/rejected`. `failed_at` может присутствовать у completed/partial, если enrichment не удался. После успешного transient recovery last_error может сохранять историю сбоя. Для анализа результата следует читать document status, а не только job status.

## Политики и статусы

`config/enrichment/policies.yaml` содержит exact source IDs из Stage 1 и strict configuration: `always`, `when_needed`, `never`, `minimum_body_characters` (240), `allowed_hosts`. Новая policy не требует изменения worker. Перечитывание при restart.

`when_needed` проверяет: пустой body; normalized body равен title; завершающий `…`/`...` при наличии URL; длина меньше порога. Сравнение title/body игнорирует регистр и лишние пробелы. Правила детерминированы. Неизвестная source policy — rejected, без HTTP. `never` не скачивает URL; недостаточный RSS остаётся partial/failed.

| Document status | Semantics |
|---|---|
| ready | успешный extraction минимум 100 символов либо достаточный RSS, не требовавший fetch |
| partial | enrichment не обеспечил полный текст, но сохранён непустой fallback |
| failed | нет полезного непустого body, fetch/extraction невозможен или не удался |
| rejected | запрос/результат сознательно запрещён security/resource policy; RSS сохраняется, если был |

`ready` — техническая оценка извлечения, не доказательство смысловой полноты. Generic extractor может оставить уведомление со ссылкой на приложение; сервис не обходит вложенные ссылки и не объединяет документы.

`fetch.status` и `extraction.status` независимы: например HTTP 200 + PDF без текста — fetch success, extraction text_unavailable, document partial/failed. Unsupported media сохраняется как snapshot, extraction unsupported. 403/404 не повторяются; RSS используется как fallback. Extraction title записывается отдельно, source title не меняется. Короткий extracted текст используется только если он длиннее исходного RSS, с partial status.

## Безопасный fetch

`DocumentFetcher` отделён от `ContentExtractor`. Разрешены только HTTP/HTTPS, стандартные порты 80/443, exact host allowlist. Запрещены credentials, whitespace/control characters, backslash, internal names, private/loopback/link-local/multicast/reserved/unspecified адреса и IPv4-mapped IPv6. Проверяются **все** DNS answers; смешанный public/private ответ отклоняется. Redirect destinations проходят ту же проверку до запроса, максимум 3 redirects.

После DNS validation HTTPX обращается к конкретному проверенному IP. Исходный Host и TLS SNI передаются отдельно; TLS verification включена. Pool разделён по исходным scheme/hostname/port, чтобы не переиспользовать TLS session для другого virtual host. HTTP transport не резолвит исходный hostname повторно. Proxy environment отключён (`trust_env=False`), cookie jar не отправляется через явно построенный Request. Это закрывает окно DNS rebinding между проверкой и соединением.

Timeouts: connect 5s, read 15s, общий deadline DNS + host wait + redirects + fetch + snapshot persistence 45s. Rate limit по hostname — 1 request/s, reservations общие для экземпляров в MariaDB; sleep вне транзакции. Сильно загруженный host может исчерпать общий deadline, затем job получит bounded retry. Все экземпляры должны иметь синхронизированные часы.

HTML/plain/unknown media: 5,000,000 bytes; PDF: 20,000,000 bytes. Проверяется Content-Length и поток реальных байтов. `%PDF-` позволяет распознать ошибочно маркированный PDF; limit уточняется при первом bounded chunk. Чтение прекращается до накопления bytes сверх limit. Заголовки сами по себе не разрешают неограниченное чтение.

`Accept-Encoding: identity`; неожиданный gzip/br/другой Content-Encoding даёт `unsupported_encoding`. Это осознанное ограничение: не допускается неограниченная распаковка HTTP body. Успешные snapshots хранят точные bytes тела, safe headers ETag/Last-Modified/Content-Type/Content-Length. Cookies/auth headers не сохраняются. Ошибки HTTP не сохраняют response body.

Transient: connect/read/total timeout, connection failure, temporary DNS failure, HTTP 408/429/500/502/503/504. Максимум 3 worker attempts, exponential backoff 5s × 2^(attempt−1) + jitter; cap 300s. Permanent errors завершают job сразу. Infrastructure crash сохраняет lease; при исчерпании attempts fetch не повторяется. HTTP Retry-After пока не используется; обязательный host rate limit остаётся активным.

## Extraction и воспроизводимость

HTML/XHTML — Trafilatura 2.2.0, generic main-content extraction; parser без network, удаление script/style/noscript/nav/footer, без выполнения JS. PDF — pypdf 6.19.0, только text-based, максимум 100 страниц. Plain text — charset из Content-Type, UTF-8 replacement с warning при ошибке. Encrypted/unsupported PDFs не расшифровываются; пустой PDF получает text_unavailable, OCR отсутствует.

Все extractors исполняются в отдельном фиксированном Python subprocess, без shell. Linux RLIMIT_AS 768 MiB, CPU 30s, файловая запись RLIMIT_FSIZE=0, wall deadline 30s с kill/wait. Ошибка/таймаут процесса становится результатом, основной event loop остаётся доступен. Это resource isolation, не полноценная OS sandbox против неизвестных уязвимостей native libraries. Container работает как UID 10002.

Нормализация: Unicode NFC, нормальные переводы строк/пробелы, удаление NUL, сохранение разумных абзацев. Максимум 200,000 символов; превышение rejected. Processor version и library version сохраняются. Hash — SHA-256 UTF-8 canonical JSON `{title,body,language}` с sorted keys и компактными separators. IDs, timestamps и metadata исключены.

Input title/categories/language и timestamps сохраняются. `ingestion_delay_seconds=received_at−published_at`; null при неизвестной publication date, может быть отрицательным при таком upstream timestamp. Historical items не отбрасываются; freshness не классифицируется.

## Output и NATS

Строгая Draft 2020-12 schema: `contracts/document/enriched/v1.schema.json`, все ключи определены, enum/status/reasons, UUID/date-time/URI formats проверяются. Дополнения к reference: отдельные failure/error reasons, extractor library_version, extracted_title, fetch attempt_count. Нет необходимости угадывать статус по null.

Input: durable `ENRICHMENT_V1`, explicit ACK, DeliverAll, ack_wait=30s, max_ack_pending=128, unlimited delivery для безопасного ожидания восстановления БД; это не unlimited HTTP retry. Существующий `NEWS_RAW` только читается, stream config не изменяется.

Output: `DOCUMENT_ENRICHED`, subject `document.enriched.v1`, file storage, одна replica, 1 GiB, max message 1,000,000 bytes, DiscardNew, duplicate window 24h. Publisher ставит `Nats-Msg-Id=message_id` и `Nats-Expected-Stream`. Outbox lease 60s, deadline15s; при outage pending сохраняется и повторяется с backoff до300s. Output retry не ограничен числом попыток, чтобы не терять документ при длительном outage. Invalid stored payload переводится в dead для расследования.

At least once: crash между PubAck и DB mark published допускает повторную доставку. Downstream обязан дедуплицировать по output message_id. Document/outbox IDs стабильны после commit. JetStream duplicate window не является глобальной exactly-once гарантией.

## Эксплуатация

`docker compose up --build -d` запускает оба независимых сервиса. `enrichment-bootstrap` создаёт database/user на существующем MariaDB volume, затем `enrichment-migrate` применяет собственную миграцию. Root credentials есть только у bootstrap; runtime использует enrichment user. Bootstrap не меняет пароль существующего пользователя. MariaDB `max_allowed_packet=64M` необходим для PDF LONGBLOB до20MB и SQL escaping; volumes сохраняются.

API `127.0.0.1:8001`: `/health`, `/ready`, `/stats`, `/documents/{document_id}`, `/jobs/{job_id}`. Readiness проверяет DB/migration, NATS/streams, живость задач; не запрашивает публичные сайты. Logs содержат input/job/snapshot/document/output IDs, hostname, attempt, status/duration/length без body и credentials. Полная цепочка связывается через IDs. `/stats` даёт grouped statuses и retries; отдельный Prometheus не вводится.

Retention, admin replay, миграция старых documents на новый extractor, HA, NATS auth/TLS, OCR/JS renderer и семантическая полнота остаются вне scope. Raw/input/snapshots/outbox растут без автоочистки. Изменение policy не перерабатывает уже завершённые jobs; immutable output не заменяется автоматически.

Проверки и smoke: [отчёт](../enrichment-verification.md), [machine-readable results](../enrichment-smoke.json).
