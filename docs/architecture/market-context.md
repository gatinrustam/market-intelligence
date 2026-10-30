# Stage 3.5.1 — Causal Market Context Resolver

Independent service `services/market_context`, database `market_context`, API on localhost port 8004. It consumes canonical events from the existing Stage 2 `EVENTS` stream through durable `MARKET_CONTEXT_V1`, filtering both `event.detected.v1` and `event.updated.v1`. The context worker calls the Stage 3 HTTP API; the decision projection also reads immutable evidence through the Stage 2 HTTP API. There is no Binance client, market collection, cross-service SQL access, model call or trading decision.

## Identity, time and provenance

Identity is `(event_id, event_revision, BTCUSDT)`. A deterministic UUIDv5 identifies the context. Different canonical event revisions create different contexts; context revisions record later observations without overwriting earlier payloads. Seven unique points are keyed by offsets −900, −300, 0, 60, 300, 900 and 3600 seconds.

Anchor uses `time.event_time`; only when null does it use `earliest_source_published_at`, explicitly labelled `source_published_at`. UTC normalization preserves the source's precision and original value. The existing canonical contract allows a date or date range instead of a timestamp. Those cannot honestly anchor second/minute windows: the context has a null anchor, `imprecise_event_time`, seven unavailable points, no synthetic midnight and no substitution of publication time. When both time fields are null, reason is `missing_anchor_time`. These jobs terminate with an explicitly incomplete context; a corrected event revision creates a new context.

At each due point `GET /market/snapshot?symbol=BTCUSDT&at=...&mode=causal` chooses:

1. Actual realtime snapshot from Stage 3 with observed_at <= target_at (nearest eligible predecessor within tolerance): `realtime_1s`, price is last trade, with real bid/ask/spread, snapshot message ID, observed time and distance.
2. Otherwise the latest stored closed candle with close_time <= target_at: `candle_1m`, price is explicitly `candle_close`, `price_at` is the candle close time. All candle OHLC/volume fields are preserved. Bid/ask/spread are null. Candle close must never exceed target. At 18:00:00, the immediately preceding minute closes at 17:59:59.999. If stored history has gaps, the last closed candle can be older; price_at exposes that age, and no missing candle is fabricated.
3. Otherwise unavailable, with Stage 3's reason. During a configurable 10 second period after target, status is `pending / awaiting_market_data` to allow the final candle to arrive.

A future target is `pending / future_target` and does not call Stage 3. Already available points under the same causal lookup policy are frozen for reproducibility; subsequent passes resolve only remaining points. Their returns may be populated later when the anchor price becomes available. Stage 3 does not manufacture historical snapshots; neither does this service. No automatic historical backfill is triggered by the resolver. An operator may backfill via Stage 3; unavailable context points are retried every 300 seconds by default and can then become available.

Returns are `(point_price - anchor_price) / anchor_price * 100`, calculated using Decimal precision 80, rounded to 12 fractional places with ROUND_HALF_EVEN. Absolute return is the absolute value of that percentage, not a price difference. Missing anchor price or missing point price produces null metrics. Every point exposes its resolution/price basis, including when returns compare different resolutions. There is no sentiment, importance, prediction or signal classification.

## Transactions and scheduler

The consumer validates the existing canonical contract, stores exact input bytes and transport metadata with a durable job in one transaction, then ACKs. Duplicates are harmless; conflicting content for the same identity is quarantined without replacing the first event. Invalid JSON, duplicate JSON keys, nonfinite numbers, wrong subject/change_type and schema failures are persisted in `dead_inputs` before ACK. DB failure causes NAK.

A DB worker claims one due job with `FOR UPDATE SKIP LOCKED`, token-fenced lease (90 seconds), and performs up to four concurrent HTTP requests outside the transaction. Each HTTP request has an eight second timeout; the resolution pass has a 30 second timeout. After resolution, context state, seven point rows, immutable revision and outbox event commit together. Internal lookup_policy provenance distinguishes legacy_nearest_v1 from causal_asof_v1. No change means no new revision/outbox. Future points schedule the next relevant timestamp, short data grace waits retry after two seconds, unavailable points retry at the configured interval. HTTP/DB errors retain the previous context and retry with bounded exponential backoff and jitter. Expired leases recover after restart; an obsolete worker cannot commit over the new owner.

`status.complete` means all seven points are available. Separate counts distinguish future pending, data-grace pending and unavailable. A context can have no future points and still be incomplete because historical data is missing. Input/revision storage is independent of Stage 2 and Stage 3 databases.

## Output contract and delivery

Strict schema: `contracts/market/context/v1.schema.json`, title `market.context.v1`.

Following the specification's explicit output-subject section:

- first creation → `market.context.created.v1`;
- subsequent changed revision → `market.context.updated.v1`.

