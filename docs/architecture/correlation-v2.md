# DI-4 — Correlation v2 (research only)

## Implementation and boundaries

DI-4 runs as a separate worker/module within the existing **event-research** service (8011), with its own `correlation_*` tables. It polls completed immutable DI-3 runs. It does not replace the production Event Engine or publish production events. DI-3's `event.research.v2` contract and `merge_enabled=false` remain unchanged: that flag describes extraction, not DI-4's isolated research canonical store.

The internal input projection selects each v2 candidate, its exact primary/supporting fact-linked relations and canonical actors from the frozen DI snapshot, document/source/title/publication metadata, versions, input hash and observed v1 event IDs. It verifies the DI hash/document provenance. It never analyzes raw article text or forwards a full article body. Evidence snippets and structured relation arguments are retained for audit. Human labels are not inputs.

Own storage:

- `correlation_policies`: immutable configuration/version binding, also the per-policy transaction lock.
- `correlation_processed`: atomic DI-3 result checkpoint, including zero-candidate results.
- `correlation_candidates`: immutable projection, fingerprint, source candidate and event association.
- `correlation_decisions`: immutable explainable pair decisions, versioning, document IDs and v1 same-event comparison.
- `correlation_suggestions`: separate records; never applied as merges.
- `correlation_events`: stable research event ID and latest revision pointer.
- `correlation_revisions`: append-only canonical research revisions, documents, source counts and merge-decision references.

A single transaction includes all decisions, candidate membership, canonical revision, suggestions and processing checkpoint. A per-policy row lock serializes concurrent arrivals, including the first exact identity; no absent-row race can create duplicate events. A retry reuses the same candidate/checkpoint. Conflicting input under an existing candidate ID fails closed. All existing group members must agree exactly; no transitive suggestion/partial-match bridge is allowed.

New supporting documents keep the event ID and append a revision. Multiple candidates from the same document preserve candidate provenance without inflating document/source counts. `independent_source_count` is strictly the number of distinct source IDs, not a claim of publisher independence.

## Fingerprint policy

Configuration: `config/event_research/correlation.v1.json`.

- Ruleset: `correlation_v2.1`.
- Fingerprint: `fact_identity_v1`.
- Input extraction ruleset pinned to `2.0`.
- Exact auto-merge is enabled **only for rate decisions** (`central_bank.policy_statement` / `monetary_policy.rate_decision`). Other types remain separate candidates with pair decisions/suggestions until deliberate identity rules are added.
- Mandatory exact fields: same type, resolved primary actor, asserted action (`hold`, `raise`, `cut`), linked normalized measurements and explicit event timestamp.
- Objects, linked explicit dates and jurisdiction (when available) are additional conflict guards. Topics are preserved as supporting data, not mandatory rate identity.
- Rate levels normalize percent / basis points / fractional units using Decimal, including numeric ranges. Rate changes stay a separate dimension. Unknown units, incomplete values, ambiguous actors/actions/dates cannot establish exact identity.
- Date-only DI mentions are **conflict guards**, not automatic event identity: upstream does not distinguish meeting/publication/effective-date roles. Exact identity currently requires v2's explicit fact datetime. Publication is never substituted. This conservative restriction is intentional.
- All measurements are compared, not just the first value. Different values/actions/types/explicit dates/actors/objects cause `separate`, regardless of title similarity.
- Without conflicts, matching fact type/actor/action/measurements with incomplete exact identity yields `suggestion`. Same actor/day/title alone yields `insufficient_data`.
- `strong_match` is reserved in the controlled enum but not emitted/auto-merged in this policy.

Features include same type/actor/action, measurement/date agreement, topic overlap, title token Jaccard, publication distance and configured proximity. There is no opaque aggregate probability. Proximity is supporting only and does not suppress all distant suggestions; the real corpus demonstrates two such low-value suggestions. No suggestion is a claim that the events are identical.

Fingerprint component hashes are separate from the exact grouping key. The latter includes configured required fields and all conflict guards. Ruleset/fingerprint/input-rule versions scope storage and event IDs. Reusing the same version tuple with different configuration is rejected. Semantic implementation changes require a new policy version; never rewrite stored revisions.

## Read-only API / dashboard

- `GET /correlation/stats`: corpus and pair counts for the configured policy.
- `GET /correlation/events`: current research canonical events.
- `GET /correlation/events/{id}/revisions`: immutable history, including historical policies.
- `GET /correlation/decisions?mode=suggestion&offset=0&limit=100`: paginated pair audit.
- `GET /documents/{id}/correlation`: all stored policy versions for that document, event, fingerprint, decisions and suggestions.

The **Correlation** section on News Detail and Event Detail checks exact document/input provenance and research flags. It displays modes, fingerprint, linked documents/source count, matched/conflicting fields and separate suggestions. There is no manual merge action. Service outage, missing input and mismatched provenance are explicit; existing review UI remains independent.

## Deployment and repeatability

```sh
docker compose up -d --build event-research-migrate
docker compose up -d --build --no-deps event-research dashboard
./scripts/test-event-research.sh
./scripts/test-dashboard.sh
docker compose exec -T event-research python -m app.correlation.research
docker compose exec -T event-research python < scripts/smoke-correlation.py
```

Migration `di4001` creates only the new tables. Build the migration image as well as runtime when deploying changes. `EVENT_RESEARCH_CORRELATION_RULES_PATH` selects another versioned policy. A new version reprocesses completed DI-3 inputs into its own event/revision namespace. Same-version replay is a no-op.

## Metrics and limits

`events_before_correlation` counts candidates; `events_after_correlation` counts research canonical events. `exact_merges` is their difference, **not** the number of exact pairs. Three exact documents yield three exact pair decisions, two merges and one event. Conflict reasons overlap. `rejected_merges` counts conflicting evaluated pairs, including obvious different-type pairs; it is not a count of near-duplicate false positives prevented. Merge rate is not a quality score.

All-pairs O(n²) evaluation and a per-policy transaction lock suit the current 55-candidate research corpus, not a high-throughput production rollout. There is no LLM, embedding, vector database, semantic judge, story grouping, manual merge, signal engine or trading. No new broker contract/service was needed; future production adoption remains a separate decision.
