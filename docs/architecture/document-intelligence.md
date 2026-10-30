# Document Intelligence Engine — DI-1

Independent service on localhost:8009, Python 3.13 / FastAPI / Pydantic / SQLAlchemy / Alembic / MariaDB / NATS JetStream / spaCy. No LLM calls, routing, relevance scoring, event merging, embeddings, surprise, signals or trading.

## Pipeline and provenance

`DOCUMENT_ENRICHED: document.enriched.v1` → exact accepted input → deterministic local NLP → structured extraction → atomic persistence/outbox → `DOCUMENT_INTELLIGENCE: document.intelligence.v1`.

`LanguageDetector` uses pinned langdetect 1.0.9 with seed 0, an 0.80 confidence cutoff, and a versioned multi-marker Russian fallback for short texts mixed with Latin organization names. Other languages and empty/uncertain text produce `language=unsupported` and an explicit processing result; no translation. Short or mixed-language detection remains imperfect.

`EnglishSpacyBackend` and `RussianSpacyBackend` load pinned `en_core_web_sm-3.8.0` / `ru_core_news_sm-3.8.0` under spaCy 3.8.14, CPU only. The Russian model includes its morphology dependencies. Domain components consume detached `NLPDocument`, `Sentence`, `Token` and `NamedEntity` records; they do not access spaCy APIs. `AuxiliaryExtractor` is an extension protocol; optional proposals require a future explicit versioned promotion policy and are not canonical facts. GLiNER is absent.

Sentence IDs and offsets are Python Unicode character indices into the exact existing normalized `content.body`; no further normalization/retranslation changes the source. The internal sentence model includes text. NATS includes sentence metadata and evidence fragments, not an article body or a duplicate full sentence-text array. Headers/newlines may remain inside a parser sentence; relation predicate offsets still identify the actual action.

Every entity, measurement, date, relation, fact and topic carries `evidence` (document, sentence, offsets, text) and `extraction` (method, extractor, rule ID, version). Validation enforces `body[start:end] == evidence.text`, argument spans and referential consistency. Entity mentions have occurrence IDs; repeated mentions are intentionally retained. Facts are source claims, not independent truth verification.

## Registry, values and rules

`config/document_intelligence/entities.v1.json`: bilingual aliases for Fed/FOMC, SEC, ECB, Bitcoin/BTC, Ethereum/ETH, Binance, Coinbase, USD/EUR; indicators, instruments and locations. Longest non-overlapping aliases take precedence over statistical NER. Contextual Committee/Governing Council aliases require the named institution elsewhere in the same body. They do not use title metadata outside the body. Unregistered organizations/people/locations receive stable surface-derived IDs with `registry=false`; these are not globally resolved real-world identities.

`rules.v1.json`: pipeline/rules version 1.0, registry version 1.0. Uses lemmata, grammatical subject/object dependencies, scoped negation and conservative conditional/modal guards. xcomp control can connect “Committee decided to maintain …”; no fuzzy or unrestricted pronoun resolution. Numeric monetary facts are omitted when the necessary value is absent. Measurements remain explicitly empty rather than filled from outside knowledge.

Active fact rules cover rate decisions, inflation/employment/GDP/wages reports, SEC enforcement/proposal/adoption, withdrawal suspension, treasury purchases and ETF approval. Four taxonomy entries are reserved without active detectors: monetary guidance, exchange outage, security incident and stablecoin depeg. Other constructions can be missed. Unsupported or ambiguous constructions do not get guessed facts.

Economic reporting rejects target/goal/forecast comparisons and ambiguous multiple-measurement sentences. This intentionally trades recall for safer value association. Values are still available as separately evidenced measurements. Indicator evidence may describe survey/perceived values; readers must retain the source qualification instead of treating every `economic_data.*` claim as an official released statistic.

Measurements: decimal strings, percentages, percentage points, basis points (25 bps → 0.25 percentage_points), fractional ranges including Unicode hyphens, money/scale/currency, contextual prices, quantities and ratios. Clock times are not ratios. Dates support explicit ISO/month-name dates, times, ISO ranges and quarters; a missing year stays unnormalized. Timezone labels are preserved, never converted by guessing a missing date/offset.

