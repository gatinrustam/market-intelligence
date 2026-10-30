# DI-4 — Correlation v2 verification

Verified 2026-09-20. Parallel research only; production v1 remains authoritative.

## Implementation

Correlation runs inside Event Research as an isolated worker with separate persistence, a versioned configuration and read-only APIs. Canonical research IDs remain stable across exact additions; revisions and pair decisions are immutable. Suggestions are separately stored and never merged. No raw-body analysis, LLM, vector search, semantic merge, Story Group or manual merge UI.

[Architecture, identity policy, deployment and APIs](architecture/correlation-v2.md).

## Fingerprint rules

`fact_identity_v1` / `correlation_v2.1`, pinned to DI-3 extraction ruleset `2.0`. Exact rate identity requires event type, canonical primary actor, asserted action, normalized linked values and explicit event timestamp. Measurements normalize with Decimal; rate levels and rate changes remain different dimensions. Additional dates/objects/actors guard against conflicts. Publication time never supplies identity.

Date-only mentions guard against contradictory dates but do not replace a missing event timestamp. `strong_match` is reserved and disabled. Other event types need deliberate exact-rule configuration before auto-merge.

## Tests and regression

**717 tests passed**, including **58 Event Research tests** (29 existing + 29 DI-4) and **48 dashboard tests / 200 assertions** (44 existing + 4 DI-4).

| Suite | Passed |
|---|---:|
| Ingestion | 40 |
| Enrichment | 95 |
| Events v1 | 103 |
| Market Data | 56 |
| Market Context / causal / decision / freshness | 105 |
| LLM Analysis | 60 |
| Evaluation | 46 |
| Event Intelligence | 24 |
| Document Intelligence | 55 |
| Article Router | 27 |
| Event Research / Correlation v2 | 58 |
| Dashboard | 48 |

DI-4 checks same facts merge, value/date/type/action/actor conflicts, normalized units/timezones, unknown units/unresolved entities, no identity from actor/day/title alone, missing-date suggestions, duplicate idempotency, conflicting input rejection, concurrent exact arrivals, immutable revisions, source counts, version isolation, preserved provenance, read-only API and processing documents with no candidates. Dashboard checks display, escaped content, missing results, outage and provenance mismatch. Pint passed. Existing upstream deprecation warnings do not fail tests.

## Synthetic correlation results

Fixtures are explicitly synthetic and run only in the disposable test database. Full inputs, stored revisions, decisions and metrics are included in the JSON report.

| Scenario | v2 events | Result |
|---|---:|---|
| Three formulations of one Fed rate decision | 1 | 3 documents, 2 distinct source IDs, revisions 1–3, 2 merges / 3 exact pairs |
| Rate ranges 3.50–3.75% vs 4.25–4.50% | 2 | separate: measurement conflict |
| Same meeting: policy statement + projections | 2 | separate: event type |
| SEC proposal + enforcement on same day | 2 | separate: event type/action |
| Matching facts, missing explicit date | 2 | suggestion; zero merges |

The actual v1 `exact_key`/`suggestion` functions were also invoked on an explicit-date synthetic adapter. v1 gives 1 event for the different-rate-values scenario because its identity key does not include measurements; v2 gives 2. Other synthetic event counts agree. This is a **policy-level comparison**, not a rerun of v1 article extraction and not evidence that the current real corpus suffered a false merge. Synthetic supplied dates/namespaces are documented in the adapter.

## Real 55-candidate smoke

55 documents / 55 candidates processed; **55 research canonical events** remain. Real v1 likewise has 55 events and no stored correlation suggestions.

| Measure | Count |
|---|---:|
| Exact merges | **0** |
| Exact pair matches | 0 |
| Strong matches | 0 |
| Suggestions | **3** |
| Separate pairs / rejected merges | 1,359 |
| Insufficient-data pairs | 123 |
| All evaluated pairs | 1,485 |

Conflict fields: type 1,347; actor 77; action 92; measurements 17; explicit linked dates 3. Counts overlap. Most rejected pairs are obvious different types; these counts are not a quality/precision score.

All **55 projections/fingerprints**, **1,485 pair decisions** and **55 revisions** verified from frozen inputs. Repeated research run processed **0 new results**. Existing **55 DI-3 results and snapshots**, **55 v1 events and all revision/extraction histories**, **55 DI outputs**, **55 routing results including human labels**, **55 legacy Event Intelligence results** and **3 paid Astra audit/input packages** remain unchanged. LLM remains 4 jobs / 3 provider attempts; no new requests.

## Suggestions and conflict examples

- ECB “Monetary policy decisions” and “Christine Lagarde, Boris Vujčić: Monetary policy statement (with Q&A)”: matching fact actor/action/measurements; publications 45 minutes apart; missing exact fact timestamp → suggestion, not merge.
- Fed April 29 vs June 17, and April 29 vs July 29: same hold/rate facts, missing complete date identity → two suggestions. Publication distances are **49 and 91 days**, explicitly marked outside proximity. These are weak research suggestions, not duplicates; all events remain separate. Current proximity is supporting, not a suppression filter.
- Fed September 16 vs June 17: different action, rate values and explicit linked dates → separate.
- Policy statement vs projections: different type → separate even with the same issuer/meeting.
- SEC proposal vs enforcement: type/action conflict → separate.

## Dashboard

Read-only **Correlation** appears on News Detail and Event Detail. It displays research event/revision, mode, fingerprint/version, document/source counts, linked documents, separate suggestions and matched/conflicting pair fields. The expanded Fed suggestion visibly shows its long publication distance and `publication_proximity=false`. No manual merge control or model request was added.

## Known limitations and deviations

- Implemented as an isolated module/worker within Event Research, not an additional microservice. No production/public DI-3 contract change or new NATS output required.
- Exact auto-merge currently configured only for rate decisions; other types remain conservative. Date-only DI mentions lack semantic roles, so exact identity requires a linked explicit timestamp. This may miss legitimate matches.
- Two distant Fed suggestions demonstrate limited suggestion precision. They cannot cause automatic merges.
- Pairwise O(n²) research and a per-policy transaction lock target this small corpus, not production throughput.
- Different source IDs are only a technical count, not proof of independent publishers.
- Synthetic v1 comparison isolates the actual correlation functions using supplied structured identity; it does not test v1 extraction recall.
- No strong auto-merge, LLM correlation, embeddings, semantic grouping, manual merge or trading.

[Complete machine report, synthetic fixtures and pair audit](correlation-v2-verification.json).
