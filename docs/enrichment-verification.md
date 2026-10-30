# Stage 1.5 — отчёт проверки

Дата: 19 сентября 2026. Проверено в Docker, Python3.13, MariaDB11.8.6, NATS2.12.5. Все команды ниже выполнены, а не только предложены.

## Реализация

Созданы независимые компоненты в `services/enrichment`: consumer, repository/jobs, policies, URLGuard/HTTPDocumentFetcher, shared host limiter, Trafilatura/pypdf/plain extractors, resource-limited process runner, document builder, strict schema validator, transactional outbox, JetStream publisher, FastAPI API. Собственные Alembic migration и Dockerfile с точными direct/transitive dependency versions.

Новые файлы конфигурации и контракта: `config/enrichment/policies.yaml`, `contracts/document/enriched/v1.schema.json`. Добавлены test fixtures HTML/PDF, deterministic suite, real-broker fault probe, smoke verifier, `scripts/test-enrichment.sh`, `scripts/fault-test-enrichment.sh`, `scripts/enrichment-smoke.py`. README и Compose дополнены Stage1.5.

База `enrichment`: enrichment_inputs, invalid_inputs, enrichment_jobs, fetch_snapshots, enriched_documents, outbox_events, fetch_host_slots. UNIQUE constraints ограничивают один input/job/document/output на source_message_id. Snapshot bytes неизменны после commit. Root используется только bootstrap; runtime имеет собственные права.

NATS input — существующий NEWS_RAW/read-only config, durable ENRICHMENT_V1, explicit ACK после input/job commit. Output — DOCUMENT_ENRICHED, document.enriched.v1, file storage, 1 replica, 1GiB, DiscardNew, 24h duplicate window, Nats-Msg-Id. Доставка at least once; identity downstream стабильна.

## Тесты

| Проверка | Passed | Failed | Skipped | Warnings |
|---|---:|---:|---:|---:|
| `./scripts/test-enrichment.sh` | 94 | 0 | 0 | 2 |
| `./scripts/test.sh` — неизменённая Stage1 suite | 40 | 0 | 0 | 0 |
| `./scripts/fault-test-enrichment.sh` | оба этапа PASS | 0 | 0 | 0 |

Enrichment suite: 9.31s; Stage1 regression:1.46s, время без сборки образов. Два предупреждения только из тестового FastAPI/Starlette TestClient: deprecated httpx adapter и anyio.abc.BlockingPortal alias. Они не подавлены. Runtime не использует TestClient; дополнительный httpx2 ради тестов не добавлялся.

Unit coverage: все sufficiency heuristics и режимы, HTML boilerplate/script removal, plain charset, text/empty/invalid/page-limited PDF, normalization/hash, strict enum/required fields/formats, historical/unknown timestamps. Integration использует настоящую MariaDB; полный вход→ACK→document→output проверен на настоящем изолированном NATS. Внешние сайты deterministic tests не используют.

Migrations: upgrade/downgrade/upgrade и Alembic compare_metadata проходят; `docker compose exec -T enrichment alembic check`: No new upgrade operations detected.

Stage1 regression дополнительно: SHA-256 всех39 исходных файлов services/ingestion, contracts/news и config/sources совпали со снятым до реализации baseline. Код Stage1, contract и source configs не изменены. Production NEWS_RAW не пересоздавался; тест также сравнивает input stream configuration до и после enrichment consumer/publisher.

## Надёжность

- Duplicate delivery: concurrent inserts в MariaDB и два реальных NATS messages с одинаковым input message_id (без NATS dedup header) дают один input/job/document/outbox. Дубликат после завершения ACK, без второго HTTP.
- ACK boundary: callback ACK проверяет input/job из новой DB session, подтверждая commit; до ACK нет document/extraction. DB failure вызывает NAK, не ACK. Malformed NATS input сохраняется в quarantine, последующее валидное событие успешно проходит pipeline.
- Restart: crash до snapshot безопасно reclaim; crash после snapshot повторно использует те же bytes без fetch. Token fences stale worker. Новый consumer привязывается к прежнему durable. Restart финального production container не создал дополнительных documents/outbox.
- Настоящий NATS outage: тестовый broker остановлен Compose; документ сохранён, output pending; после start новый процесс publisher отправил payload с тем же message_id. Payload считан management API и сравнен с DB. Production broker не останавливался.
- HTTP503: persist retry_wait/backoff, успех после восстановления; после max attempts — terminal fallback. HTTP404 — один запрос, partial/failed, очередь продолжает работу.
- Общий HTTP deadline и extraction deadline протестированы; hung extraction process уничтожается. Concurrent claim выдаёт job только одному worker, host reservations разделяются между экземплярами.

## Безопасность

Прошли проверки unsupported schemes, URL credentials, loopback/private/link-local/multicast/reserved/mapped addresses, internal service names, host outside exact allowlist, invalid URLs, нестандартные порты, DNS public/private mixture и DNS rebinding. Запрос использует проверенный IP, исходный Host/SNI; TLS verification не отключается.

