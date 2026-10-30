# Stage 5.5 — Event Intelligence

Independent deterministic service on localhost:8008. It consumes retained canonical `event.detected.v1` / `event.updated.v1` messages from the EVENTS stream and publishes strict `event.intelligence.v1` into EVENT_INTELLIGENCE. No LLM, consensus provider, trade, signal or PnL is involved.

## Rules and meaning

Versioned configuration lives in `config/event_intelligence/rules.v1.json` (1.0) and `rules.v1.1.json` (active 1.1). Ordered selectors combine event type, source, canonical rule IDs, topics and narrowly scoped title patterns. Worker logic does not contain event-specific rules. `digital_assets` supplies a high relevance floor. A source-scoped exact SEC tokenized-NMS exemption rule supplies medium relevance even when Stage 2 lacks that topic.

- Fed policy statements/minutes/projections: high BTC relevance, specific.
- Other central bank policy: medium, specific. Speeches: medium, commentary. Interviews: low, commentary.
- SEC enforcement: low, specific; personnel: low, general. Digital-asset evidence can raise relevance.
- Quality combines evidence quality, trusted source/type, enrichment readiness, independent sources and corroboration. Partial evidence caps quality. This is not statistical confidence.
- Novelty uses exact canonical revision/correlation history. First `new_event` revision is new; exact-key revision updates are update; unchanged semantic event plus no new document content hashes is duplicate_like. Unsupported correlation is unknown. No fuzzy merge, global novelty claim, or comparison against information outside this history.
- Without an external provider, surprise is unavailable and all expectation fields are null. The strict schema includes nullable decimal-string expectations and future source provenance.

Stage 2 currently labels the Sam Waldon departure as enforcement because the job title includes “Enforcement.” Ruleset 1.1 adds an anchored, SEC-only personnel announcement exception. Its intelligence specificity is general; the canonical taxonomy and all 1.0 results remain untouched.

## Persistence and recovery

Own logical DB `event_intelligence`; migration `i55001`. Tables: intelligence_rulesets, intelligence_inputs, intelligence_runs, intelligence_results, outbox_events, dead_inputs. Identity is event ID + revision + BTCUSDT + ruleset version, using deterministic UUIDs. Registry binds each version to a normalized configuration hash; changing configuration under the same version fails.

Input is acknowledged after durable acceptance. Exact canonical payload, publication metadata, immutable evidence and previous canonical revision are pinned. Result records include canonical/input/configuration hashes and evidence hashes. Lease-fenced completion atomically saves result and outbox. Outbox retries broker failures, uses stable message IDs and validates the strict schema. New ruleset consumer durables replay retained EVENTS; duplicate input does not create duplicate results. Explicit research POST is idempotent and only accepts the active version. Old results are never rewritten.

## APIs

- GET `/health`, `/ready`, `/stats`
- GET `/intelligence/{intelligence_id}` — published-contract result
- GET `/intelligence/{intelligence_id}/input` — frozen snapshot and configuration
- GET `/intelligence/{intelligence_id}/availability` — result plus confirmed publication availability; 409 until outbox ACK is recorded
- GET `/events/{event_id}/intelligence?event_revision=1&ruleset_version=1.1` — revision/version-filtered results
- POST `/events/{event_id}/research` with `{ "event_revision": 1, "ruleset_version": "1.1" }`

Contract: `contracts/event/intelligence/v1.schema.json`, schema version 1.0; ruleset version is independent.

## Optional Stage 4 integration

POST `/analyses` accepts optional `intelligence_id`. Absence preserves the original `btc_event_analysis_v1` flow and identity. Presence selects separate `btc_event_intelligence_v1` prompt and includes intelligence ID in analysis identity. Existing analysis output contracts and old prompts remain unchanged. Missing/unpublished/mismatched intelligence blocks only the opt-in mode before a provider call.

The worker requires exact event revision, canonical hash and evidence hashes. It freezes intelligence with the Stage 4 input. Research explicitly records `hypothetical_derivation=true` and the assumption `current_rules_on_pinned_historical_evidence`; it does not pretend the intelligence existed at source publication time.

Live input availability is the confirmed outbox publication timestamp (a conservative bound recorded after JetStream ACK). The decision projection accepts optional timezone-aware `additional_input_available_at` for live mode only. It uses the maximum of canonical/evidence availability and this additional time, and re-resolves all three causal points relative to that time with `known_at=decision_at`. Future availability is rejected. Stage 4 independently requires intelligence availability no later than decision_at. Freshness and outcome exclusion remain enforced. This read-only projection does not mutate stored context revisions. The parameter is an availability cutoff supplied by the caller, not independent proof; the Stage 4 integration gets it from the confirmed intelligence endpoint and pins that provenance.

Automatic live paid analysis remains disabled. Creating intelligence alone never enqueues an LLM request.

## Dashboard and operation

Event Detail shows every intelligence ruleset for the displayed canonical revision: relevance, novelty, surprise, quality, specificity, expectations availability and version. Missing service/data degrades read-only display. Historical Astra analyses remain separate and unchanged.

```sh
docker compose up -d --build event-intelligence llm-analysis market-context dashboard
./scripts/test-event-intelligence.sh
./scripts/test-event-intelligence-faults.sh
docker compose exec -T event-intelligence python - < scripts/smoke-event-intelligence.py
```

Run backend and broker-fault suites sequentially: they share the isolated test DBs/broker. The fault script never stops the production broker. Change rules only by introducing a new version and selecting it via `EVENT_INTELLIGENCE_RULES_PATH`.
