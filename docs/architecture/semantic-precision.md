# DI-5.1 — Semantic Precision

DI-5.1 runs inside the existing local `article-semantic` service after chunk inference. It keeps `article.semantic.v1` and the separate research database/outbox. It never calls OpenAI/Astra, changes production routing, trains on labels, or rewrites a completed result.

## Versioned acceptance

Current policy is `config/article_semantic/policy.v1.json`; the frozen DI-5 policy is `policy.di5.json`. Ontology `semantic_ontology_v2` contains 29 bilingual concepts with positive and, for confusion-prone concepts, negative examples. Original `ontology.v1.json` is preserved. Model revisions and derived CPU artifact hashes are unchanged.

Each chunk has positive similarity, negative similarity and their margin. All concept scores are retained in the frozen observation, while public top matches are bounded. Thresholds are per concept in `reranking.v5.json`. Scores are retrieval similarities, not probabilities.

Accepted article concepts need exact DI facts, explicit sentence entity/action or measurement support, two independent sentence groups in distinct chunks, or a very strong contrastive match plus extracted entities. A weak match alone remains review-only. Negative-example concepts additionally require a positive margin and direct sentence support. Every concept has an accepted/rejected/review decision, reasons, counts, evidence spans, fact/entity/relation references and contrastive scores. Independence is based on disjoint sentence IDs, not two copies of the same sentence.

Claims are reselected from the full stored body, ordered by facts, actions/relations, measurements and supported thematic context. Explicit metadata, questions, references and boilerplate are excluded. Types require sentence evidence; ambiguous combinations use `generic_claim`. DI facts remain unchanged even if a claim needs a more cautious interpretation. Asset links have their own exact evidence. Legal company suffix `АО` alone does not establish equity exposure. There is no general mapping from digital central-bank money to crypto assets.

The seven `reranking.importance_components` explain specific-event support, DI facts, source quality, document quality, semantic centrality, assets and density. The display projection uses these components; older top-level information-value fields remain available for contract/history compatibility. Importance is not a maximum-cosine threshold. Suggested routes remain research-only (`production_switch=false`).

## Immutable comparison and failure isolation

For each new input the worker stores a DI-5 baseline, using the original description embeddings and shared GLiNER observation. Existing DI-5 results are reused unchanged. It then appends the precision result and a comparison with baseline ID/hash, removed/added topics, assets and claims, and before/after importance/routes.

`semantic_precision_v1` is retained as an intermediate research revision. Its set-derived array ordering was not stable across processes. `semantic_precision_v2` orders these arrays deterministically. `semantic_precision_v3` additionally tightens geographic/stock matching and strips speech metadata/outlines, with sentence-level perception/expectation typing. `semantic_precision_v4` also separates title/lead concept evidence from clean claims, gates educational/test notices, constrains personnel/regulation anchors and excludes foreign-share futures from Russian equity links. The final `semantic_precision_v5` applies the instrument boundary across the whole document, including split futures tables. Replay is tested across different Python hash seeds. The 70 completed v2 rows are retained as an intermediate revision. `reranking_legacy.py` preserves the earlier algorithm for audit; no old payload is rewritten. `scripts/rerank-semantic-precision.py` creates the new revision from frozen observations without model calls. The inference provenance and original model timing remain visible, with separate reranking timing.

A reranker exception leaves the independently stored baseline accessible and produces an explicit failed reranking status/warning. RSS supervisor tasks and source failures remain independent. Job leases can be reclaimed after worker loss; this mutates scheduling state only, never completed history.

## Official Russian sources

- `cbr_events_ru`: https://www.cbr.ru/rss/eventrss
- `cbr_press_ru`: https://www.cbr.ru/rss/RssPress
- `moex_news_ru`: https://www.moex.com/export/news.aspx?cat=100

Source declarations set language `ru`. Router registry revision `1.1` only adds the three sources as `official_primary`; its routing rules and high-value registry are unchanged. Semantic source quality also recognizes them. The same ingestion, enrichment, DI-1, semantic and router paths process EN and RU.

The official RSS is sufficient for discovery. Existing generic enrichment fetches the official article only when the RSS body is too short, using exact allowed CBR/MOEX hosts. No source-specific scraper or Russian-only inference branch was added.

These feeds expose extensive archives. Normal polling is bounded to the first 20 entries per source per poll; it is **not** an exhaustive historical crawler. The complete fetched RSS bytes remain in raw storage. `Ingestor.process(selected_indices=...)` supports explicit research/bootstrap selection from those exact bytes. A gap exceeding this polling window needs explicit recovery from retained/full feeds. `scripts/ingest-semantic-ru-corpus.py` selects the fixed 20 CBR (14 events + 6 press) and 20 MOEX inputs for this evaluation.

## Read-only insight and append-only review

`GET /documents/{document_id}/insight` returns newest and archived insights, including `baseline_insight` for side-by-side comparison. Russian titles, bodies and evidence remain Russian source text. Display labels/reasons are localized without changing immutable machine payloads.

The existing authenticated review endpoint accepts optional `concepts_correct`, `gold_concepts`, and `false_positives`, in addition to claims/assets/importance/missing-context fields. Request UUID idempotency and optimistic revisions apply. Old request hashes remain compatible when new fields are omitted. Unknown concept/asset/claim IDs are rejected. Labels never modify analysis or trigger model learning.

## Validation

- `scripts/smoke-semantic-precision.py`: pinned 95-document corpus, preserved 77 earlier result hashes, exact NATS payloads, unchanged DI facts, source offsets, complete chunk coverage, baseline comparison and deterministic frozen replay; separate EN/RU resource aggregates.
- `datasets/semantic_precision/review/ru-corpus.v1.json`: 40 actual enriched source documents, full stored text and provenance, 13 pilot source reviews and 27 pending independent reviews.
- Pilot labels are Codex-assisted and **not independently human validated**. The original 15 EN gold importance/assets are fixed for comparison. They are not a held-out generalization benchmark.

Run one model worker on the 8 GiB host. Finish image builds and regression tests before sustained inference; the first combined run exited 137 under concurrent workload. Completed jobs survived and remaining jobs resumed. Original inference timings include shared-host contention and are not isolated microbenchmarks.

Live RSS smoke выявил превышение стандартного лимита 5 MB для MOEX (~5,7 MB). Compose теперь задаёт настраиваемый `INGESTION_MAX_FEED_BYTES=10000000`; ограничение размера сохранено, тест отказа при превышении лимита остаётся действующим.
