# Stage 2 — Event Engine

Независимый deterministic сервис `services/events`, Python3.13/FastAPI, собственная MariaDB database `events`, API `127.0.0.1:8002`. Вход только `document.enriched.v1`, выход `event.detected.v1` и `event.updated.v1`. Нет чтения databases ingestion/enrichment, внешнего HTTP, LLM, ML или рыночной оценки.

```text
document.enriched.v1 / DOCUMENT_ENRICHED
  → durable EVENTS_V1, explicit ACK
  → schema validation → exact bytes + unique processing job → COMMIT → ACK
  → lease/token claim → Quality Gate → RuleBasedEventExtractor
  → list[EventCandidate] → taxonomy/entity validation
  → Exact correlation / fuzzy suggestion
  → [Canonical Event + event_documents + revision + outbox + completed job]
  → COMMIT → independent publisher → JetStream PubAck
  → event.detected.v1 / event.updated.v1 / EVENTS
```

## Ownership и хранение

Stage2 не импортирует код предыдущих сервисов и не читает их таблицы. Использованы те же проверенные patterns коротких SQL транзакций, lease/token, explicit ACK и outbox. Input schema копируется в container как read-only boundary. Публичные contracts Stage1/1.5 и source configurations не изменены.

| Таблица | Ответственность |
|---|---|
| event_inputs | PK document_id, exact received bytes, first input_message_id, decoded payload, SHA-256, stream sequence, received_at |
| event_jobs | UNIQUE document_id; pending/processing/retry_wait/completed/failed, outcome, attempts, lease/token, next_retry_at, last_error_type, timestamps |
| dead_inputs | exact malformed/conflicting payload, validation error path/type, subject, JetStream metadata, received_at; dedup SHA-256 |
| extraction_runs | immutable committed result, candidates JSON, quality, all versions, configuration snapshot/hash, document_id, optional UNIQUE job_id |
| event_candidates | immutable candidate payload, run_id и document_id; отдельная identity |
| events | current projection, stable UUID, UNIQUE nullable exact_event_key, current revision/type/actor |
| event_documents | many-to-many composite PK(event_id,document_id), candidate_id, primary/supporting relation, evidence metadata |
| event_revisions | immutable payload snapshots, composite PK(event_id,revision), UNIQUE message_id |
| correlation_suggestions | ordered pair PK(event_a,event_b), individual similarity facts, reason, policy hash, timestamp |
| outbox_events | stable payload/message_id/subject, UNIQUE(event_id,revision), publish attempts/backoff/lease |

Нет foreign keys в другие databases. `events-bootstrap` создаёт database/user на существующем или пустом volume; runtime не получает root credentials. Собственная frozen migration `v20001` не импортирует изменяемые app models. Runtime UID10003. Bootstrap не меняет пароль уже существующего DB user.

## Input и jobs

Identity — **document_id**, не transport message_id. Дубликат не создаёт второй job/run/candidate/event/revision/outbox. Тот же документ с новым transport message_id считается дубликатом; первая точная последовательность bytes сохраняется. Другая content/metadata при том же document_id — identity conflict в dead_inputs, исходный документ не перезаписывается.

Input в одной транзакции создаёт event_inputs/event_jobs. ACK происходит только после commit. Crash до commit приводит к redelivery; crash после commit до ACK — безопасный duplicate. Malformed/schema-invalid/duplicate-key/NaN/invalid Unicode JSON сохраняется в quarantine перед ACK. При недоступности БД — NAK delay5s, без ACK.

Worker claim: FOR UPDATE SKIP LOCKED, lease120s и UUID token. Извлечение вне DB transaction через thread; текущие правила используют bounded title/URL, не выполняют body NLP. Canonical transaction повторно проверяет token/status/expiry. Stale worker не может завершить новый lease.

Одна canonical transaction сохраняет run/candidates/events/relations/revisions/outbox/job outcome. Ошибка откатывает весь набор. Попытки processing ограничены3; retry2s ×2^(attempt−1)+jitter, cap300s. После исчерпания — failed job и failed extraction run с версиями/configuration; следующие документы не блокируются. DB outage может задержать фиксацию failure до восстановления инфраструктуры. Cancellation/crash оставляют lease для reclaim.