Topics come from supported facts with evidence, plus asset mentions within a supported crypto fact. Incidental Bitcoin mentions alone produce no topic or priority flag. This causes low recall for broad speeches; that is measured, not hidden.

## Contract and durability

Strict schema: `contracts/document/intelligence/v1.schema.json`, generated from `app/schema.py`. Model versions and configuration hash are included. Input body SHA-256 and original enriched/source message IDs bind output to its source.

Own `document_intelligence` database, migration `di1001`: intelligence_inputs, intelligence_configurations, intelligence_jobs, intelligence_runs, document_entities, document_measurements, document_dates, document_relations, document_facts, document_topics, outbox_events, dead_inputs.

Identity: document ID + pipeline version + fact rules version + registry version. Configuration content is bound to this version tuple; reusing a tuple with different content fails. A new version creates a new run/result; previous results are never rewritten. Exact accepted JSON and NATS provenance are retained. Duplicate delivery reuses the job; conflicting input for a document ID is quarantined.

Workers claim recoverable leases with fencing tokens. Core NLP/validation failures terminate as failed; optional component errors preserve other results as partial with warnings. A partial enriched/RSS source also marks the result partial. Storage failures leave a recoverable lease and roll back all result rows. Successful completion persists extracted rows, immutable run and outbox in one transaction. Publisher retries failures, validates contract and uses stable NATS message ID deduplication. Output larger than 950 KB fails explicitly instead of silently dropping extraction.

Update the pipeline version when changing extraction code/model behavior; update the appropriate registry/rules version for data/config changes. Dependencies/models are pinned in pyproject and constraints. Consumer durable names include the configuration hash and replay retained inputs for new versions. Explicit research is available for already accepted documents.

## HTTP API

- GET `/health`, `/ready`, `/stats`
- GET `/documents/{document_id}/intelligence` — all retained versions, paginated
- GET `/intelligence/{intelligence_id}` — exact result
- GET `/intelligence/{intelligence_id}/input` — exact accepted JSON, hash, frozen configuration and provenance
- GET `/jobs` — processing statuses/errors
- POST `/documents/{document_id}/research` — idempotent run under the active version tuple

All interfaces are local/internal. Stage 4 inputs/contracts, canonical events and Event Intelligence remain unchanged. DI-1 does not route documents to Astra.

## Dashboard

The existing event detail embeds Document Intelligence for each exact evidence document; no separate document-detail route was introduced. Shows language, processing/version/warnings, entities, facts, measurements, relations, topics and dates. Native read-only disclosure controls reveal evidence; the exact span is highlighted within surrounding source text. The API adapter independently validates document/input identity, body hash and Unicode offsets. HTML is escaped; unavailable/mismatched data degrades the section while preserving the event page.

## Operation and evaluation

```sh
docker compose up -d --build document-intelligence
./scripts/test-document-intelligence.sh
./scripts/test-document-intelligence-faults.sh
docker compose exec -T document-intelligence python - < scripts/smoke-document-intelligence.py
./scripts/evaluate-document-intelligence.sh
```

Run backend/fault suites sequentially because isolated test databases and broker are shared. The fault script only interrupts nats-test. Stop it after verification if no longer needed.

Gold dataset: `datasets/document_intelligence/gold/`. Ten full *observed enriched bodies*, including six truncated SEC RSS inputs, two Fed statements and two ECB documents. Manually authored source labels, exact spans, full immutable inputs and annotation notes; no extractor-generated gold labels. Single annotator (Codex), no independent human adjudication. Error inspection prompted explicit source-based annotation corrections and conservative rule fixes; this is a development/bootstrap set, not a held-out benchmark. Format accepts future Russian documents; Russian fixtures are tests, not part of the English gold count.

Evaluator reports occurrence-aware micro precision/recall/F1 and per-document FP/FN details. Entities match type/canonical ID (registered entities) and exact span; measurements include normalized units/values and exact span; facts match taxonomy/action/subject/predicate span. Fact-value attachment is tested separately, not included in the reported fact F1. Topics use document-level sets. Empty denominators are null, never fictitious 100%.

NLP installation/model references: [spaCy installation](https://spacy.io/usage), [English model](https://spacy.io/models/en), [Russian model](https://spacy.io/models/ru). Small-model statistical NER has observed type/boundary errors; use extraction method and exact evidence rather than treating all mentions as verified entities.
