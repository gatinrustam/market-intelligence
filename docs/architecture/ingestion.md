# Stage 1: решения и границы

```text
Source
  ↓ HTTP: timeout, bounded body, transient retry
SourceAdapter.fetch() → FetchResult(bytes, received_at, content_type)
  ↓
Raw Store ─────────────────────┐
  ↓                           │ MariaDB transaction per fetch
RSS parser → Normalizer       │
  ↓                           │
news.raw.v1 validation        ├→ malformed: failed_items + raw reference
  ↓                           │
Dedup UNIQUE (savepoint/item)  ├→ duplicate: raw retained, no new event
  ↓                           │
news_items + outbox_events ────┘
  ↓ COMMIT
Outbox claim transaction → lease/token → COMMIT
  ↓
NATS JetStream publish + PubAck (outside DB transaction)
  ↓
Conditional published UPDATE by lease token
```

## Контракт и расширение

`news.raw.v1` — независимая публичная граница. Сервисы не должны читать внутренние ORM модели. Schema является опубликованным артефактом и валидируется перед записью и перед публикацией. Для эволюции с несовместимыми изменениями нужен новый subject/schema version. Не добавляйте необязательные поля v1 без проверки совместимости: strict consumers могут отвергнуть их.

`SourceAdapter` отвечает за I/O и healthcheck. Он не содержит semantic classification, LLM/торговой логики. Текущий FetchResult ориентирован на пакетный HTTP ответ; для streaming adapters может понадобиться новый внутренний envelope, но публичный контракт останется тем же. Registry/factory для новых типов добавляется в composition root; конфигурация намеренно отвергает ещё не поддерживаемые типы.

## Атомарность и raw

Raw payload — точный документ после HTTP decompression, не сериализация feedparser. Один raw ID на fetch, а не копия большого XML для каждой новости. News хранит raw reference и item_index. Raw, accepted news и outbox коммитятся вместе. На bad feed коммитится raw + failed record. Этот вариант уточняет требование per-item pipeline и избегает N копий feed; кратковременная инфраструктурная ошибка откатывает весь fetch, который повторяется poller.

Сырые данные не включают Authorization/Cookie/response headers. Полный HTTP wire dump не нужен. Ограничение fetch body защищает память; source definitions — доверенная конфигурация оператора, не пользовательский HTTP endpoint.

## Дедупликация и спорные случаи

Используется OR двух уникальных identity: stable provider ID и canonical content hash. Scope — source_id. Hash включает normalized content, canonicalized URL и publication date, но не receive time. Одинаковые заголовки разных Fed релизов не объединяются. Отсутствующая дата и GUID не заменяются выдуманными значениями. URL fallback не подменяет external ID.

Same GUID + changed text сохраняет только исходную нормализованную новость; исправленный текст доступен в новом raw. Same text + different URL/date — разные релизы. Межисточниковая/семантическая дедупликация относится к будущему Event Engine. SHA-256 external identity упрощает безопасный индекс длинных и case-sensitive GUID.

## Crash matrix

| Момент сбоя | После restart |
|---|---|
| До COMMIT ingestion | Транзакция откатится, следующий fetch повторяет |
| После COMMIT, до claim | Pending сохраняется |
| После claim, до publish | Lease истекает через 60 сек |
| NATS отказал | Pending + сохранённый backoff |
| PubAck получен, DB update не выполнен | Повтор с тем же message_id; NATS dedup в пределах 24 ч |
| Истёк lease, старый worker вернулся | Token check запрещает stale UPDATE |
| Невалидный outbox payload | Dead, не блокирует другие записи |

Transactional outbox не устраняет окно повторной доставки после PubAck. Никакие future consumers здесь не реализованы. При внедрении consumer нужен durable subscription и идемпотентный обработчик message_id.

## Локальная эксплуатация

MariaDB InnoDB и JetStream file storage имеют persistent Docker volumes. NATS один узел, без обещаний отказоустойчивости. Stream full не удаляет старые события автоматически (`DiscardNew`). DB/outbox не очищаются автоматически. Outbox workers можно дублировать; poll workers пока не имеют распределённого лидерства. Источники независимы, их runtime status в памяти.

Проверенные API: [SQLAlchemy MariaDB](https://docs.sqlalchemy.org/en/20/dialects/mysql.html), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [JetStream headers](https://docs.nats.io/nats-concepts/jetstream/headers). Версии библиотек проверены в PyPI 2026-09-19. Каталоги RSS: [Fed](https://www.federalreserve.gov/feeds/feeds.htm), [SEC](https://www.sec.gov/about/rss-feeds), [ECB](https://www.ecb.europa.eu/home/html/rss.en.html).