Outcomes документа: event_created, event_correlated, no_event, failed. При нескольких candidates summary=event_created, если хотя бы один event создан; детализация по каждому candidate хранится в result_json. Конкретный production extractor v1 возвращает максимум один candidate, interface и core поддерживают список (до32 за batch). Два candidates одного документа для одного exact event сохраняются, но relation/revision добавляется один раз.

## Taxonomy и entity registry

`config/events/taxonomy.v1.yaml`, version1.0:

- central_bank.policy_statement, central_bank.minutes, central_bank.projections, central_bank.speech, central_bank.interview, central_bank.data_release, central_bank.other;
- regulator.rule_proposal, regulator.rule_adoption, regulator.guidance, regulator.enforcement, regulator.meeting, regulator.report, regulator.personnel, regulator.other;
- unknown.

Topics: monetary_policy, interest_rates, inflation, wages, employment, economic_growth, financial_stability, capital_markets, market_structure, regulation, enforcement, banking, payments, digital_assets.

`entities.v1.yaml`, version1.0: organization:federal_reserve (Federal Reserve), organization:sec (Securities and Exchange Commission), organization:ecb (European Central Bank). Jurisdictions US/EU. Источник→issuer/jurisdiction/fallback находится в отдельном Stage2 `sources.yaml`, version1.0.

Canonical actors берутся только из registry. Extracted person из `Name: title` становится unresolved с null entity_id, пока registry не содержит person или alias. Для combined names через запятую/and v1 не создаёт ложного единого person. Новые unknown sources получают unknown event без придуманного issuer/jurisdiction.

Config validation проверяет версии, уникальность vocabulary/rule IDs, enum references, regex syntax, issuer/source/jurisdiction references, alias ambiguity. Полный config snapshot и SHA-256 сохранены у каждого run; изменение файла без version bump всё равно обнаружимо по hash. Version bump при изменении правил обязателен операционно.

## Rules и quality

Rules находятся в `config/events/rules/core.yaml`, version1.0. Generic engine сортирует priority descending, затем rule ID ascending для воспроизводимого tie-break. Source condition AND (любой title regex OR любой URL regex). Первый rule определяет v1 candidate. Body keywords не добавляют topics автоматически.

| Rule | Условие | Event type | Topics |
|---|---|---|---|
| fed.fomc_statement | FOMC statement | central_bank.policy_statement | monetary_policy, interest_rates |
| fed.minutes | Minutes | central_bank.minutes | monetary_policy |
| fed.projections | economic projections | central_bank.projections | monetary_policy, economic_growth |
| ecb.interview | Interview OR /press/inter/ | central_bank.interview | — |
| ecb.policy_statement | Monetary policy decisions/statement | central_bank.policy_statement | monetary_policy, interest_rates |
| ecb.wage_tracker | wage tracker | central_bank.data_release | wages |
| ecb.speech | /press/key/ | central_bank.speech | — |
| sec.rule_proposal | Proposes | regulator.rule_proposal | regulation |
| sec.rule_adoption | Adopts / Final Rule | regulator.rule_adoption | regulation |
| sec.guidance | Updates FAQs / Guidance | regulator.guidance | regulation |
| sec.enforcement | Charges / Enforcement / Settles | regulator.enforcement | enforcement |
| sec.meeting | Meeting / Roundtable | regulator.meeting | capital_markets |
| sec.report | Report | regulator.report | capital_markets |
| sec.personnel | Departure / Appoints / Names | regulator.personnel | — |

Interview priority400 выше generic speech200. SEC priorities отражены в YAML; complex titles с несколькими cues получают первый configured rule, что не является semantic truth. Exact_rule означает конкретное правило классификации, **не** разрешение exact correlation. Speech URL/report/personnel помечены heuristic_rule. Без match — source fallback central_bank.other/regulator.other, иначе unknown, basis=fallback. Confidence/probability отсутствуют.

Quality settings в sources.yaml: usable title≥8 символов либо body≥80 с alphanumeric content; high — ready и body≥500, body не равен title; medium — partial и meaningful body≥80, не title-only; остальные usable cases low. Failed/rejected с usable title не теряются. Нет usable title/body — no_event без candidate/canonical output. Blank title при usable body остаётся blank canonical_title, не генерируется summary.

