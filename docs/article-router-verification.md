# DI-2 verification

Verified: 2026-09-20T08:09:54.977583+00:00

## Implementation, rules and schema

Independent Article Router, own `article_routing` DB, strict `article.routing.v1`, versioned ruleset/high-value registry 1.0. Every feature has an explicit basis. Immutable machine results, append-only human labels and transactional outbox. Required DI evidence and optional event metadata are obtained over HTTP. No LLM/trading integration.

## Tests and regression

| Suite | Passed |
|---|---:|
| llm-analysis-tests | 60 |
| tests | 40 |
| document-intelligence-tests | 55 |
| market-data-tests | 56 |
| event-intelligence-tests | 24 |
| events-tests | 103 |
| evaluation-tests | 46 |
| market-context-tests | 105 |
| enrichment-tests | 95 |
| article-router-tests | 27 |
| dashboard-tests | 40 |

**651 tests passed**, including 27 new backend tests and 40 dashboard tests (177 assertions). Coverage includes requested route cases, partial/no-fact documents, novelty, strict schema, duplicate/conflicting inputs, version isolation, immutable label history, stale/concurrent review conflicts, auth, metadata outage, stale worker leases, outbox retry, dashboard filters/search and outage fallback. The isolated test broker was stopped after regression.

## 55-document real smoke

55 completed; 55 published; zero dead inputs or failed runs. All 55 payloads match JetStream exactly and reproduce from their frozen snapshots/configuration. All optional metadata resolved without warnings in this run. Restart and replay retained 55 results, with 55 duplicates and no new result.

| Route | Count |
|---|---:|
| critical | 0 |
| important | 9 |
| review | 45 |
| low | 1 |
| archive | 0 |

### By source

| Group | critical | important | review | low | archive |
|---|---:|---:|---:|---:|---:|
| ecb_press | 0 | 3 | 12 | 0 | 0 |
| fed_monetary_policy | 0 | 4 | 11 | 0 | 0 |
| sec_press_releases | 0 | 2 | 22 | 1 | 0 |

### By topic

| Group | critical | important | review | low | archive |
|---|---:|---:|---:|---:|---:|
| capital_markets | 0 | 0 | 8 | 0 | 0 |
| economic_growth | 0 | 0 | 2 | 0 | 0 |
| enforcement | 0 | 0 | 7 | 1 | 0 |
| inflation | 0 | 1 | 0 | 0 | 0 |
| interest_rates | 0 | 6 | 0 | 0 | 0 |
| monetary_policy | 0 | 6 | 10 | 0 | 0 |
| none | 0 | 1 | 14 | 0 | 0 |
| regulation | 0 | 1 | 13 | 0 | 0 |
| wages | 0 | 0 | 1 | 0 | 0 |

### By fact type

| Group | critical | important | review | low | archive |
|---|---:|---:|---:|---:|---:|
| economic_data.inflation | 0 | 1 | 0 | 0 | 0 |
| monetary_policy.rate_decision | 0 | 6 | 0 | 0 | 0 |
| none | 0 | 2 | 36 | 1 | 0 |
| regulation.enforcement | 0 | 0 | 7 | 0 | 0 |
| regulation.rule_proposal | 0 | 0 | 2 | 0 | 0 |

Topics combine frozen DI and canonical event metadata; multi-topic articles occur in multiple rows. Fact-type counts are documents containing each distinct type, not fact occurrences. `none` means no extracted fact/topic; it does not assert no real-world information exists.

## Required examples

| Example | Route | Facts / measurements | Basis |
|---|---|---:|---|
| [SEC Waldon departure](http://localhost:8006/admin/news/3a776ca3-c2ad-5a38-b049-b04ef5919207) | low | 0 / 0 | router.sec.personnel_exception |
| [SEC E-Delivery proposal](http://localhost:8006/admin/news/7c7daef8-cc6c-5a2a-bd6f-bf7bd02efd8e) | review | 1 / 0 | conservative default |
| [SEC Crypto Assets proposal](http://localhost:8006/admin/news/bfc7384a-9768-59b3-bd37-6fbb0da14b2c) | important | 0 / 0 | router.sec.crypto_proposal |
| [ECB Cipollone speech](http://localhost:8006/admin/news/0022517e-78bd-5ef0-95bb-82964ffb2ea9) | review | 0 / 4 | router.central_bank.commentary |
| [Fed FOMC 2026-04-29](http://localhost:8006/admin/news/9c6fc2a9-2e2c-55b3-8631-b3ac15ed83b5) | important | 1 / 4 | router.monetary_policy.rate_decision |
| [ECB Ouest-France interview](http://localhost:8006/admin/news/a3c5cdc4-5478-5698-9f09-a8c367638578) | review | 0 / 4 | router.central_bank.commentary |

## Manual review smoke and dashboard

Five real articles were reviewed by Codex through the authenticated News Detail UI, using the displayed text and expandable evidence. Each Save review showed confirmation; labels remained visible after service restart. Comments explicitly identify the smoke reviewer as Codex; the session account is `research@local.test`.

| Article | Usefulness | Priority | Facts correct | Send to LLM | Status |
|---|---|---|---|---|---|
| SEC Waldon departure | not_useful | low | true | false | dismissed |
| SEC E-Delivery proposal | useful | review | true | false | reviewed |
| SEC Crypto Assets proposal | useful | important | false | false | reviewed |
| Fed FOMC 2026-04-29 | useful | important | true | true | reviewed |
| ECB Ouest-France interview | useful | review | false | false | reviewed |

For crypto proposal/interview, `facts_correct=false` records incomplete extraction (missing visible claims), as explained in their comments; it is not a claim that an extracted assertion was fabricated. Personnel labels also flag the pre-existing canonical enforcement-type error without editing that event.

All **55 machine hashes and all 55 frozen-input hashes are unchanged** after these saves. Exactly five append-only labels exist; one `send_to_llm=true` flag caused no job/provider request. Existing 55 legacy Event Intelligence results and all three paid Astra analyses with their frozen inputs/audits are unchanged. LLM still has four jobs and three provider attempts.

News Feed default shows 54 queue articles; all 55 remain accessible under All. Filters cover route/source/topic/status/date/language and title search. News Detail displays full observed body, exact DI evidence, per-feature reasons, frozen canonical metadata and review history. No upstream write controls exist.

## Known limitations and deviations

- Deterministic bootstrap rules, not a calibrated relevance model. No critical/archive real examples occur in this corpus; those routes are covered by synthetic tests.
- DI-1 misses some financial claims and SEC inputs remain partial RSS. Routing does not repair extraction or verify historical HTML; limitations remain visible.
- Two source-scoped SEC metadata/title fallbacks are explicit. This is narrower than semantic crypto classification and does not create synthetic facts.
- Novelty is canonical-history/source-lineage only. Missing optional metadata is frozen as unavailable for that run; improved metadata requires a new ruleset research result.
- Identity adds the DI intelligence ID and high-value registry version to avoid collisions. Review items are also retained for low/archive so those articles can be reviewed explicitly.
- Feed filtering is local to a capped 1,000-record catalogue; backend listing is intended for the current small research corpus.
- Human labels are subjective review annotations; `send_to_llm` remains an inert flag. No model router, automatic learning, signals or trading was added.

Machine-readable distributions, all 55 IDs/hashes, labels and audit proofs: [article-router-verification.json](article-router-verification.json). Architecture/API/research replay: [article-router.md](architecture/article-router.md).
