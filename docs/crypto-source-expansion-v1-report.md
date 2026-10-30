# Crypto Source Expansion v1 — отчёт

Срез: 2026-09-20T17:51:26.114968+00:00. Все материалы — реальные официальные ответы; выборка историческая. LLM и платные API не вызывались.

## Статус

Реализованы адаптеры, конфигурации, versioned DI/ontology/router, lifecycle identity и фильтры Dashboard. Полный Definition of Done **не закрыт**: Binance недоступен из текущей среды, SEC блокирует тексты filings, Coinbase блокирует текущий Docker collector. Наличие записей в корпусе не означает наличие полного текста или подтверждённого финансового факта.

## Источники и точные endpoints

| Source ID | Adapter / формат | Интервал | URL |
|---|---|---:|---|
| binance_delistings | announcement_page / binance | 30 s | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=161&pageNo=1&pageSize=20 |
| binance_listings | announcement_page / binance | 30 s | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20 |
| binance_maintenance | announcement_page / binance | 30 s | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=157&pageNo=1&pageSize=20 |
| binance_news | announcement_page / binance | 300 s | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=49&pageNo=1&pageSize=20 |
| circle_pressroom | announcement_page / circle | 300 s | https://www.circle.com/pressroom |
| coinbase_blog | announcement_page / coinbase | 300 s | https://www.coinbase.com/blog |
| kraken_status_incidents | statuspage / incidents | 30 s | https://status.kraken.com/api/v2/incidents.json |
| kraken_status_maintenance | statuspage / scheduled_maintenances | 30 s | https://status.kraken.com/api/v2/scheduled-maintenances.json |
| sec_strategy_8k | sec_filing / — | 300 s | https://data.sec.gov/submissions/CIK0001050446.json |
| tether_news | rss / — | 300 s | https://tether.io/feed/ |

Исторические дополнительные страницы: https://tether.io/feed/?paged=2 и https://www.circle.com/pressroom?29c9664d_page=2. SEC filing URL строится из CIK, accession без дефисов и primaryDocument: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}/{primaryDocument}`.

Каждый новый source имеет domain=crypto, source_quality=official_primary, source_class, source_role, poll_priority, language=en и expected_content_types. Быстрые источники опрашиваются независимо; при ошибке действует существующий backoff до 1800 секунд. Непроверенные в live Binance endpoints не объявляются исправными.

## Корпус

| Группа | Raw observations | Требование | Ограничение |
|---|---:|---:|---|
| Binance | 0 | 20 | ConnectError; реальных Binance items нет |
| Kraken | 92 | 10 | 13 incident IDs + 13 maintenance IDs; обновления не считаются отдельными underlying events |
| Coinbase | 10 | 10 | Официальные карточки/summary; full article fetch из Docker — 403 |
| Tether | 10 | 10 | RSS, включая вторую историческую страницу |
| Circle | 10 | 10 | Две страницы официального pressroom |
| Strategy | 10 | 10 | 10 реальных 8-K metadata; HTML filings — 403, BTC facts не заявляются |

Всего raw observations: **132**. Маршрутизировано уникальных документов: **131**. Semantic outputs, совпадающие с актуальным DI input: **74**. Дефицит Binance не компенсируется числом lifecycle updates Kraken.

## Распределение

Source/category labels могут пересекаться; это происхождение и назначение источника, а не доказательство финансового события:
- exchange: 101
- incidents: 91
- stablecoin: 20
- corporate_treasury: 10
- institutional: 10
- infrastructure: 101
- security: 0

Принятые semantic concepts (только завершённые результаты актуального DI; группы могут пересекаться):
- listings: 2
- delistings: 0
- incidents: 0
- stablecoin: 6
- treasury: 0
- institutional: 4
- promotional hint: 0; Binance noise проверен fixtures, а не вымышленным real smoke.

## Required example Article Insights

Пустой facts/assets — честное отсутствие подтверждения. Semantic candidates не заменяют точные DI facts. Числа similarity не являются вероятностями.

### Kraken funding/withdrawal

- Source: kraken_status_incidents
- Title: Funding delays for select blockchain networks
- Published: 2026-09-18T11:45:18+00:00
- URL: https://status.kraken.com/incidents/074rbtn08wzw
- Article type: unknown
- Enrichment: {"status": "partial", "required": false, "reason": "policy_never", "failure_reason": "insufficient_rss_content"}
- Extracted entities: []
- Facts: []
- Measurements: []
- Semantic concepts: []
- Affected assets: []
- Article route: review
- Semantic suggested route (research): low
- Why it matters / basis: ["No decisive rule; conservative review", "Incomplete/unsupported evidence remains visible to reviewers; source prestige does not repair document quality", "Explicit action and accepted substantive event theme", "Research only; production router unchanged"]
- Audit: document `6abc66c6-250b-4665-96b7-31dce0558a0c`, DI `6ee7e4bb-ec33-5049-88fe-59533aac4698`, routing `d73132b6-d1bc-5930-aadc-b9dd06a484d7`.