Canonical title — исходный title после NFC/whitespace normalization. Дополнительный extracted_title не заменяет его. Evidence quality — техническая шкала качества доступного документа, не confidence события или торговой оценки.

## Event time и identity

published_at **не** подставляется в event_time. Отдельно хранятся earliest/latest_source_published_at, first_detected_at, last_updated_at. Nullable publication timestamps корректно агрегируются по реальному UTC времени.

V1 извлекает только очевидную дату из title, прошедшего configured identity matcher: English Month day[, ]year; Month day–day[, ]year; ISO YYYY-MM-DD. Несколько дат, невозможная дата, отсутствующий год — unknown. Из URL год/дата не выводятся. В актуальных projections title нет года, поэтому event_time остаётся null.

Precision enum: exact, minute, hour, date, date_range, unknown. V1 реально создаёт date/date_range/unknown. Date range — явная ISO строка `YYYY-MM-DD/YYYY-MM-DD`, обе даты существуют и start≤end. Exact/minute/hour предусмотрены schema для будущих extractors; v1 их не выдаёт. Source=title или not_extracted (body зарезервирован).

Exact key = SHA-256 canonical JSON `{type,actor,time,precision,namespace}`. Требуются canonical issuer, явная date/date_range и configured event-specific namespace. V1 namespace `fomc.meeting` разрешён только при отдельном identity_title_regex для FOMC statement, Federal Open Market Committee minutes, FOMC economic projections. Тип входит в ключ: statement и projections одной встречи не объединятся. Namespace нельзя переиспользовать для другого смысла при будущей смене rules.

Без exact key каждый документ создаёт отдельный event даже при одинаковом title. Это осознанная политика missed merge предпочтительнее false merge. UNIQUE(exact_event_key), insert-on-conflict и row lock сериализуют concurrent candidates. Revision увеличивается под lock, все связанные записи коммитятся атомарно.

## Suggestions, lifecycle, revisions

Fuzzy matching никогда не merge. Сравниваются одинаковые event type, canonical primary actor, jurisdiction; явно различные extracted event times отсекаются. Token Jaccard title после casefold/tokenization/удаления небольшого списка служебных слов ≥0.7 и source-publication proximity≤7days. Publication time здесь только filter для suggestion, не event time. Неизвестная publication date — suggestion не создаётся. Сохраняются same_event_type/same_primary_actor/title_similarity/time_distance_seconds/time_distance_basis/reason/config hash. Нет overall probability.

Поиск ограничен500 recent events того же type/actor (configurable), выполняется при создании нового event. Concurrent незакоммиченные события могут не получить suggestion; нет фонового global rescan. Это не влияет на exact correlation. PK упорядоченной пары не допускает duplicate suggestions.

Первый committed document — primary; exact supporting document — supporting. Schema допускает update/duplicate для будущих policies. Primary title/classification/actors/provenance сохраняются; новое evidence и source timestamps входят в следующую revision. Supporting extraction имеет собственные версии/configuration/run ID, доступные через relation.

Lifecycle detected при одном source.id; corroborated при≥2 различных source.id, подтверждающих тот же exact key. Два документа одного source не corroboration. Evidence quality агрегируется как максимум deterministic quality среди документов. Это не независимая статистическая оценка и не проверка фактического владения источниками.

Event UUID стабилен; каждый committed change получает новую revision и новый message_id. Первая revision=1/change_type=created → event.detected.v1; следующие updated → event.updated.v1. Event revisions никогда не заменяются. Current projection может быть восстановлена из последней revision.

## Contract и доставка

Оба subjects используют `contracts/event/canonical/v1.schema.json`. Строгая Draft2020-12, additionalProperties=false, versioned controlled event types/topics, required nested groups, UUID/date-time/date, явные null/status/precision. Структура повторяет reference: schema_version/message_id/event/taxonomy/content/actors/jurisdictions/time/lifecycle/evidence/extraction/correlation.

Дополнения: entity_registry_version/configuration_hash/core_version; evidence.input_message_id (enriched message) отдельно от source_message_id (original news); evidence quality и extraction_run_id. Full body не копируется. Application validator дополнительно проверяет уникальные evidence document IDs, counts, lifecycle, единственный primary и календарный date range. Payload≤1MB, до1000 evidence documents; превышение приводит к failed processing run без частичного canonical commit.

