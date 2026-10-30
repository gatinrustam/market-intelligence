# Document Intelligence — DI-1 verification

Verified 2026-09-20T07:36:37.824645+00:00. Pipeline/rules/registry **1.0 / 1.0 / 1.0**. No LLM/provider requests.

## Implementation, languages, registry and rules

Independent service on localhost:8009, separate DB, exact immutable input, versioned jobs/results, extracted row tables, strict schema and transactional outbox. Local English/Russian spaCy backends; unsupported languages produce an explicit result. Versioned registry and dependency/context rules; negation, modal/conditional guards, no inferred rate, no full body field in NATS. [Architecture and limitations](architecture/document-intelligence.md).

Schema: `contracts/document/intelligence/v1.schema.json`. Canonical event, market, analysis and Event Intelligence contracts were not changed.

## Tests / regression

| Suite | Passed |
|---|---:|
| ingestion | 40 |
| enrichment | 95 |
| events | 103 |
| market_data | 56 |
| market_context | 105 |
| llm_analysis | 60 |
| evaluation | 46 |
| event_intelligence | 24 |
| document_intelligence | 55 |
| dashboard | 34 |
| **Total** | **618** |

DI-1 tests cover all six required EN/RU examples, canonical aliases, exact Unicode evidence, fractions and normalized units, dates, missing values, unsupported language, negative/hypothetical/incidental mentions, target-versus-actual ambiguity, partial components, strict schema, duplicate delivery, version conflicts, expired leases/fencing, transaction rollback, core failures, API inputs and exact JetStream publication. Evaluator tests verify occurrence-aware precision/recall and empty denominators.

Separate broker-outage probe: extraction saved one result with one pending outbox while isolated nats-test was offline; a fresh process published it once after recovery and broker dedup suppressed repeat publication. Production NATS was never stopped. Database-only regression suites ran sequentially with the broker tests; no paid provider calls. Two existing enrichment dependency warnings remain non-failing.

## 55-document real smoke

Language distribution: **{'en': 55}**. Russian behavior is tested through fixtures; this existing catalogue has no Russian documents.

| Extracted layer | Count |
|---|---:|
| entities | 2477 |
| facts | 18 |
| measurements | 242 |
| relations | 27 |
| dates | 223 |

**16 documents with facts; 39 with zero facts.** Complete: 30; partial: 25; failed: 0. All 25 partial results have only the source `partial_enrichment` warning: SEC RSS fallback, not a crashed component. Zero dead inputs. All 55 outbox messages published; every payload equals the NATS message, every source hash/exact input matches, all evidence slices validate.

Entity/measurement/relation/fact counts are occurrences, not unique real-world entities or events. A repeated rate-decision sentence can produce a second evidenced occurrence; DI-1 performs no event merge.

Topics by number of documents: regulation: 9, capital_markets: 2, monetary_policy: 6, interest_rates: 6, inflation: 1.

## Required examples

| Example | Entities | Facts | Measurements | Relations | Status |
|---|---:|---:|---:|---:|---|
| Fed FOMC | 13 | 1 | 2 | 1 | complete |
| ECB speech | 99 | 0 | 4 | 0 | complete |
| ECB interview | 47 | 0 | 4 | 0 | complete |
| SEC proposal | 2 | 1 | 0 | 1 | partial |
| SEC partial RSS | 6 | 0 | 0 | 0 | partial |

Representative facts: Fed FOMC `hold`, range **3.5–3.75 percent**; SEC E-Delivery `regulation.rule_proposal`. ECB speech/interview and SEC personnel RSS example have zero supported facts; their entities/measurements/dates remain available with evidence. No facts are fabricated to fill empty sections.

- Fed FOMC: **Federal Reserve issues FOMC statement** — document `af753500-f62e-43ec-8166-dc3afad60ec3`.
- ECB speech: **Piero Cipollone: The future of euro cash: trusted today, designed for tomorrow** — document `5b1a0b2f-5e7d-47a8-9752-87c81bf779f5`.
- ECB interview: **Christine Lagarde: Interview with Ouest-France** — document `f7a7aac3-427c-44a5-83f2-3b4b18e2cab3`.
- SEC proposal: **SEC Proposes New E-Delivery Approach to Make Information More Readily Accessible and Useful for Investors** — document `b71f6f3c-65c9-42c7-a864-cc70b1519d73`.
- SEC partial RSS: **SEC Announces Departure of Principal Deputy Director of Enforcement Sam Waldon** — document `a5244d2d-c901-492e-a557-39f2d01af39f`.

