# Stage 3 — Market Data Service

Independent Python service (`services/market_data`), MariaDB logical database `market_data`, HTTP port 8003. It reads no Stage 1/1.5/2 database. Public Binance Spot BTCUSDT only; no keys, accounts, orders, news joins or indicators.

## Data flow and time

`BinanceSpotProvider` implements the `MarketDataProvider` protocol. A combined public WebSocket supplies aggregate trades, best bid/ask and final UTC 1m candles. The receiver updates bounded in-memory state; it does not save trades or raw WebSocket messages. Duplicate/out-of-order trade and book sequence IDs are ignored within a connection. Disconnect clears both inputs; fresh trade and book updates are required before sampling resumes. Exponential reconnect delay is 1–60 seconds plus up to one second jitter, reset after 30 seconds of a healthy connection. The WebSocket library responds to server pings; no client ping flood.

The sampler saves actual observations once per configurable interval (default 1 second). It does not fabricate catch-up samples. Both inputs must have been received within 10 seconds (configurable). A slot uniqueness key prevents duplicate samples; changing sampling interval requires a planned collector restart. One active collector per deployment is supported. The scheduled delay is measured after each write, so cadence can exceed one second under database load; observed timestamps and gap warnings expose this.

`observed_at` is the actual sampling time. `exchange_event_at` is the last aggregate trade's exchange event time, explicitly identified by `exchange_event_basis=last_trade`. Binance Spot bookTicker has no exchange timestamp; only its local `book_received_at` is exposed. Sequence IDs are normalized names (`trade`, `book`), not raw exchange objects. Ingestion latency is trade receive time minus its exchange event time; it can be negative if local and exchange clocks differ. Synchronize host/VM clocks for accurate latency measurements. No timestamps are silently corrected.

All financial numbers use Python Decimal. Canonical candles use NUMERIC(38,18); immutable snapshot/outbox JSON stores exact decimal strings, never binary floating-point price/volume numbers. Calculations use precision 60; mid and absolute spread are exact, spread bps is rounded to 18 fractional places with ROUND_HALF_EVEN. UTC timestamps retain microseconds in DB. Public timestamps end in Z.

## Persistence and delivery

One transaction inserts `market_snapshots_1s` and `outbox_events`. The publisher independently leases due records for 60 seconds, publishes within a 15 second deadline and marks acknowledged records published. Failure retries with bounded exponential backoff and jitter. Expired leases survive process restart. Strict JSON Schema validation precedes persistence and publication. NATS uses stable message IDs and a 24-hour duplicate window. Delivery is at least once; consumers must deduplicate message_id outside the broker's window.

`MARKET_SNAPSHOTS` owns only `market.snapshot.v1`, file storage, one replica, 1 GiB, discard-new. A full stream causes outbox retries rather than discarding saved samples. Database and outbox retention/archiving are not implemented; provision storage and monitor backlog. DB loss cannot be hidden: the collector logs failures and later gaps; unavailable samples are not recovered from candles.

`market_candles` has primary key `(provider,symbol,interval,open_time)`. Only final WS candles or REST candles from completed minutes are saved. REST imports compare close time with Binance `/api/v3/time` captured before fetching candles, so a fast local clock cannot admit an open candle. Duplicate equal candles are no-ops; conflicting values are rejected and logged, never overwritten. The bounded 120-candle queue retries DB failures; overflow is logged and the REST repair path can recover missed bars.

A durable `collection_checkpoints` cursor drives continuous REST repair, including startup and reconnect gaps. It is independent of the newest WebSocket candle, so later candles do not mask earlier holes. Repair runs every 60 seconds, processing at most a day per pass. A failed page leaves the cursor unchanged. Historical imports use separate durable `backfill_jobs` with token-fenced leases and heartbeat. Candle inserts and page cursor advancement commit together. Rerunning the same range resumes or returns the completed job. Fixed windows of at most 1,000 minutes require complete ordered results; missing minutes are reported for retry rather than silently skipped.

The REST client spaces requests by at least one second, follows Retry-After for 429/418 and limits one call to six attempts. Failed CLI jobs remain resumable. Run one collector and at most one CLI backfill process per deployment; request pacing is per process, not a distributed IP-wide quota manager.

## API

- `/health`: process alive.
- `/ready`: own migration at head, NATS available, worker tasks alive. Binance connection state is separately visible in stats; NATS failure does not stop collection.
- `/stats`: connection state, last event/sample/candle times, counts, latency, reconnects, outbox pending/dead, last ten backfill jobs. WS counters/latency/reconnect counts are per process.
- `/market/snapshot?symbol=BTCUSDT&at=<timezone-aware ISO8601>`: nearest actual sample within configured tolerance (default 3 seconds), ties prefer the past. Before first saved sample returns `not_collected`, even if a future sample is near. Later gaps return `no_snapshot_within_tolerance`. Candle is the closed bar for the requested UTC minute, independent of sample availability.
- `/market/candles?symbol=BTCUSDT&interval=1m&from=<ISO8601>&to=<ISO8601>&limit=1000`: half-open range by open_time, ascending; `next_from` supports continuation. Max page size 1,000.

Neither candle close nor any other historical candle field substitutes for unavailable realtime bid/ask, spread or trade price.

## Operations

```sh
docker compose up -d --build market-data
./scripts/test-market-data.sh
./scripts/test-market-data-faults.sh

docker compose exec market-data python -m app.backfill \
  --symbol BTCUSDT --interval 1m --from 2026-04-01 --to 2026-09-20
```

Backfill timestamps must align to UTC minutes and contain a timezone; date-only values mean UTC midnight. End is exclusive and must not include a still-open minute. The long example is valid only once that end time has passed. A short verified range is recorded in `docs/market-data-verification.md`.

Settings use `MARKET_DATA_` prefix: DATABASE_URL, NATS_URL, SNAPSHOT_INTERVAL_SECONDS, MAX_SNAPSHOT_DISTANCE_SECONDS, MAX_STATE_AGE_SECONDS, REST_INTERVAL_SECONDS. Compose also supports MARKET_DATA_DB_PASSWORD and MARKET_DATA_PORT. Root credentials are passed only to bootstrap, not the runtime. Versions are pinned in pyproject/constraints. Migrations contain frozen metadata.

Official provider references: [WebSocket streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md), [REST market data](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md). The documented market-data-only endpoints are `data-stream.binance.vision` and `data-api.binance.vision`.


## Stage 3.5.1 additive causal lookup

`GET /market/snapshot?...&mode=causal` selects only snapshots with observed_at <= at, nearest first and within the existing configured tolerance. Candle fallback selects the latest stored closed bar with close_time <= at, never the bar ending after at. Boundary equality is allowed. Missing stored minutes can make the last closed bar older; its close_time remains explicit. There is no fabricated intermediate price.

The default `mode=nearest` preserves the original Stage 3 research lookup semantics and response shape for existing clients. Decision-making clients must explicitly request causal mode. Market Context Resolver now always does so and independently checks the returned cutoff. No event JSON Schema changes were made.


## Stage 3.5.2 local availability cutoff

`GET /market/snapshot?mode=causal&at=...&known_at=...` additionally requires historical candles to have `collected_at <= known_at`. The target must not exceed `known_at`, and nearest mode cannot use it (422). Snapshots already use the local `observed_at <= at` cutoff. This additive query parameter leaves default nearest behavior and response/NATS schemas unchanged. Decision projections use it for live observations; explicit historical simulations omit it.
