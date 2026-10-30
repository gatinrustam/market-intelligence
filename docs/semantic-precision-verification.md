# DI-5.1 — итоговая проверка

DI-5.1 реализован и проверен на фиксированном корпусе из 95 реальных документов: 55 EN и 40 RU. Итоговая версия — `semantic_precision_v5`. DI-5 baseline — `semantic_pipeline_v5`; это разные линии версий. OpenAI/Astra не вызывались, production router не переключался на semantic recommendations.

**Все оценки качества — Codex pilot, not independently human validated.** Выборка целевая и использовалась при настройке правил; это не независимый held-out benchmark и не оценка точности на произвольном потоке.

## Реализация

После локального chunk inference работает deterministic article reranker. Для принятия темы нужны DI facts, явная связь сущность/действие, два независимых набора evidence либо очень сильный semantic match с дополнительным подтверждением. Один слабый match остаётся кандидатом. Сохраняются positive/negative similarity, margin, поддержка facts/entities/relations/sections и причины accepted/rejected/review. Similarity не представляется вероятностью.

Asset links требуют собственного текстового evidence. Тип claim определяется на уровне предложения; неоднозначный тип становится `generic_claim`. Claims ранжируются по фактам, действиям, измерениям и тематической поддержке; библиография, вопросы, заголовки и служебные фрагменты фильтруются. Importance имеет семь независимо объясняемых компонентов.

Контракт `article.semantic.v1` расширен совместимыми полями. Labels сохраняются отдельно, append-only; обучение по ним не запускается. Ошибка reranker оставляет доступным отдельный DI-5 baseline. Ошибки RSS изолированы по источникам.

Подробности: [архитектура](architecture/semantic-precision.md), [машинный аудит](semantic-precision-verification.json), [метрики с результатами по документам](semantic-precision-metrics.json).

## Русские источники и корпус

| Источник | Официальный RSS | Фиксированный RU corpus |
|---|---|---:|
| `cbr_events_ru` | https://www.cbr.ru/rss/eventrss | 14 |
| `cbr_press_ru` | https://www.cbr.ru/rss/RssPress | 6 |
| `moex_news_ru` | https://www.moex.com/export/news.aspx?cat=100 | 20 |

Все три источника имеют `ru`, `official_primary` и используют существующую цепочку ingestion → enrichment → DI-1 → semantic → reranking → dashboard. Общий Article Router сохраняет собственные правила; добавлена только регистрация официальных источников. Специального русского scraper или отдельной ветки inference нет. Все 40 RU документов имеют готовый enriched body. Во всём корпусе ready body есть у 70 документов, ещё 25 EN доступны как partial RSS.

Полные тексты, provenance и source-review содержатся в `datasets/semantic_precision/review/ru-corpus.v1.json`. Из 40 документов 13 имеют pilot-разметку, 27 ждут проверки. Представлены ставка, инфляция, выступление, интервью, крипторегулирование, торговые ограничения, листинг, риск-параметры, валютный рынок и административные сообщения.

Обычный polling ограничен первыми 20 элементами каждой ленты, раз в 900 секунд. Полные RSS bytes сохраняются. Это не исчерпывающий historical crawler: пропуски за пределами окна требуют явного backfill из полной ленты. Фиксированный исследовательский набор выбран явно из реальных RSS.

## Модели и policy

Model revisions не изменены:

| Модель | Revision |
|---|---|
| BAAI/bge-m3 | `5617a9f61b028005a4858fdac845db406aefb181` |
| urchade/gliner_multi-v2.1 | `443d26d654e0324125a96bebd8e796c14ff2efe6` |
| microsoft/mdeberta-v3-base | `a0484667b22365f84929a935b5e50a51f71f159d` |

BGE CPU artifact SHA-256: `30ba401e590463584607ed3fae0786ffd5b811e11d186ca20b85ca176283066c`. QNNPACK INT8 Linear, компактное FP16-хранение word embeddings с FP32 compute; GLiNER FP32. oneDNN не используется. Runtime: Torch 2.8, sentence-transformers 5.1.2, transformers 4.57.6, GLiNER 0.2.24, NumPy 2.2.6.

