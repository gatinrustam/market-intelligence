# DI-3 — Event Engine v2 verification

Verified: 2026-09-20T08:30:53.920802+00:00

## Implementation / rules / schema

Independent parallel research service and own database, strict `event.research.v2`, frozen ruleset 2.0. Fact-first extraction with DI-only entity IDs, fact-linked measurements, explicit conflicts, multiple candidates and no cross-document merge. Legacy metadata rules remain supporting/fallback. No production v1 replacement, LLM/model routing or trading.

## Tests and regression

| Suite | Passed |
|---|---:|
| document-intelligence-tests | 55 |
| enrichment-tests | 95 |
| events-tests | 103 |
| market-context-tests | 105 |
| event-intelligence-tests | 24 |
| event-research-tests | 29 |
| llm-analysis-tests | 60 |
| tests | 40 |
| evaluation-tests | 46 |
| article-router-tests | 27 |
| market-data-tests | 56 |
| dashboard-tests | 44 |

**684 tests passed**, including 29 v2 tests and 44 dashboard tests (189 assertions). Required fact/legacy precedence, conflict, fallback, multiple candidates, measurement linkage, unresolved entities, unknown/explicit time, duplicate input, ruleset isolation, v1 non-mutation and strict schema are covered. Additional tests cover metadata-only HTTP access, provenance rejection, read-only APIs, retries, worker leases, outbox recovery and UI outage/mismatch behavior.

## 55-document comparison

| Metric | Documents |
|---|---:|
| documents_total | 55 |
| fact_based | 16 |
| fallback_used | 39 |
| conflict | 3 |
| multiple_candidates | 0 |
| no_event | 0 |
| same_classification | 52 |
| changed_classification | 3 |

Fact-based classification is **16/55 (29.1%)**; metadata fallback is **39/55 (70.9%)**. V1 used title/source/URL classification for all documents. V2 preserves 52 type classifications while grounding 16 in DI evidence. Three type changes are explicitly flagged as conflicts. Metrics overlap: a changed document can also be fact-based/fallback and conflicted.

All 55 runs completed and all 55 messages were published. Zero dead inputs/failed runs. All published JSON payloads exactly match NATS and reproduce from frozen inputs/configuration. Independent provenance checks verified **18 fact references, 73 actor references and 10 measurement attachments** against DI-1. All 55 saved snapshots lack a full-body field. Every event_time is null in this corpus; no publication timestamps were substituted.

No real multi-candidate/no-event documents occur in these 55 inputs. Both paths are tested with fixtures. Same-version research replay reported 55 duplicates and created no result.

## All changed classifications

| Document | v1 | v2 | Basis | Conflict |
|---|---|---|---|---|
| ECB Consumer Expectations Survey results – August 2026 | central_bank.other | central_bank.data_release | primary_fact | yes |
| SEC: 38 Entities Feigned Legitimacy as U.S. Advisers Through False Filings to Lure Retail Investors | regulator.other | regulator.enforcement | primary_fact | yes |
| SEC Announces Departure of Principal Deputy Director of Enforcement Sam Waldon | regulator.enforcement | regulator.personnel | fallback_rule | yes |

The personnel correction is a narrow configured fallback precedence fix, not a newly extracted fact. The other two changes use actual DI facts. The ECB survey evidence concerns **perceived inflation**, not an official CPI actual. All source wording, rule IDs and evidence spans remain available.

## Manual checks

| Example | v2 basis | Assessment |
|---|---|---|
| Fed FOMC | primary_fact | Rate-decision evidence explicitly supports policy_statement; only fact-linked rate range/change retained. Date/header clock fragments are not combined into an invented exact event_time. |
| Fed projections | fallback_rule | No projection domain fact in DI-1. Kept projections via explicit legacy metadata fallback; no synthetic projection fact or incidental measurement. |
| ECB speech | fallback_rule | No mapped financial facts. Speech remains fallback; incidental numbers/entities do not create a policy decision. |
| ECB interview | fallback_rule | No extracted domain facts. Interview remains fallback. Existing facts_correct=false incompleteness label is shown for evaluation only. |
| SEC proposal | primary_fact | Explicit proposed Regulation E-Delivery sentence supports regulator.rule_proposal despite partial RSS. |
| SEC enforcement | primary_fact | Explicit charged sentence supports regulator.enforcement. No unlinked numbers from the article are added. |
| SEC personnel | fallback_rule | A departure from the Enforcement department is personnel, not an enforcement action. Narrow fallback override corrects it, records v1 disagreement, and aligns with the existing negative event_type label. |
| Crypto-related SEC | fallback_rule | DI-1 has no extracted proposal fact despite the visible crypto proposal. Retain regulator.rule_proposal as fallback; no invented crypto fact. Negative facts_correct label remains an evaluation signal. |
| Changed SEC false filings | primary_fact | Body fact explicitly says the SEC charged 38 entities; supports enforcement rather than generic other. Full provenance is visible. |
| Changed ECB survey | primary_fact | Body evidence reports perceived inflation over the previous 12 months from the survey. Data-release classification is supported. This is not asserted to be an official CPI actual or a policy decision. |

## Human-review alignment

Five existing DI-2 labels were frozen as evaluation signals. The one negative `event_type_correct` label (SEC personnel) corresponds to a changed v2 type and visible conflict; manual inspection confirms the personnel reading. The three positive event-type labels retain their v1 types. One other label has no event-type verdict. Two `facts_correct=false` incompleteness labels remain visible; v2 does not invent missing facts or train on these labels. This small, selected review sample is not an accuracy benchmark.

## Immutable history / dashboard

HTTP baseline checks confirm unchanged: 55 v1 events, 55 revision histories, 55 extraction histories, all 55 DI outputs and all 55 routing results with their existing five human labels. Legacy Event Intelligence and all three paid Astra analyses/frozen inputs/audits also match their prior baseline. LLM still has four jobs and three provider attempts; DI-3 made zero model requests.

Browser verification on News Detail (SEC personnel) and Event Detail (SEC false filings) confirmed the read-only Event Engine Comparison block, primary/fallback basis, conflicts, expandable exact fact evidence and frozen human evaluation. No new labels were written. Missing/unavailable research is explicit and leaves the article/review form usable.

## Known limitations / deviations

- This is an isolated research service/database (port 8011), intentionally not an in-place production Event Engine switch. Merge is disabled as allowed by the specification.
- DI-1 fact coverage limits v2: projections, speeches/interviews and some crypto proposals still require fallback. Partial SEC RSS and extraction incompleteness remain visible; this stage does not repair DI-1.
- Metadata-only read endpoints were added to DI-1 and Article Router to avoid transferring document bodies or reading service databases. No old public message contract or stored result changed.
- Within a document, same-type/subject/action facts share a candidate; different types remain separate. This is bounded extraction grouping, not semantic event correlation.
- Exact event time requires an explicitly linked timezone-qualified datetime. Date-only or unlinked dates remain evidence, not an invented instant.
- Economic-data mapping uses the current central-bank corpus taxonomy; extending sources/domains requires a deliberate versioned mapping update.
- Classification disagreement is audit-visible even when a v1 generic fallback becomes a specific event. A changed type alone is not proof of improved accuracy.
- Human evaluation is frozen at research time, not automatically refreshed or used to change results. New semantic policies require a new ruleset research run.

Full payloads, comparisons, IDs, hashes and checks: [event-engine-v2-verification.json](event-engine-v2-verification.json). Architecture/API: [event-engine-v2.md](architecture/event-engine-v2.md).