Full outputs and exact proof flags: [55-document JSON report](document-intelligence-verification.json).

## Gold dataset metrics

Ten manually annotated English observed documents; six are truncated SEC RSS bodies, two Fed and two ECB. Exact input retained. Single annotator (Codex); source-based annotation corrections documented per file. The same bootstrap set informed rule debugging, so this is **not held-out/general accuracy**. Russian gold is not yet annotated.

| Layer | TP / FP / FN | Precision | Recall | F1 |
|---|---|---:|---:|---:|
| entities | 136 / 23 / 12 | 0.8553 | 0.9189 | 0.8860 |
| facts | 7 / 0 / 2 | 1.0000 | 0.7778 | 0.8750 |
| measurements | 26 / 0 / 0 | 1.0000 | 1.0000 | 1.0000 |
| topics | 11 / 0 / 17 | 1.0000 | 0.3929 | 0.5641 |

Entity errors include exact boundary differences and small-model NER type errors (e.g. job titles tagged as people). Fact misses: SEC proposal expressed through a pronoun, and an inflation assertion with both a threshold and actual number; ambiguous value association is deliberately rejected. Topics currently require supported facts, explaining their limited recall on speeches. Fact F1 does not include numerical attachment correctness; dedicated tests cover that boundary.

[Gold data and annotation policy](../datasets/document_intelligence/gold/README.md) · [Per-document metrics and complete FP/FN lists](document-intelligence-gold-metrics.json).

## Dashboard

The existing event detail now includes a Document Intelligence section for each pinned enriched document. Read-only expandable facts/entities/measurements/relations/topics/dates show the exact highlighted source phrase and extractor/rule/version. The adapter verifies source body hash and Unicode slices; mismatched evidence is rejected. Dashboard suite: 34 tests, 145 assertions, including rendering, evidence mismatch, XSS escaping and upstream outage. Authenticated browser screenshot QA was not performed; rendering and disclosure markup were verified through feature tests.

## Audit preservation

Read-only comparison confirms the original 55 Event Intelligence 1.0 results and all three historical Astra analyses, requests, responses and frozen inputs are unchanged. Astra job count remains four (three completed, one original blocked live job), provider attempts remain three. DI-1 generated no provider requests.

## Known limitations / deviations

- Four initial taxonomy entries are reserved without active detectors: guidance, exchange outage, security incident, stablecoin depeg. Conservative morphology/dependency rules cover 11 fact types, not unrestricted language understanding.
- No unrestricted coreference or global entity resolution. Registry misses fall back to statistical NER, whose type/boundary errors remain explicit. Some headings are part of longer parser sentences.
- Language detection has deterministic short-Russian rules because raw langdetect misclassified required mixed-script fixtures; this is a local fallback, not translation. Ambiguous multilingual input can still be unsupported.
- Ambiguous rates/benchmarks/forecasts are not filled from outside knowledge. Economic facts represent source claims; qualification such as perceived inflation must be retained from evidence.
- Dates cover explicit supported forms; missing year stays null. No broad relative-date inference or unsupported timezone conversion.
- UI is integrated into existing event/evidence detail instead of adding a new document route. No Stage 4/routing integration was added, as required.
- Gold annotation is a bootstrap by one annotator, with no independent human review; no broad quality claim.

## Reproduce

Run `scripts/test-document-intelligence.sh`, `scripts/test-document-intelligence-faults.sh`, `scripts/evaluate-document-intelligence.sh` sequentially. Read-only real smoke: `docker compose exec -T document-intelligence python - < scripts/smoke-document-intelligence.py`.

Production restart verified: ready; still 55 inputs/results and 55 published messages, no duplicates. All 12 project runtime containers healthy; isolated test broker stopped; unrelated projects remain stopped.
