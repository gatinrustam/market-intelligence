# Stage 5 — Evaluation Engine

Independent service `services/evaluation`, port 8007, own MariaDB `evaluation`. Reads completed analysis messages and public HTTP APIs; no microservice database access, LLM call, signals or trades.

## Run

```sh
docker compose up -d --build evaluation
./scripts/test-evaluation.sh
./scripts/test-evaluation-faults.sh
```

Run all backend/fault suites sequentially: they share isolated `nats-test` and test databases. The fault script stops only `nats-test`, never the production broker.

Configuration prefix `EVALUATION_`: database/NATS/context/analysis URLs, worker/fixture flags, poll and retry intervals, and Decimal thresholds. Defaults: neutral if absolute return < 0.05%; impact negligible < 0.10%, small < 0.50%, moderate < 1.50%, otherwise large. Equality belongs to the next non-neutral/bucket interval. Config rejects nonfinite, nonpositive or unordered limits.

## Correct time boundary

A forecast is evaluated from its **decision_at**, not automatically from event_time. Its anchor price is the exact T price in the frozen Stage 4 input fetched through `GET :8005/analyses/{id}/input`. The canonical input SHA-256 must match `analysis.audit.input_hash`; event revision, decision and fresh anchor are checked. Source/event taxonomy for grouping comes from that pinned input.

Market Context now exposes additive read-only `GET :8004/contexts/{id}/outcomes?decision_at=<timezone-aware timestamp>`. It resolves ONLY +60/+300/+900/+3600 seconds through its existing causal market lookup and freshness policy. Future targets are pending. Each observation must be after decision_at, no later than its own target, and fresh (3-second snapshot / 60-second closed candle defaults). It does not include causal points, modify stored contexts, or recompute the decision baseline. No old stored event-time outcome is relabelled as a live decision-time outcome. This endpoint is exclusively for evaluation, never Stage 4 input.

Outcome retrieval may use subsequently backfilled data: that is allowed for measuring results. Live decision inputs remain restricted to what was actually known at decision_at. The evaluator independently validates identities, horizon ordering, role, timestamp bounds and freshness before scoring.

## Contract and arithmetic

`contracts/evaluation/v1.schema.json` is strict JSON Schema 2020-12, additionalProperties=false for all objects. Four ordered horizons are always present. IDs, revision, analysis/event/model/prompt/input hash, decision basis, explicit origin, source taxonomy, policy/hash, actual prices/timestamps, status and result fields are required.

Price/return fields use decimal strings on the wire, Decimal internally (80-digit intermediate precision, 12 return decimal places, ROUND_HALF_EVEN). Return is `(outcome_price - anchor_price) / anchor_price * 100`; classification uses that stored rounded value. No float monetary arithmetic.

- Horizon `pending`: future target or data within upstream grace period; no actual movement.
- `unavailable`: outcome absent/stale; no actual movement. Scheduler retries, allowing later backfill.
- `evaluated`: actual movement available and predicted direction is up/down/neutral; exact equality is hit, other directions miss.
- `not_scored`: actual movement available but direction unclear. Actual movement and impact comparison remain visible; it contributes neither a hit nor a miss.
- `complete=true`: all four outcomes observed, including unclear forecasts. Missing data is never considered complete.

Impact equality and ordinal distance (0–3) are stored independently. Confidence remains low/medium/high, explicitly model-reported and uncalibrated. No composite score or profit calculation.

## Identity, audit and recovery

`analysis_id` is input identity; evaluation_id is deterministic UUIDv5 from it. Exact input bytes, fingerprint and JetStream provenance are persisted before ACK. Duplicate bytes/content are accepted idempotently. Conflicting content with the same analysis identity and invalid inputs are quarantined in `dead_inputs`; the original is preserved.

Tables: evaluation_inputs, evaluations, evaluation_results, evaluation_revisions, evaluation_jobs, outbox_events, dead_inputs. Policy thresholds are frozen on first acceptance and carry a hash. Config changes affect new inputs only; a distinct research analysis run is required for a different evaluation policy in this version.

