"""Render the requested research report from captured real pipeline evidence."""
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'datasets/crypto-source-expansion-v1'
d=json.loads((folder/'observed-pipeline.json').read_text());tests=json.loads((folder/'tests.json').read_text())
sem={x['document']['intelligence_id']:x for x in d['semantic_outputs']}
articles=d['articles'];out=[]
def line(s=''):out.append(s)
def j(x):return json.dumps(x,ensure_ascii=False)
line('# Crypto Source Expansion v1 — отчёт')
line();line('Срез: '+d['captured_at']+'. Все материалы — реальные официальные ответы; выборка историческая. LLM и платные API не вызывались.')
line();line('## Статус')
line();line('Реализованы адаптеры, конфигурации, versioned DI/ontology/router, lifecycle identity и фильтры Dashboard. Полный Definition of Done **не закрыт**: Binance недоступен из текущей среды, SEC блокирует тексты filings, Coinbase блокирует текущий Docker collector. Наличие записей в корпусе не означает наличие полного текста или подтверждённого финансового факта.')
line();line('## Источники и точные endpoints')
line();line('| Source ID | Adapter / формат | Интервал | URL |');line('|---|---|---:|---|')
configs=[]
for p in sorted((ROOT/'config/sources').glob('*.yaml')):
 if p.stem.startswith(('binance','kraken','coinbase','tether','circle','sec_strategy')):configs.append(json.loads(p.read_text()))
for s in configs:line(f"| {s['id']} | {s['connector']['type']} / {s['connector'].get('format','—')} | {s['poll']['interval_seconds']} s | {s['connector']['url']} |")
line();line('Исторические дополнительные страницы: https://tether.io/feed/?paged=2 и https://www.circle.com/pressroom?29c9664d_page=2. SEC filing URL строится из CIK, accession без дефисов и primaryDocument: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}/{primaryDocument}`.')
line();line('Каждый новый source имеет domain=crypto, source_quality=official_primary, source_class, source_role, poll_priority, language=en и expected_content_types. Быстрые источники опрашиваются независимо; при ошибке действует существующий backoff до 1800 секунд. Непроверенные в live Binance endpoints не объявляются исправными.')
line();line('## Корпус')
line();line('| Группа | Raw observations | Требование | Ограничение |');line('|---|---:|---:|---|')
groups={'Binance':['binance_listings','binance_delistings','binance_maintenance','binance_news'],'Kraken':['kraken_status_incidents','kraken_status_maintenance'],'Coinbase':['coinbase_blog'],'Tether':['tether_news'],'Circle':['circle_pressroom'],'Strategy':['sec_strategy_8k']}
notes={'Binance':'ConnectError; реальных Binance items нет','Kraken':f"{d['distinct_incidents'].get('kraken_status_incidents',0)} incident IDs + {d['distinct_incidents'].get('kraken_status_maintenance',0)} maintenance IDs; обновления не считаются отдельными underlying events",'Coinbase':'Официальные карточки/summary; full article fetch из Docker — 403','Tether':'RSS, включая вторую историческую страницу','Circle':'Две страницы официального pressroom','Strategy':'10 реальных 8-K metadata; HTML filings — 403, BTC facts не заявляются'}
for group,sources in groups.items():line(f"| {group} | {sum(d['raw_counts'].get(s,0) for s in sources)} | {20 if group=='Binance' else 10} | {notes[group]} |")
line();line(f"Всего raw observations: **{sum(d['raw_counts'].values())}**. Маршрутизировано уникальных документов: **{len(articles)}**. Semantic outputs, совпадающие с актуальным DI input: **{len(sem)}**. Дефицит Binance не компенсируется числом lifecycle updates Kraken.")
line();line('## Распределение')
line();line('Source/category labels могут пересекаться; это происхождение и назначение источника, а не доказательство финансового события:')
for category in ('exchange','incidents','stablecoin','corporate_treasury','institutional','infrastructure','security'):
 line(f"- {category}: {sum(category in a['categories'] for a in articles)}")
line();line('Принятые semantic concepts (только завершённые результаты актуального DI; группы могут пересекаться):')
for label,concepts in {'listings':{'exchange_listing'},'delistings':{'exchange_delisting'},'incidents':{'exchange_outage','withdrawal_suspension','deposit_suspension','funding_degradation','api_outage','network_maintenance'},'stablecoin':{'stablecoin','stablecoin_issuance','stablecoin_redemption','stablecoin_infrastructure'},'treasury':{'treasury_purchase','corporate_btc_purchase','corporate_btc_sale','corporate_btc_holdings','crypto_treasury_strategy'},'institutional':{'institutional_crypto','crypto_derivatives','custody'}}.items():
 line(f"- {label}: {sum(bool(concepts & {c['concept_id'] for c in x['semantic_concepts']}) for x in sem.values())}")