### Coinbase derivatives

- Source: coinbase_blog
- Title: Coinbase Brings Global Crypto Derivatives to US Market
- Published: 2026-05-29T00:00:00+00:00
- URL: https://www.coinbase.com/blog/coinbase-brings-global-crypto-derivatives-to-us-market
- Article type: нет завершённого актуального semantic result
- Enrichment: {"status": "partial", "required": true, "reason": "policy_always", "failure_reason": "http_403"}
- Extracted entities: ["Coinbase", "US"]
- Facts: []
- Measurements: []
- Semantic concepts: []
- Affected assets: []
- Article route: review
- Why it matters / basis: ["No decisive rule; conservative review", "Incomplete/unsupported evidence remains visible to reviewers; source prestige does not repair document quality"]
- Audit: document `c6ef4c0a-99e5-4eb6-b78e-3cbf333ee8ea`, DI `68d97c4b-fe83-5d3d-b20d-61faa30cfffa`, routing `bb0345f4-4093-5345-8d60-29ea6b6f40c8`.

### Tether stablecoin infrastructure

- Source: tether_news
- Title: Tether and Fasanara Capital Launch $400 Million Private Credit Fund to Expand Stablecoin-Enabled Real-Economy Lending
- Published: 2026-09-09T12:00:00+00:00
- URL: https://tether.io/news/tether-and-fasanara-capital-launch-400-million-private-credit-fund-to-expand-stablecoin-enabled-real-economy-lending/
- Article type: нет завершённого актуального semantic result
- Enrichment: {"status": "ready", "required": false, "reason": "rss_body_sufficient", "failure_reason": null}
- Extracted entities: ["Advisor", "Fasanara", "Fasanara Capital", "Fasanara Capital Fasanara Capital", "Fasanara’s", "Francesco Filia", "London", "Originator", "Paolo Ardoino", "SME", "StableFund", "Tether", "USD"]
- Facts: [{"fact_type": "crypto.stablecoin_change", "action": "announce_product", "fact_id": "c79a6c73-8386-539f-b59f-858a266d28fa", "evidence_offsets": [0, 246]}]
- Measurements: [{"kind": "money", "value": "400000000", "min": null, "max": null, "unit": "USD", "currency": "USD"}, {"kind": "money", "value": "3000000000", "min": null, "max": null, "unit": "USD", "currency": "USD"}, {"kind": "money", "value": "3", "min": null, "max": null, "unit": "USD", "currency": "USD"}, {"kind": "money", "value": "5", "min": null, "max": null, "unit": "USD", "currency": "USD"}, {"kind": "money", "value": "5.7", "min": null, "max": null, "unit": "USD", "currency": "USD"}, {"kind": "money", "value": "6000000000", "min": null, "max": null, "unit": "USD", "currency": "USD"}]
- Semantic concepts: []
- Affected assets: []
- Article route: important
- Why it matters / basis: ["Explicit evidenced crypto product, exchange or corporate treasury fact"]
- Audit: document `05a5f8e5-b1cc-461c-b4c2-fa8a0562b44b`, DI `0aaa22d2-7366-5575-bca6-05e2eb98c4ff`, routing `080d31a5-cac3-549c-94ed-05350c079eb6`.

### Circle infrastructure