Input stream DOCUMENT_ENRICHED только читается; configuration не изменяется. Durable EVENTS_V1: DeliverAll, explicit ACK, ack_wait30s, max_ack_pending128, unlimited redelivery при DB outage. Output stream EVENTS: exact subjects event.detected.v1/event.updated.v1, FILE, one replica, max1GiB, DiscardNew, max_msg_size1MB, duplicate_window24h. Nats-Msg-Id/message_id и Expected-Stream защищают retries/маршрут.

Outbox publisher имеет lease60s/deadline15s/backoff+jitter до300s. NATS outage не создаёт новую revision; retries используют тот же payload/message_id. Для одного event следующая revision ждёт published предыдущих, включая ожидание исправления dead revision. Разные events не блокируют друг друга. Contract-invalid persisted payload становится dead.

Delivery at least once: после PubAck и до DB mark published возможна повторная доставка, особенно за пределами duplicate window. Downstream обязан дедуплицировать message_id и учитывать event.revision; JetStream не обещается global exactly-once.

## Research extension

EventExtractor Protocol возвращает list[EventCandidate], имеет name/version. Он не владеет canonical storage, correlation или publisher. RuleBasedEventExtractor — единственная production реализация. Новый extractor использует тот же Event Core и schema.

Нормальная обработка создаёт один run/job. `extraction_runs.document_id` не UNIQUE; nullable job_id позволяет отдельным research runs сравнивать разные extractors/versions с теми же exact input bytes без перезаписи предыдущего run и без auto-publication. Автоматический research/reprocessing endpoint не реализован. Изменение rules не переобрабатывает completed jobs.

## API и запуск

`docker compose up --build -d`: MariaDB, NATS, ingestion:8000, enrichment:8001, events:8002; bootstrap/migrations автоматически. Runtime endpoints только loopback:

- GET /health — процесс жив;
- GET /ready — DB/migration v20001, NATS streams, живость фоновых tasks; без сайтов/LLM;
- GET /stats — documents/outcomes, events by type, unknown, correlations/suggestions, pending/failed/dead counts;
- GET /events/{id} — current projection;
- GET /events/{id}/revisions — snapshots, limit≤100/offset;
- GET /documents/{id}/extraction — job state и extraction runs/provenance/results;
- GET /correlation-suggestions — read-only, limit≤100/offset.

Логи JSON связывают source/document/job/candidate/event/revision/outbox/message IDs, rule IDs, correlation method, duration и error type. Body не логируется.

Environment: EVENTS_DATABASE_URL, EVENTS_NATS_URL, EVENTS_CONFIG_DIR, EVENTS_INPUT_SCHEMA_PATH, EVENTS_OUTPUT_SCHEMA_PATH, EVENTS_DURABLE_NAME=EVENTS_V1, EVENTS_WORKERS_ENABLED=true, EVENTS_LEASE_SECONDS=120, EVENTS_MAX_ATTEMPTS=3, EVENTS_RETRY_BASE_SECONDS=2. Compose подставляет EVENTS_DB_PASSWORD и EVENTS_PORT из .env; прочее через service environment/override. Quality/correlation thresholds в versioned sources.yaml включены в config hash.

Новая rule: измените YAML с уникальным ID/priority/matchers и controlled output; добавьте positive/negative/priority tests, bump ruleset version, restart events. Новый type/topic требует согласованного taxonomy/schema version и downstream review. Trusted regex configuration не должна содержать патологические backtracking patterns; runtime v1 не использует пользовательские regex из документа.

## Ограничения

Нет LLM/ML, semantic understanding, sentiment, market impact, confidence, trading, UI. Англоязычные title/URL rules ограничены заданными authority feeds. Источники с похожими заголовками могут остаться отдельными events. Люди преимущественно unresolved. Неполные SEC RSS дают medium evidence, generic enrichment ready не гарантирует фактическую полноту. Нет administrative merge/replay, retrospective global fuzzy scan, automatic retention, HA или NATS auth/TLS. Контролируйте размер DB/stream; при заполнении EVENTS новые outbox records остаются pending.

Тесты/реальный smoke/примеры: [отчёт](../events-verification.md), [машиночитаемый smoke](../events-smoke.json).