Both share one schema. There is no third duplicate publication on `market.context.v1`; that is the contract name. The `MARKET_CONTEXTS` stream owns those two subjects, uses file storage, one replica, 1 GiB discard-new capacity, and a 24-hour message-ID dedup window. Earlier revisions must be published before later revisions of the same context. Failed publication never rolls back saved context/revisions; full broker storage leaves events in outbox. A dead outbox revision blocks later revisions of that context and is visible in stats.

Delivery is at least once. Consumers should deduplicate message_id; broker deduplication alone does not cover retries beyond 24 hours. No DB retention/archiving is implemented. Missing historical points can remain scheduled indefinitely; monitor job errors/backlog/storage.

## API and operations

- `GET /health`: process alive.
- `GET /ready`: own DB migration at head, input/output JetStream available, worker tasks alive. Does not promise Stage 3 availability; Stage 3 failures appear as retriable job errors.
- `GET /stats`: input/context/point/revision counts, job statuses/errors, outbox pending/dead, quarantined inputs.
- `GET /contexts/{context_id}`: latest context revision, 404 when unknown.
- `GET /contexts/{context_id}/revisions`: immutable history, offset/limit (max 100).
- `GET /events/{event_id}/contexts`: contexts ordered by canonical event revision, offset/limit (max 100).

```sh
docker compose up -d --build market-context
./scripts/test-market-context.sh
./scripts/test-market-context-faults.sh
```

The normal full Compose startup includes Stage 3. Starting only market-context requires Stage 3 already running; its temporary unavailability is retried safely. Settings use `MARKET_CONTEXT_`: DATABASE_URL, NATS_URL, MARKET_DATA_URL, DURABLE_NAME, UNAVAILABLE_RETRY_SECONDS, DATA_GRACE_SECONDS, LEASE_SECONDS, WORKERS_ENABLED. Compose also exposes MARKET_CONTEXT_DB_PASSWORD and MARKET_CONTEXT_PORT. Root credentials are passed only to bootstrap. Runtime runs as UID 10005. Dependencies and migration metadata are pinned/frozen.

Tests run on `market_context_test` and `nats-test`. All project test suites and fault probes share that isolated broker and must run sequentially. Fault scripts do not stop production NATS.

`scripts/context-live-fixture.py` creates one deterministic, explicitly labelled synthetic current event in the resolver-owned input store for smoke verification. It never writes a fake announcement into Stage 2's DB or its EVENTS stream. It exercises the same repository/job/worker/outbox path; real canonical stream consumption is independently verified using existing events and JetStream integration tests.


## Causal/outcome boundary — mandatory for Stage 4

The unchanged strict `market.context.v1` payload remains the full research/audit context. Do **not** give that payload, its raw NATS subjects, revision history, or a serialized ORM object to the Stage 4 LLM. Outcome points and even outcome-related status/revision metadata can leak future information.

Deterministic internal role mapping (`MarketContextPoint.role` / `app.causal.point_role`):

| Offsets | Role | Intended use |
|---|---|---|
| −900, −300, 0 seconds | causal | decision at anchor T |
| 60, 300, 900, 3600 seconds | outcome | later evaluation only |

No role property was added to the existing wire payload: its schema forbids additional properties. Roles remain deterministic by offset. Stage 3.5.2 supersedes the original event-time decision projection: **`GET /contexts/{context_id}/decision` now defaults to actual live input availability**, with explicit `basis=research_hypothetical` for publication-time simulations. See [Decision Time](decision-time.md) for provenance, availability cutoffs, fields and errors. Stored contexts and the earlier causal audit remain anchored on event time/publication.

The resolver validates price_at <= target_at for **all seven** points before committing a new revision; outcome points may be after anchor, but never after their own target. A malicious/old Stage 3 response with a future observation is rejected and retried, never published as a causal revision.

This is event-time causal research: historical candles may have been backfilled later, but only information from market observations ending by the cutoff is selected. It does not assert that the local platform had collected the historical data in real time, nor prove that a subsequently extracted canonical event revision itself was known at T. Stage 3.5.2 enforces event/news availability in the separate decision endpoint, which includes exact evidence and rebuilt decision-time market points. Clock accuracy remains bounded by the recorded pipeline clocks.

## Upgrade and immutable audit

Migration c35101 adds internal lookup_policy columns to current contexts and immutable revisions. Existing revisions are labelled legacy_nearest_v1 without changing payload/message_id. Jobs are token-fenced and requeued. The new worker ignores frozen legacy points, queries all due offsets causally, and commits a new revision even when prices happen to match. Repeated passes under causal_asof_v1 are idempotent.

Stop old resolver workers before applying this migration; never run legacy and causal workers together. Upgrade Stage 3 first so it supports the additive causal API mode, then restart the upgraded resolver. Existing JSON Schemas and wire subject names remain unchanged. Earlier verification documents describe their historical runs; do not use their pre-fix payloads as decision inputs. See `docs/causal-context-verification.md` for the post-fix Fed proof and hash audit.