- Source: circle_pressroom
- Title: Circle Launches Arc Mainnet, an Economic Operating System for the Internet
- Published: 2026-09-16T00:00:00+00:00
- URL: https://www.circle.com/pressroom/circle-launches-arc-mainnet-an-economic-operating-system-for-the-internet
- Article type: нет завершённого актуального semantic result
- Enrichment: {"status": "ready", "required": true, "reason": "policy_always", "failure_reason": null}
- Extracted entities: ["AI", "APAC", "ARC", "AUDF", "Aave Labs", "Aero", "Alchemy", "Alethieum", "Arc", "BCW", "BRLA", "BTG Pactual", "Bankr", "Binance", "BitGo", "Bitget Wallet", "Bitso", "Bitwise", "BlackRock", "BlockRun", "Blockdaemon", "CADD", "CHFAU", "CRCL", "Ceffu, Copper, Fireblocks", "Centrifuge", "Chainlink, Figment", "Circle", "Co-Founder", "Co-Founder of", "Coinbase", "Cumberland", "DeFi", "Digital", "Digital Assets", "Digital Garage", "Dinari", "Doppler", "EURAU", "EURC", "Earth", "FX", "Founder", "Gate", "Gauntlet", "Global Head", "Global Payments", "Goldsky", "HSBC", "Hibachi", "JCB", "JPYC", "JPYSC", "Janus Henderson", "Japan", "Jeremy Allaire", "KRW1", "Kaleido", "Keyrock", "Kraken", "KuCoin", "L1", "LLC", "Lead Bank", "Ledger", "MXNB", "Maple, Matrixdock", "Mastercard", "Merlin Egalite", "Michael Blaugrund", "MoneyGram", "Morpho", "NEW YORK", "NYSE", "New York Life Investment Management", "OKX", "OKX Wallet", "OSL", "Onchain", "Ornn", "Orthogonal", "Phantom", "President & CEO", "ProShares", "Proof of Authority", "QCAD", "Quicknode", "Rainbow", "Robbie Mitchnick", "SBI APAC Digital Economic Zone", "SBI Group", "SBI Holdings", "SBI Shinsei Trust", "SBI VC Trade", "SDK", "SEC", "SEKAU", "Securitize", "Societe Generale", "Stack", "Standard Chartered", "Stani Kulechov", "Steakhouse Financial", "Sumitomo Corporation", "TRYB", "The Depository Trust & Clearing Corporation", "Thunes", "Trust Wallet", "USDC", "USYC", "Uniswap", "United States", "Upbit", "VP", "Visa", "Wenia", "Worldpay", "Yoshitaka Kitao", "ZARU", "Zodia Custody", "cirBTC", "the Agentic Economic Era", "the New York State Department of Financial Services", "the Private Securities Litigation Reform Act", "treasury", "wBRL", "wCLP", "wMXN", "xStocks"]
- Facts: []
- Measurements: [{"kind": "money", "value": "74000000000", "min": null, "max": null, "unit": "USD", "currency": "USD"}, {"kind": "percentage", "value": "98.8", "min": null, "max": null, "unit": "percent", "currency": null}]
- Semantic concepts: []
- Affected assets: []
- Article route: review
- Why it matters / basis: ["No decisive rule; conservative review"]
- Audit: document `c143a322-0112-43b6-acc6-8552d4436786`, DI `8d287369-4232-5bd7-b83b-4d0d9b849a39`, routing `54002655-1f3f-5971-be06-315633b07074`.

### Strategy filing

- Source: sec_strategy_8k
- Title: Strategy — 8-K — 2026-09-14
- Published: 2026-09-14T12:00:16+00:00
- URL: https://www.sec.gov/Archives/edgar/data/1050446/000119312526389858/mstr-20260914.htm
- Article type: нет завершённого актуального semantic result
- Enrichment: {"status": "failed", "required": true, "reason": "policy_always", "failure_reason": "http_403"}
- Extracted entities: []
- Facts: []
- Measurements: []
- Semantic concepts: []
- Affected assets: []
- Article route: review
- Why it matters / basis: ["No decisive rule; conservative review", "Incomplete/unsupported evidence remains visible to reviewers; source prestige does not repair document quality"]
- Audit: document `4aa6c175-f18d-46c8-90f5-7527fbf31896`, DI `9101afac-293f-5e95-9727-cee71c08688d`, routing `26f7b00a-6624-5fc3-839f-92cfc9b0ffe9`.

### Binance listing и delisting/maintenance

Не подтверждены real smoke: официальный endpoint сбрасывает соединение. API parser, malformed/empty catalogue, promotional hint и standard news.raw.v1 boundary проверены тестами. Поисковые сниппеты и вымышленные публикации не подставлялись.

### Strategy BTC acquisition/sale/holdings

Metadata 8-K подтверждены, но финансовое содержание недоступно из-за SEC 403. Поэтому реальные BTC acquired/sold/holdings не утверждаются. Пример 520 BTC / $34.9m / $67,068 — **unit fixture**, не реальный filing этого smoke. Проверено точное извлечение 520 / 34900000 / 67068 и отказ от вычисления отсутствующей средней цены.

## Тесты и failure isolation

| Suite | Passed |
|---|---:|
| enrichment-tests | 95 |
| evaluation-tests | 46 |
| event-intelligence-tests | 24 |
| events-tests | 103 |
| llm-analysis-tests | 60 |
| market-context-tests | 105 |
| market-data-tests | 56 |
| document-intelligence | 59 |
| article-router | 30 |
| article-semantic | 64 |
| event-research | 58 |
| ingestion-final | 51 |
| dashboard | 63 |

Всего: 814 passed. Наборы запускались в отдельных тестовых БД/NATS; рабочие сервисы Stage 2–5 не запускались. Проверены duplicate delivery, restart persistence, lifecycle replay и изменение только статуса, malformed/403/oversize transport, retry/outbox после NATS failure и source isolation. Production NATS не отключался ради fault injection.