line(f"- promotional hint: {sum('content_hint:promotional' in a['categories'] for a in articles)}; Binance noise проверен fixtures, а не вымышленным real smoke.")
line();line('## Required example Article Insights')
line();line('Пустой facts/assets — честное отсутствие подтверждения. Semantic candidates не заменяют точные DI facts. Числа similarity не являются вероятностями.')
patterns=[('Kraken funding/withdrawal','Funding delays for select blockchain networks'),('Coinbase derivatives','Coinbase Brings Global Crypto Derivatives'),('Tether stablecoin infrastructure','Tether and Fasanara Capital Launch'),('Circle infrastructure','Circle Launches Arc Mainnet'),('Strategy filing','Strategy — 8-K — 2026-09-14')]
for label,pattern in patterns:
 candidates=[a for a in articles if pattern in a['title']]
 line();line('### '+label)
 if not candidates:line('Пример не доступен в зафиксированном корпусе.');continue
 a=max(candidates,key=lambda a:(a['intelligence_id'] in sem,len(a['facts']),a['published'] or ''));s=sem.get(a['intelligence_id'])
 line();line('- Source: '+a['source']);line('- Title: '+a['title']);line('- Published: '+str(a['published']));line('- URL: '+str(a['source_url']));line('- Article type: '+(s['article_type'] if s else 'нет завершённого актуального semantic result'))
 line('- Enrichment: '+j(a['enrichment']));line('- Extracted entities: '+j(sorted({e['canonical_name'] for e in a['entities']})))
 line('- Facts: '+j([{k:f[k] for k in ('fact_type','action','asset','quantity','aggregate_value_usd','average_price_usd') if k in f}|{'fact_id':f['fact_id'],'evidence_offsets':[f['evidence']['start_char'],f['evidence']['end_char']]} for f in a['facts']]))
 line('- Measurements: '+j([{'kind':m['kind'],'value':m['value'],'min':m['min'],'max':m['max'],'unit':m['unit'],'currency':m['currency']} for m in a['measurements']]))
 line('- Semantic concepts: '+j([x['concept_id'] for x in s['semantic_concepts']] if s else []));line('- Affected assets: '+j([x['asset'] for x in s['affected_assets']] if s else []));line('- Article route: '+a['article_route'])
 if s:line('- Semantic suggested route (research): '+s['routing']['semantic_suggested_route'])
 line('- Why it matters / basis: '+j(a['route_reasons']+(s['routing']['reasons'] if s else [])))
 line(f"- Audit: document `{a['document_id']}`, DI `{a['intelligence_id']}`, routing `{a['routing_id']}`.")
line();line('### Binance listing и delisting/maintenance')
line();line('Не подтверждены real smoke: официальный endpoint сбрасывает соединение. API parser, malformed/empty catalogue, promotional hint и standard news.raw.v1 boundary проверены тестами. Поисковые сниппеты и вымышленные публикации не подставлялись.')
line();line('### Strategy BTC acquisition/sale/holdings')
line();line('Metadata 8-K подтверждены, но финансовое содержание недоступно из-за SEC 403. Поэтому реальные BTC acquired/sold/holdings не утверждаются. Пример 520 BTC / $34.9m / $67,068 — **unit fixture**, не реальный filing этого smoke. Проверено точное извлечение 520 / 34900000 / 67068 и отказ от вычисления отсутствующей средней цены.')
line();line('## Тесты и failure isolation')
line();line('| Suite | Passed |');line('|---|---:|')
for name,count in tests.items():
 if name!='tests':line(f'| {name} | {count} |')