Ontology `semantic_ontology_v2`: 29 двуязычных concepts, positive/negative examples. Per-concept thresholds: `semantic_contrastive_v1`. Итоговый reranker: `semantic_reranking_v5`, файл `config/article_semantic/reranking.v5.json`. Policy: `config/article_semantic/policy.v1.json`; неизменный DI-5 baseline: `policy.di5.json`.

## EN: те же 15 reviewed документов

Gold importance/assets сохранён от предыдущего сравнения. Claims оценены по корректности выделенного текста и его типа.

| Метрика | DI-5 | DI-5.1 |
|---|---:|---:|
| Important precision | 100% (6/6) | 90% (9/10) |
| Important recall | 60% (6/10) | 90% (9/10) |
| Asset precision | 51,85% (14/27) | 100% (15/15) |
| Asset recall | 87,5% (14/16) | 93,75% (15/16) |
| Claim precision | 58,82% (40/68) | 94,92% (56/59) |

Asset/claim precision превысили заданные baseline. Asset recall вырос; корректных claims стало 56 вместо 40 при снижении общего числа с 68 до 59. Полной exhaustive-разметки всех возможных claims нет, поэтому claim recall не заявляется. Important precision немного снизился при существенном росте recall.

Проверены исходные регрессии:

- Fed FOMC: необоснованный ETF удалён; USD/rates сохранены.
- Lagarde interview: удалены crypto_exchange, exchange_outage, institutional_crypto, treasury_purchase и crypto_market; поддержанные rates/EUR/US_equities сохранены.
- ECB cash speech: удалены ETF, crypto_exchange, treasury_purchase и crypto_market; cash/legal-tender не превращается автоматически в crypto regulation; остаётся EUR.

Оставшиеся ошибки: создание SEC accounting/enforcement unit переоценено как важное событие; SEC Innovation Exemption для tokenized stock недооценено, crypto_market пропущен при сохранении US_equities. Три ошибочных EN claims: слишком общий Fed assessment с узким типом inflation_expectations; survey income-expectation без достаточного antecedent; фраза Lagarde о двух факторах долгосрочных ставок без самих факторов.

## RU: отдельные результаты 13 reviewed документов

| Метрика | DI-5.1 |
|---|---:|
| Concept precision | 96,15% (25/26) |
| Concept recall | 83,33% (25/30) |
| Asset precision | 100% (15/15) |
| Asset recall | 100% (15/15) |
| Claim precision | 77,78% (35/45) |
| Important precision | 100% (10/10) |
| Important recall | 90,91% (10/11) |

Результаты RU не смешаны с EN. Остаётся лишний general_commentary у выступления Заботкина; пропущены отдельные employment/FX/ETF темы. Запуск инфраструктуры цифрового рубля недооценён из-за консервативных cash-policy правил. Некоторые claims теряют antecedent/условия сценария либо получают слишком узкий тип. Ограничение futures на уровне всего документа защищает от ложных RU_equities, но может быть слишком консервативным для смешанных статей.

## Десять полных русских примеров

[Все 10 статей целиком и их Article Insights](semantic-precision-ru-examples.md): полный сохранённый нормализованный body, исходная ссылка, результат, важность, причины, точные подтверждающие фрагменты и замечания pilot-review.

1. Банк России: ключевая ставка 14%.
2. Банк России: инфляция.
3. Выступление Алексея Заботкина.
4. День открытых дверей Банка России.
5. Банк России: крипторегулирование.
6. MOEX: приостановка торгов.
7. MOEX: риск-параметры фьючерсов.
8. MOEX: UZS/RUB.
9. MOEX: листинг EUTR.
10. MOEX: тестирование T0 / техническое сообщение.

Это полный текст, сохранённый существующим enrichment, а не утверждение об идентичности поздно полученной страницы исторической версии в момент публикации.

## Dashboard и review

