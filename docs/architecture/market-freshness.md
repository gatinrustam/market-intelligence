# Stage 3.5.3 — Market Data Freshness

The Stage 4 `/contexts/{context_id}/decision` boundary now applies `causal_asof_fresh_v1` in both live and explicit hypothetical research modes. It retains the Stage 3.5.2 evidence/decision-time semantics. Stored context payloads, NATS messages and old revisions remain research/audit data and must not be supplied to Stage 4.

## Freshness limits

For each selected causal observation, `age = target_at - price_at`. Negative age fails the existing causal validation. An observation is usable only when `age <= max_age_seconds`; comparison uses timedeltas including microseconds, without rounding before the cutoff.

| Resolution | Default maximum age | Environment variable |
|---|---:|---|
| realtime_1s | 3 seconds | MARKET_CONTEXT_REALTIME_MAX_AGE_SECONDS |
| candle_1m | 60 seconds | MARKET_CONTEXT_CANDLE_MAX_AGE_SECONDS |

Both settings must be positive finite numbers; fractional seconds are supported. Compose forwards them from `.env`. Effective limits are returned in every decision package under `freshness_policy.max_age_seconds`, alongside `freshness_policy.version` and `lookup_policy=causal_asof_fresh_v1`. Save the package and effective limits for reproducibility.

For a target exactly at 18:00:00, the previous closed candle at 17:59:59.999 is 0.001 seconds old and valid. A candle closing at 17:58:59.999 is 60.001 seconds old and rejected. Equality with the configured limit is valid. No extra candle allowance is needed for the existing close-time semantics.

## Unavailable observations and decision readiness

Freshness is applied immediately after causal resolution and before return calculations. A stale candidate becomes `available=false`, `status=unavailable`, `reason=stale_market_data`. Its price, timestamp, candle OHLC, bid/ask, spread, snapshot identity and returns are removed. Only target/offset and numeric age/limit diagnostics remain. There is no retry against an older candle after rejection. A realtime candidate rejected by freshness does not silently fall back to a candle.

The HTTP endpoint returns an explicit incomplete package (200), rather than hiding evidence behind an exception:

- `decision_ready` is true only if mandatory T is available and fresh. Stage 4 must require this flag before making a market-informed decision.
- `complete` is true only if T−15m, T−5m and T are all available and fresh. Consumers requiring all three must also require `complete`.
- `market_data_status=market_data_unavailable` if any point is unavailable; otherwise `available`.
- Every point includes `age_seconds` and `max_age_seconds`. Both are null if no observation was selected; stale candidates retain age diagnostics but no market observation payload.

A fresh T with a missing historical point has `decision_ready=true`, `complete=false`. Missing historical points cannot contribute prices or returns. With missing/stale T, returns are null for all points and `decision_ready=false`. Outcomes remain absent.

Sparse historical coverage therefore cannot expose an April price as a September observation. A subsequent backfill may make a new hypothetical read complete. Live reads retain the Stage 3.5.2 `known_at=decision_at` filter, so later backfill cannot fabricate actual historical live availability.

## Reproducibility and compatibility

This policy is applied in the read-only decision projection, not to stored full research contexts. No migration, revision rewrite or NATS schema change is performed. Existing context `lookup_policy=causal_asof_v1` still describes their original causal research selection; the new response uses its own version and effective limits. Previous verification artifacts retain their original results. Each saved new response is a new research-run artifact; policy changes do not alter prior artifacts. The legacy event-time `decision_view` helper remains an audit helper, not a Stage 4 interface.

Run `python3 scripts/freshness-smoke.py` with the local services running. See [verification](../market-freshness-verification.md).
