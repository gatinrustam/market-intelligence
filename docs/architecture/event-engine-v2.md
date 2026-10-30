# DI-3 — Event Engine v2 research

## Scope and deployment

`document.intelligence.v1` → **event-research** (localhost:8011) → `event.research.v2` / `EVENT_RESEARCH_V2` JetStream stream. This is a parallel extraction research service, not a replacement for the production Event Engine. `event.canonical.v1`, existing event IDs/revisions, correlation and downstream consumers remain unchanged. All v2 payloads explicitly say `mode=research`, `production_canonical=false`, `merge_enabled=false`.

A separate service/database is an intentional isolation choice: the same v1/v2 comparison can run without modifying the production core or migrations. No LLM, embeddings, semantic correlation, model router, learning, signals or trading.

```sh
docker compose up -d --build document-intelligence article-router event-research dashboard
./scripts/test-event-research.sh
./scripts/test-dashboard.sh
docker compose exec -T event-research python < scripts/smoke-event-research.py
```

`EVENT_RESEARCH_DB_PASSWORD` and `EVENT_RESEARCH_RULES_PATH` are configurable in root `.env`. The service database user is limited to its own `event_research` database (and the disposable test database provisioned by the test script).

## Input and provenance boundary

The consumer validates the strict DI-1 contract and internal links between facts, relations, entities, evidence and measurements. A required read-only `GET /intelligence/{id}/metadata` projection in DI-1 returns title, source/URL, publication timestamp, enrichment status, length and hashes; it does **not** return `content.body`. V2 verifies the exact DI hash, extraction versions and document/input/source-message/body-hash references.

The existing Events HTTP APIs provide immutable extraction candidates and canonical revisions for comparison. A failed/incomplete v1 baseline retries the research run instead of fabricating a baseline. Article Router adds read-only `GET /documents/{id}/reviews`; matching-DI human labels and the v1 types actually reviewed are frozen as evaluation data. Missing review metadata is explicit. No cross-service database access occurs.

The research input contains the DI payload and evidence snippets, not the complete enriched document. Evidence can naturally span an entire short RSS excerpt; no independent full-body field is fetched or copied. Old DI/Router output contracts and stored results are unchanged by their new read projections.

## Extraction policy 2.0

`config/event_research/rules.v2.json` freezes the fact mapping, a copy of legacy title/source/URL rules and the narrow research override for the known SEC personnel departure.

- `monetary_policy.rate_decision` → `central_bank.policy_statement`.
- `regulation.rule_proposal` / `rule_adoption` / `enforcement` → corresponding regulator types.
- Economic release facts map to the current corpus's `central_bank.data_release` type.
- Crypto withdrawal/outage/security/depeg facts map to separate market-infrastructure event types; treasury and ETF facts have their own types.
- Asserted, mapped domain facts are primary; a forward-looking relation is not silently made an asserted event.
- Candidates are grouped **within a document** by event type, DI subject and action, preserving all fact references and values. Different types remain separate; no cross-document/source/date merge is performed.
- Matching metadata rules are `supporting_rule` signals when facts exist. With no eligible facts, metadata classification is explicitly `fallback_rule` and creates no synthetic facts or measurements.
- The source-scoped SEC personnel rule corrects an explicitly worded departure whose department name contains “Enforcement”. It is configuration, not learned from human labels. Its disagreement with the immutable v1 result remains visible.

Fact references include document/fact/relation IDs, fact type, exact span/text and extractor/rule version. Only DI entities are used; registry entities remain canonical and mention entities remain unresolved with their original DI IDs. Fallback issuer resolution requires an existing DI entity, not a new Event Engine registry ID.

Only measurements present in a candidate's linked facts are attached. Topics from DI must reference those facts. Dates must be contained within a relevant fact span; event time is populated only for a unique explicitly normalized, timezone-qualified datetime. Date-only values, publication times and incidental dates do not become exact event time. Missing/ambiguous time stays null.

`classification_conflict` preserves the selected types plus disagreeing v1/strongest metadata alternatives, rule IDs and fact IDs. A fallback `other`→specific-fact change is also reported as a conflict for audit; this flag means a classification disagreement, not necessarily a logical contradiction in the document.

## Contracts, storage and replay

Strict machine contract: `contracts/event/research/v2.schema.json`. Comparison DTOs are separately validated before persistence. Own tables:

- `v2_inputs`: exact DI message, hash, JetStream provenance.
- `v2_rulesets`: immutable version/configuration/hash binding.
- `v2_extraction_runs`: recoverable leases, frozen inputs/configuration, status.
- `v2_candidates`, `v2_results`, `v1_v2_comparisons`: immutable completed research output.
- `outbox_events`, `dead_inputs`: durable publication and input failures.

Result, candidates, comparison and outbox commit atomically. Stale workers cannot commit. Input identity is DI intelligence ID; research identity is DI intelligence ID + ruleset version. Reusing a ruleset version with different content fails closed. New versions produce separate history.

After deploying a new versioned rules file, replay persisted inputs without relying on broker retention:

```sh
docker compose exec -T event-research python -m app.research
```

Same-version replay is idempotent. Classification-semantic code changes require a new ruleset version. Human review changes do not rerun or rewrite existing results. Human labels are excluded from extraction decisions and the extraction context hash, but preserved in the immutable comparison snapshot as evaluation signals. Their `facts_correct`/`event_type_correct` flags are not a complete ground-truth taxonomy.

## Read-only API and dashboard

- `GET /health`, `/ready`, `/stats`
- `GET /research?offset=0&limit=100`
- `GET /research/{research_id}` — result, comparison, frozen snapshot and configuration.
- `GET /documents/{document_id}/comparison` — all research versions for that document.

No HTTP mutation endpoint exists. News Detail and Event Detail include **Event Engine Comparison**, pinned to the exact document input (and DI identity on News Detail). It displays v1/v2 types and basis, primary facts with expandable evidence, fallback/conflicts and frozen human evaluation. Existing DI-2 label writes remain independent. Outage/empty/mismatched research data is explicit and does not hide the article or existing review form.

## Limits

V2 can only classify from facts DI-1 extracted; it does not repair missing or inaccurate extraction. Exact time remains unknown when DI supplies no unambiguous linked datetime. Novel domains require deliberate mapping/taxonomy updates. The current economic-data mapping is scoped to the Fed/ECB/SEC research corpus. Current metadata/comparison listing uses bounded HTTP catalogues and is intended for this small local corpus.

See [verification and manual review](../event-engine-v2-verification.md) and [all 55 machine results/comparisons](../event-engine-v2-verification.json).