line();line('Всего: '+str(sum(v for k,v in tests.items() if k!='tests'))+' passed. Наборы запускались в отдельных тестовых БД/NATS; рабочие сервисы Stage 2–5 не запускались. Проверены duplicate delivery, restart persistence, lifecycle replay и изменение только статуса, malformed/403/oversize transport, retry/outbox после NATS failure и source isolation. Production NATS не отключался ради fault injection.')
line();line('Bootstrap replay: 0 created, 0 failed на повторном импорте всех восьми захваченных ответов; реальные суммы duplicates и SHA-256 находятся в `bootstrap-manifest.json`. Live: Binance/Coinbase failed одновременно с healthy Kraken/Tether/Circle/EDGAR, что подтверждает отсутствие глобальной блокировки collector.')
line();line('## Версии и воспроизводимость')
line();line('- news.raw.v1 и document.enriched.v1 не изменены.')
line('- DI: `rules.crypto.v1.1.json`, ruleset `crypto_v1_1`, entity registry `crypto_v1`. Предыдущая crypto_v1 сохранена для audit; исправлено ложное Arc/Research совпадение.')
line('- Ontology: `semantic_ontology_crypto_v1`; существующие concepts сохранены без изменения, новые описания EN/RU добавлены отдельно.')
line('- Semantic final policy: `semantic_crypto_v1_1`; model revisions и weights не изменены. Для исправленных DI inputs допускается reuse уже сохранённого inference только при совпадении document ID, body hash, sentence boundaries, языка и всей semantic-конфигурации. Ссылка находится в immutable snapshot `inference_reused_from`; performance относится к исходному измерению inference.')
line('- Router/high-value registry: `crypto_v1`. Promotions получают `content_hint:promotional` через существующий generic categories path и archive приоритетнее high-value rules.')
line('- Incident key: `incident/{incident_id}/update/{update_id}/{revision_hash}`. В read-only catalogue отдельно доступен `incident_id`; исходные updates и raw JSON сохранены. Новые canonical events здесь не создаются; correlation может использовать общий ключ.')
line();line('## Dashboard')
line();line('News Feed: Crypto, Exchange, Stablecoin, Corporate Treasury, Institutional, Incidents; source badges Binance/Kraken/Coinbase/Tether/Circle/Strategy / SEC. Sources строится из collector registry и показывает новые источники и ошибки. Новый интерфейс не создавался. Для увеличившегося каталога убрано чтение полных DI/body snapshots при запросе списка; страницы читают только необходимые JSON-поля.')
line();line('## Failures, ресурсы и ограничения')
for state in d['source_health']:line(f"- {state['id']}: {state['status']}; {state['last_error_type'] or 'без ошибки'}.")
line('- Coinbase: live Docker HTTP 403; десять карточек получены обычным HTTP с хоста и сохранены с точной provenance. Полные статьи не выдаются за доступные.')
line('- Strategy: submissions API healthy, HTML archive 403; результаты enrichment failed и DI unsupported сохраняются, missing numbers не заполняются.')
line('- Kraken: короткие complete API updates могут получать conservative partial по существующей sufficiency policy; текущая HTML incident page намеренно не подмешивается к старому lifecycle update.')
line('- Coinbase/Circle карточки содержат дату без времени: midnight UTC — нормализация даты, category `publication_precision:day` явно отмечает гранулярность. Это не подтверждённое точное время публикации и не доказательство intraday availability.')
line('- SEC table extraction консервативен: однозначные подписанные BTC/aggregate/average values с exact spans; повторяющиеся колонки, неоднозначные субъекты и гипотетические примеры не повышаются в structured fact.')
line('- Semantic CPU worker: около 2.0–2.2 GiB RSS; DI около 520 MiB. Docker VM ограничена 3.825 GiB. Одновременные NLP-проверки/replays привели к перезапускам и одному killed helper (137); DI временно приостанавливался после завершения пересчёта, потерянные leases прежних процессов освобождены без изменения результатов. Параллельных model workers не добавлялось.')
line('- Короткие updates: примерно 3–9 s inference; крупные статьи в измеренных результатах — до ~139 s. Платных API costs: 0.')
line('- Kraken history JSON ~0.7 MB на два ответа. При хранении каждого raw poll каждые 30 s это порядка 2 GB/day до компрессии/retention; transport/output dedup не является raw-retention policy. Старый audit не удалялся.')
line('- Для локального deployment использованы новые исходники поверх существующих образов с теми же pinned зависимостями: повторная загрузка spaCy при обычной сборке была слишком медленной. Dockerfiles/зависимости проекта не изменялись.')
line();line('## Что теперь видно в потоке')
line();line('Ранее отсутствовавшие классы реальных материалов: Kraken funding/withdrawal/network incidents и maintenance lifecycle, Coinbase crypto derivatives/institutional products, Tether stablecoin-backed lending infrastructure, Circle Arc/USDC minting-redemption/institutional integration announcements, company-specific Strategy 8-K metadata. Binance articles и финансовое содержание закрытых SEC filings по-прежнему не доступны; это отражено как failure, а не скрыто как успешное подключение.')
(ROOT/'docs/crypto-source-expansion-v1-report.md').write_text('\n'.join(out)+'\n')