[Пример русской статьи в dashboard](http://localhost:8006/admin/news/52e4a704-0423-5154-ab74-a5e8ac7d3006). Есть сравнение DI-5 / DI-5.1, темы, assets, claims, importance, причины и evidence; русские фрагменты не переводятся. Reviewer отмечает корректность concepts/claims/assets/importance, missing context и false positives.

Сохранены 28 pilot labels: 15 EN + 13 RU. Дополнительно выполнено реальное сохранение через UI для статьи о ставке: label revision 1 → 2, обе версии остались, machine-result hash не изменился. В UI проверены русское сравнение и сообщение об успешном отдельном сохранении оценки. Это проверка механизма review, не независимая человеческая валидация.

## Тесты, immutable history и NATS

**791 тест прошёл:** ingestion 44, enrichment 95, events 103, market-data 56, market-context 105, llm-analysis 60, evaluation 46, event-intelligence 24, document-intelligence 55, article-router 28, event-research 58, article-semantic 61, dashboard 56. Dashboard: 229 assertions. Остались только предупреждения об устаревающих зависимостях.

Для всех 95 итоговых результатов проверены полный chunk coverage, точные source offsets, неизменность DI facts, actual NATS payload = stored payload и deterministic frozen replay. 77 прежних semantic payload hashes не изменились; 55 прежних router payload/snapshot hashes не изменились. LLM runs осталось 3, новых внешних LLM вызовов нет.

Промежуточные `semantic_precision_v1`–`v4` сохранены для аудита; в v2 завершены 70 строк, в v1/v3/v4/v5 — по 95. v1 выявил нестабильный порядок set-derived массивов, исправленный в v2; следующие ревизии ужесточали sentence, RU и instrument boundaries. Новые revisions создавались из frozen observations без повторной загрузки моделей. Старые результаты не переписывались. На момент фиксированного аудита опубликовано 567 semantic messages; обычный live поток может увеличивать число результатов после этого снимка.

## Производительность и память

Apple M3, host 8 GiB, Docker VM около 3,825 GiB; один model worker.

| Метрика | EN, 55 документов | RU, 40 документов |
|---|---:|---:|
| Средняя latency / документ | 14,714 s | 8,644 s |
| Медиана | 2,026 s | 4,121 s |
| Максимум | 192,515 s | 54,285 s |
| Inference sum | 809,285 s | 345,769 s |
| Chunks | 398 | 183 |
| Chunks / second | 0,492 | 0,529 |
| Peak RSS | 2 623 504 384 bytes ≈ 2,443 GiB | 2 434 707 456 bytes ≈ 2,267 GiB |
| Среднее final reranking/fusion | 0,02096 s | 0,01083 s |

Загрузка моделей: 45,929 s в первом запуске и 61,496 s после возобновления. Inference timings относятся к первоначальному успешному inference каждого документа и повторно использованы при финальном reranking; это не новый model benchmark для каждой policy revision.

## Ограничения и отклонения

Первый worker завершился с кодом 137 после 36 документов при одновременных сборках/тестах; вероятная причина — давление на память. Завершённые результаты сохранились, scheduling lease освобождён, оставшиеся 59 документов обработаны после прекращения конкурирующей нагрузки. Потерянная попытка и model load не включены в latency завершённых документов. Замеры получены на общем host, не в изолированном microbenchmark. Сборки/регрессии следует завершать до запуска длительного model inference.

Качество оценено на небольшом целевом pilot, требуется независимая ручная проверка, особенно RU claims. 25 partial RSS EN документов ограничивают доступный контекст. Существующие DI-1 facts не менялись: например, решение по ставке ЦБ поддерживается semantic claim, но текущий DI-1 extractor может классифицировать его по inflation fact. UI entities включают модельных кандидатов, а не только независимо подтверждённые сущности.

Не реализовывались trading, Signal Engine, Model Router, fine-tuning, автоматическое обучение по labels или автоматическое переключение production routing. Обычный ingestion и один semantic worker включены после окончания сборок и тестов; ненужные ранее остановленные проекты и сервисы не восстанавливались.

Live RSS smoke выявил превышение стандартного лимита 5 MB для MOEX (~5,7 MB). Compose теперь задаёт настраиваемый `INGESTION_MAX_FEED_BYTES=10000000`; ограничение размера сохранено, тест отказа при превышении лимита остаётся действующим.

После изменения лимита live MOEX poll успешно завершён: 11 новых записей, 9 дубликатов, 0 ошибок; остальные элементы отмечены deferred. Semantic worker загрузил обе модели и публикует новые результаты. Повторный smoke использует сохранённые IDs фиксированного корпуса, чтобы новые live статьи не меняли выборку.
