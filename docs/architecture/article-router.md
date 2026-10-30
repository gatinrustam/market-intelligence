# DI-2 — Article Router / Review Queue

`document.intelligence.v1` → Article Router → `article.routing.v1`. Local port 8010; own MariaDB database/user `article_routing`. No LLM clients, signals, trades, embeddings or learning from labels.

## Persistence and reproducibility

- `routing_inputs` preserves exact received JSON, semantic hash and JetStream provenance.
- `routing_rulesets` binds a version to immutable configuration, including the high-value registry. Reusing a version with changed contents is rejected.
- `routing_runs` uses recoverable leases. Completion atomically inserts `routing_results`, `review_items`, and `outbox_events`.
- `routing_results` and completed input/configuration snapshots have no update API. Every result contains input, configuration and snapshot hashes.
- `human_labels` is append-only. `review_items` contains the current human workflow status/revision, independent of machine route. No label changes any upstream service.
- Identity includes document ID, DI intelligence ID, DI pipeline version, router ruleset version and high-value registry version. The DI ID is an intentional extension to the minimum identity: separate DI fact/registry versions must not collide.
- A new router ruleset creates a separate result and review item; older results/labels remain available by routing ID. The default feed selects the latest generated result per document.

The durable consumer replays retained messages on a new configuration. To research **already persisted inputs** without relying on NATS retention, deploy a new versioned rules file through `ARTICLE_ROUTER_RULES_PATH`, restart the router, then run:

```sh
docker compose exec -T article-router python -m app.research
```

This only queues missing results under that configuration; it never replaces history. Semantic algorithm changes also require a new ruleset version. Optional metadata is observed at research-run time and frozen, not claimed to have existed historically at publication.

## Rules and feature basis

`config/article_router/rules.v1.json` and `high_value_facts.v1.json` are frozen together. Rules use conjunctions of configured source, fact types, event types, topics, upstream rule IDs and bounded title patterns. The highest-priority matching rule supplies the route; every match is recorded. No opaque total score.

Rate decisions and numerical economic claims are important. Withdrawal suspension, security incident and depeg facts are critical. Crypto regulatory facts with digital-asset context are important. Personnel without other high-value facts is low. Central-bank commentary without high-value facts is review. Exact service notices without financial facts are archive. Otherwise conservative review; unknown-source inputs without facts can be low.

Two explicit SEC context fallbacks address current DI-1 gaps: exact crypto-proposal title + canonical proposal classification, and pinned `sec.tokenized_nms_exemption` metadata. The existing personnel exception distinguishes a departure from enforcement. These rules do not manufacture DI facts or edit canonical types.

Every feature stores a reason, input paths, rule IDs and applicable fact IDs. Financial/high-value counts use distinct exact signatures (type, action, subject, normalized values); measurements count evidenced occurrences. Density uses configured count thresholds across financial facts, measurements, relations and registered entities; text length does not raise density. This is a bounded heuristic, not a semantic novelty or completeness model.

Source quality is a static registry. Document quality separately reflects enrichment/DI completeness. `complete` means the extraction completed, not that every real-world fact was extracted. Novelty only uses exact source-message repetition and pinned canonical-history metadata; otherwise unknown. NATS redelivery is not novelty.

## HTTP boundaries

Required enriched input is read through DI's frozen-input HTTP API; document/message/source lineage and body/input/configuration hashes are checked. Canonical events and compatible Event Intelligence are optional HTTP reads; failures produce explicit warnings and conservative fallback. Their selected payloads are frozen. No other service database is queried.

- `GET /health`, `/ready`, `/stats`
- `GET /articles?offset=0&limit=100` — latest result per document, queue metadata.
- `GET /articles/{routing_id}` — machine result, frozen document/DI/context/configuration, current review and append-only label history.
- `GET /routing/{routing_id}` — exact machine payload.
- `POST /reviews/{routing_id}/labels` — the only HTTP write, strict label request.

Strict output contract: `contracts/article/routing/v1.schema.json` (unknown fields forbidden throughout). Read endpoints are loopback-bound/internal, matching the existing local services. Label writes require the shared `ARTICLE_ROUTER_REVIEW_TOKEN`; missing configuration fails closed. Dashboard requires its existing login/session/CSRF protection and supplies the authenticated reviewer. Token stays server-side.

Labels use UUID `request_id` and `expected_revision`. Identical retries return the original revision. Reused IDs with changed data and concurrent stale revisions return 409. On uncertain network completion the UI keeps the original operation for safe retry. `send_to_llm` is only a stored flag and has no downstream consumer in DI-2.

## Dashboard

`/admin/news-feed`: default critical/important/review; low/archive retained under Visibility → All. Title search and route/source/topic/review-status/publication-date/language filters. Topics combine evidenced DI topics and frozen canonical topics. Filters/search apply to a capped 1,000-record catalogue, with an explicit cap warning.

`/admin/news/{routing_id}`: full observed text, DI facts/measurements/entities/topics with expandable evidence, all routing reasons, frozen event context, review form and label history. Machine route and human priority override are separate. Reviewer labels are subjective research annotations, not verified trading facts.

## Verification

Run `scripts/test-article-router.sh` and dashboard tests. Run backend suites sequentially because they share the isolated test broker. `scripts/smoke-article-router.py` runs inside the router and verifies all 55 current results against NATS and reproduces their payloads from frozen snapshots/configuration. Results and manual UI verification: `docs/article-router-verification.md` / `.json`.
