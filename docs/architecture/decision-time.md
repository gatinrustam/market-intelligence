# Stage 3.5.2 — Decision Time

`GET /contexts/{context_id}/decision?basis=live` is the read-only Stage 4 boundary. Live is the default. The endpoint pins the canonical revision identified by the context and its exact enriched document inputs. It does not select the latest document or refetch a website. Event time describes the occurrence; decision time describes joint input availability. Neither event time nor source publication can substitute for observed live availability.

## Live availability

`decision_at` is the maximum of the original canonical EVENTS JetStream publication timestamp, canonical generation timestamps and all required evidence availability timestamps. Evidence availability conservatively uses the maximum of Stage 2 input receipt, ingestion receipt, enrichment completion and fetch timestamps. Supporting documents are required too. `decision_basis=live_observed`, `historical_simulation=false`.

The availability scope is the durable pipeline, not the later arrival at Market Context Resolver. The latter is exposed separately as `resolver_observed_at`. This reconstructs joint input availability from recorded clocks; it does not assert that an LLM actually ran at that time. Precision and clock synchronization are bounded by existing provenance clocks.

New resolver inputs persist the original JetStream publication timestamp. For older inputs the endpoint reads the retained original EVENTS message by stream sequence and verifies exact bytes and subject. If it has been deleted, provenance cannot be recovered by this interface: the request fails closed. Synthetic fixtures are not treated as observed canonical publications.

An additive Stage 2 `GET /documents/{document_id}/input` exposes its immutable document input with receipt timestamp, stream sequence and payload hash. The resolver uses HTTP, not cross-service SQL. Document/message/source identities must match the pinned canonical evidence references. Missing or mismatched evidence fails the whole package.

## Explicit historical simulation

`?basis=research_hypothetical` sets `decision_at=earliest_source_published_at`, `decision_basis=source_published_at`, `historical_simulation=true`. Missing publication time is an error. This is a hypothetical use of the later observed canonical revision and document content at publication time, not a claim that the historical system possessed them then.

Both modes expose actual evidence availability, fetch and enrichment times. Every document has `historical_content_verified=false`: there is no archival proof that fetched HTML equals the publication-time page. `late_enrichment` flags availability more than 300 seconds after publication (configurable via `MARKET_CONTEXT_LATE_ENRICHMENT_SECONDS`). Prompt fetching alone does not establish historical verification either. The explicit `content_assumption` accompanies the full pinned canonical event and enriched documents under `known_information`.

## Market data and Stage 4

Only −15m, −5m and T points are returned, all marked causal. Targets are rebuilt relative to decision time; stored event-time context prices are not reused. For every available point `price_at <= target_at <= decision_at`. Closed candles require `close_time <= target_at`; realtime snapshots require `observed_at <= target_at` within tolerance. Returns are recalculated from these three points. No outcome points, outcome completion counts, or future context revision metadata are included. Stage 3.5.3 adds [mandatory freshness checks](market-freshness.md): `complete` now means all three points are available and fresh; `decision_ready` requires fresh T. Evidence remains mandatory. Stale candidates from the underlying last-closed-candle lookup are removed before the response and return calculations.

For live requests, Stage 3 additionally receives `known_at=decision_at`; closed candles collected after that time are excluded. Snapshot `observed_at` is the local observation timestamp, already bounded by target. Historical simulation omits the local collection cutoff and explicitly identifies `market_availability_basis=historical_observation_time_only`. Thus old bootstrap events can have no live market quotes even when a later historical backfill is available. Decision time is never shifted to obtain prices.

Stage 4 must use this endpoint with an explicit desired basis. Full context payloads, NATS context messages and revision histories contain outcomes and are audit/evaluation inputs only. `app.causal.decision_view` and `scripts/causal-context-smoke.py` retain the earlier event-time audit behavior and are not Stage 4 interfaces.

## Compatibility and errors

Existing NATS contracts, subjects, context identities and immutable revisions are unchanged. This stage adds HTTP projection fields and query parameters, without database migrations or historical rewrites. The decision projection is computed on read; save the returned package for a reproducible research artifact, since additional historical backfill can change a later hypothetical read. The pinned evidence and original context revision remain immutable.

Unknown context: 404. Unsupported basis or invalid `known_at`: 422. Legacy policy, missing publication for simulation, synthetic or inconsistent provenance: 409. Unavailable dependent services/retained NATS inputs: 503. No fallback to event/publication time occurs on live errors. Configure `MARKET_CONTEXT_EVENTS_URL` to reach Stage 2; default is `http://events:8002`.

Run `python3 scripts/decision-time-smoke.py` with the local stack running for a read-only Fed/ECB/SEC proof, including immutable revision hashes and exact evidence comparisons.