Bootstrap replay: 0 created, 0 failed на повторном импорте всех восьми захваченных ответов; реальные суммы duplicates и SHA-256 находятся в `bootstrap-manifest.json`. Live: Binance/Coinbase failed одновременно с healthy Kraken/Tether/Circle/EDGAR, что подтверждает отсутствие глобальной блокировки collector.

## Версии и воспроизводимость

- news.raw.v1 и document.enriched.v1 не изменены.
- DI: `rules.crypto.v1.1.json`, ruleset `crypto_v1_1`, entity registry `crypto_v1`. Предыдущая crypto_v1 сохранена для audit; исправлено ложное Arc/Research совпадение.
- Ontology: `semantic_ontology_crypto_v1`; существующие concepts сохранены без изменения, новые описания EN/RU добавлены отдельно.
- Semantic final policy: `semantic_crypto_v1_1`; model revisions и weights не изменены. Для исправленных DI inputs допускается reuse уже сохранённого inference только при совпадении document ID, body hash, sentence boundaries, языка и всей semantic-конфигурации. Ссылка находится в immutable snapshot `inference_reused_from`; performance относится к исходному измерению inference.
- Router/high-value registry: `crypto_v1`. Promotions получают `content_hint:promotional` через существующий generic categories path и archive приоритетнее high-value rules.
- Incident key: `incident/{incident_id}/update/{update_id}/{revision_hash}`. В read-only catalogue отдельно доступен `incident_id`; исходные updates и raw JSON сохранены. Новые canonical events здесь не создаются; correlation может использовать общий ключ.

## Dashboard

News Feed: Crypto, Exchange, Stablecoin, Corporate Treasury, Institutional, Incidents; source badges Binance/Kraken/Coinbase/Tether/Circle/Strategy / SEC. Sources строится из collector registry и показывает новые источники и ошибки. Новый интерфейс не создавался. Для увеличившегося каталога убрано чтение полных DI/body snapshots при запросе списка; страницы читают только необходимые JSON-поля.

## Failures, ресурсы и ограничения
- binance_delistings: failed; ConnectError.
- binance_listings: failed; ConnectError.
- binance_maintenance: failed; ConnectError.
- binance_news: failed; ConnectError.
- circle_pressroom: healthy; без ошибки.
- coinbase_blog: failed; HTTPStatusError.
- kraken_status_incidents: healthy; без ошибки.
- kraken_status_maintenance: healthy; без ошибки.
- sec_strategy_8k: healthy; без ошибки.
- tether_news: healthy; без ошибки.
- Coinbase: live Docker HTTP 403; десять карточек получены обычным HTTP с хоста и сохранены с точной provenance. Полные статьи не выдаются за доступные.
- Strategy: submissions API healthy, HTML archive 403; результаты enrichment failed и DI unsupported сохраняются, missing numbers не заполняются.
- Kraken: короткие complete API updates могут получать conservative partial по существующей sufficiency policy; текущая HTML incident page намеренно не подмешивается к старому lifecycle update.
- Coinbase/Circle карточки содержат дату без времени: midnight UTC — нормализация даты, category `publication_precision:day` явно отмечает гранулярность. Это не подтверждённое точное время публикации и не доказательство intraday availability.
- SEC table extraction консервативен: однозначные подписанные BTC/aggregate/average values с exact spans; повторяющиеся колонки, неоднозначные субъекты и гипотетические примеры не повышаются в structured fact.
- Semantic CPU worker: около 2.0–2.2 GiB RSS; DI около 520 MiB. Docker VM ограничена 3.825 GiB. Одновременные NLP-проверки/replays привели к перезапускам и одному killed helper (137); DI временно приостанавливался после завершения пересчёта, потерянные leases прежних процессов освобождены без изменения результатов. Параллельных model workers не добавлялось.
- Короткие updates: примерно 3–9 s inference; крупные статьи в измеренных результатах — до ~139 s. Платных API costs: 0.
- Kraken history JSON ~0.7 MB на два ответа. При хранении каждого raw poll каждые 30 s это порядка 2 GB/day до компрессии/retention; transport/output dedup не является raw-retention policy. Старый audit не удалялся.
- Для локального deployment использованы новые исходники поверх существующих образов с теми же pinned зависимостями: повторная загрузка spaCy при обычной сборке была слишком медленной. Dockerfiles/зависимости проекта не изменялись.

## Что теперь видно в потоке

Ранее отсутствовавшие классы реальных материалов: Kraken funding/withdrawal/network incidents и maintenance lifecycle, Coinbase crypto derivatives/institutional products, Tether stablecoin-backed lending infrastructure, Circle Arc/USDC minting-redemption/institutional integration announcements, company-specific Strategy 8-K metadata. Binance articles и финансовое содержание закрытых SEC filings по-прежнему не доступны; это отражено как failure, а не скрыто как успешное подключение.