Redirect к127.0.0.1 отклонён до обращения к destination. Redirect loop ограничен. Oversized declared response отклоняется до body read; oversized streaming response прерывается, следующий job обрабатывается успешно. HTML script/style не исполняются и не попадают в body. Cookies не сохраняются в snapshot. PDF limits и subprocess cleanup проверены.

## Реальный smoke

Использованы55 уже собранных событий Stage1: Fed15, SEC25, ECB15, полученные исключительно из NATS. После обработки:

- 55 exact input payloads совпадают побайтно с NEWS_RAW;
- 55 документов и55 опубликованных output events совпадают с payloads из DOCUMENT_ENRICHED и проходят strict schema;
- 30 snapshot hashes/lengths проверены по original bytes;
- 30 ready (Fed15+ECB15),25 partial (SEC),0 pending outbox,0 invalid inputs,0 retries;
- title/categories и body_length проверены для каждого документа.

| Source | Title | RSS chars | Enriched chars | Fetch / HTTP | Content type | Method | Status |
|---|---|---:|---:|---|---|---|---|
| Fed | Federal Reserve issues FOMC statement (2026-04-29) | 37 | 2309 | success /200 | text/html | trafilatura | ready |
| SEC | SEC Announces Roundtable on Preparations for 24-Hour Trading | 254 | 254 | failed /403 | text/html | rss fallback | partial |
| ECB | Christine Lagarde: Interview with Ouest-France | 0 | 5933 | success /200 | text/html | trafilatura | ready |
| ECB PDF | Philip R. Lane: Diversity at the European Central Bank | 0 | 11620 | success /200 | application/pdf | pypdf | ready |

Fed reason rss_body_equals_title, ECB rss_body_empty, SEC rss_body_truncated. SEC full page вернул403, поэтому original body сохранён, failure_reason=http_403. Антибот не обходился. PDF smoke дополняет обязательные три источника.

URLs, document/input/output/snapshot IDs и актуальный checked_at доступны в [enrichment-smoke.json](enrichment-smoke.json). Воспроизведение проверки уже обработанных данных:

```sh
docker compose exec -T enrichment python - < scripts/enrichment-smoke.py
```

Скрипт read-only, требует имеющихся sample titles и сохранённых NATS messages. Не запускает новый fetch и не читает ingestion tables.

## Запуск и API

`docker compose up -d --build` успешно собрал и запустил MariaDB, NATS, ingestion и enrichment. Bootstrap и обе миграции завершились exit0. Оба runtime containers healthy. Enrichment `/health`: alive; `/ready`: database=true, jetstream=true, workers=true. Readiness не зависит от публичных сайтов. `/stats`, `/documents/{id}`, `/jobs/{id}`,404 для неизвестных IDs проверены. Логи после финального запуска проверены: непредвиденных worker errors/traceback нет.

## Ограничения и отклонения

1. SEC HTTP403: complete text недоступен из текущей сети. Результат явно partial, RSS не потерян.
2. Generic extraction — техническая эвристика, не доказательство смысловой полноты; не следует по ссылкам на вложенные minutes/projections. Ready не означает проверенную semantic completeness.
3. Без OCR, browser/JS, расшифровки PDF, LLM и source-specific selectors. Extraction limits:100pages/200000chars/768MiB/30s.
4. Дополнительное ограничение HTTP compression: Accept-Encoding identity; игнорирующий это сервер даёт unsupported_encoding. Это исключает неограниченную распаковку; gzip/br не поддерживаются. Допускаются только стандартные80/443 порты.
5. Один public DNS address выбирается на попытку (IPv4 предпочтительнее), автоматического failover по всем A/AAAA в одной попытке нет. Proxy environment отключён. Host limits используют синхронизированные системные часы экземпляров.
6. Crash до snapshot commit может повторить HTTP GET; после commit snapshot переиспользуется. Output at least once, downstream dedup обязателен. Unlimited retry касается доставки outbox и ожидания DB, не внешнего fetch.
7. Reference schema дополнена failure_reason/error_reason, extracted_title, library_version, attempt_count для явных причин и provenance. NEWS_RAW schema не изменена.
8. Добавлены quarantine и shared host reservation tables для poison messages и rate limiting нескольких экземпляров. Собственная logical DB создаётся отдельным bootstrap, включая существующий volume.
9. Единственное общее DB infrastructure изменение: max_allowed_packet=64M для bounded PDF snapshots до20MB с SQL escaping. Volume/data сохраняются.
10. Subprocess resource limits не являются полноценной защитной OS sandbox от неизвестных native-library vulnerabilities. Контейнер non-root. Нет HA/NATS auth/TLS, retention/archival, automatic re-enrichment/replay admin API или Prometheus infrastructure.

Полная архитектура и semantics: [content-enrichment.md](architecture/content-enrichment.md).