The first resolved state is revision 1, even if all horizons are pending. A new revision is created only when result content changes; repeated scheduler passes are no-ops. Current result rows and the immutable revision/outbox insert commit atomically. Once an outcome is evaluated/not_scored, that measured observation is frozen. Subsequent corrections do not rewrite audit history.

Durable pull consumer uses explicit ACK and DeliverPolicy.ALL on `ANALYSES` / `analysis.completed.v1`. Scheduler and outbox use row locks, expiring leases and token fencing. Restart resumes persisted jobs and expired claims. Publisher awaits JetStream acknowledgement, retries indefinitely with bounded backoff, and uses stable Nats-Msg-Id. Earlier revisions must publish before later revisions of the same evaluation. Delivery remains at-least-once; consumers should deduplicate message_id even beyond the broker's one-day dedup window.

First revision → evaluation.created.v1; subsequent changes → evaluation.updated.v1. Both strict payloads are on EVALUATIONS stream. No change to analysis.v1 or earlier NATS contracts.

## Read-only APIs

- GET /health, /ready, /stats
- GET /evaluations/{evaluation_id}
- GET /analyses/{analysis_id}/evaluation
- GET /evaluations/{evaluation_id}/revisions?offset=0&limit=100
- GET /events/{event_id}/evaluations?origin=model|fixture|all&offset=0&limit=100
- GET /metrics?group_by=horizon,confidence&origin=model&basis=all

Metrics grouping supports horizon, event_type, source, model, prompt_version, confidence, including combinations. Metrics read only current result rows, never sum immutable revisions. Every row has n (= hits + misses), evaluated, hits, misses, not_scored, unavailable, pending, total_horizons, analysis_count and direction_accuracy_pct (null when n=0). Origin, live/research basis and policy hash are always separate dimensions. Source groups attribute an event to each source and may overlap; they must not be summed as independent events.

## Labelled fixture smoke

With EVALUATION_FIXTURES_ENABLED=true, run:

```sh
docker compose up -d --no-deps evaluation
docker compose exec -T evaluation python -m app.smoke
```

The current workspace enables this opt-in flag for the requested smoke. Three deterministic hand-authored analyses (Fed/ECB/SEC) use real canonical decision anchors and market observations. Fixtures are delivered on **fixture.analysis.completed.v1** in separate EVALUATION_FIXTURE_INPUTS, with an explicit envelope label and model prefix fixture/. They are never published on analysis.completed.v1 or saved as real LLM Analysis results. evaluation provenance retains origin=fixture; publication uses fixture.evaluation.created.v1 / fixture.evaluation.updated.v1. Plain /metrics excludes them. Envelopes preserve the analysis.v1 provider field solely for contract compatibility; no OpenAI request takes place.

Missing historical SEC outcomes intentionally remain unavailable; the smoke does not fabricate prices or backfill as a side effect. Re-running identical fixtures is idempotent. No fake price enters Market Data or Market Context storage.

## Dashboard

EvaluationClient reads :8007. Event detail has a separate evaluation section with analysis/event revision, origin, decision time, four forecasts, actual returns, hit/miss, impact and missing-data reasons. Labelled fixtures have a warning badge. The Evaluations page defaults to model-only metrics, with explicit fixture selection; it displays accuracy by horizon/confidence/event type and sample sizes. Evaluation outage does not break event/market pages. Overview/System also monitor the new service. UI stays read-only.

## Limits

Initial impact thresholds are a research convention. No confidence calibration, causal attribution, trading, PnL or backtest. No automatic regrading after an already-scored market observation is corrected. Public aggregate rows are grouped by policy and decision basis; they are descriptive sample statistics, not evidence of predictive validity. Event detail loads at most 100 evaluations. Public backend HTTP APIs retain the existing localhost/internal-network deployment model.
