# Stage 4.5 — Research Dashboard

Internal, authenticated, read-only Laravel 13.32 / Filament 5.8 application in `services/dashboard`, bound to `127.0.0.1:8006`. Versions, including Livewire 4.4, are pinned in `composer.lock`. It reads pipeline data through public HTTP APIs only. Its own SQLite database stores local login users; file sessions/cache live in the `dashboard_data` volume. It receives no microservice database credentials or provider API key.

## Run and sign in

Root `.env` must contain `DASHBOARD_APP_KEY` (Laravel base64 key), `DASHBOARD_ADMIN_EMAIL`, and a random `DASHBOARD_ADMIN_PASSWORD` of at least 16 characters. The current workspace has these generated values already. Keep `.env` private and untracked.

```sh
docker compose up -d --build dashboard
./scripts/test-dashboard.sh
```

Open `http://localhost:8006`; anonymous requests redirect to Filament login. Default email: `research@local.test`; password is `DASHBOARD_ADMIN_PASSWORD` in root `.env`. Bootstrap creates the initial account only if absent, and does not reset an existing password on restart. There is no public registration or account-management page. Startup fails if its application key or initial password is missing. `GET /up` is a non-sensitive application liveness endpoint.

The container uses PHP's internal server for this localhost-only v1. An internet-facing deployment, TLS and production web-server configuration are outside scope.

## Layers and API mapping

Filament pages use `Research/DashboardData` and `Research/Health`; they never issue HTTP requests directly. `Api/ApiClient` provides GET-only requests, response validation and sanitized failures. Six named clients encapsulate the upstream APIs:

| Client | Service | Reads |
| --- | --- | --- |
| IngestionClient | :8000 | `/sources`, `/stats` |
| EnrichmentClient | :8001 | `/sources`, `/stats`, `/documents/{id}` |
| EventsClient | :8002 | `/events`, `/events/{id}`, `/documents/{id}/input`, `/stats` |
| MarketDataClient | :8003 | `/stats`, causal `/market/snapshot` |
| MarketContextClient | :8004 | `/events/{id}/contexts`, `/contexts/{id}/decision?basis=...`, `/stats` |
| LlmAnalysisClient | :8005 | `/analyses`, `/analyses/{id}`, `/stats` |

All six services also expose `/health` and `/ready`, checked concurrently. URLs are configured through `INGESTION_URL`, `ENRICHMENT_URL`, `EVENTS_URL`, `MARKET_DATA_URL`, `MARKET_CONTEXT_URL`, `LLM_ANALYSIS_URL`. Requests have a 1-second connection timeout and 3-second total timeout; redirects are disabled. Overview/system/catalogues/market use a 5-second cache. Event detail and its evidence/decision are fetched directly. Unavailability is rendered as an explicit fallback, not an invented zero, price or analysis.

Three additive read-only endpoints were necessary: Events `GET /events` and LLM Analysis `GET /analyses` return `{items,total,offset,limit}` (maximum page 100); Enrichment `GET /sources` returns stored document counts, enrichment states and error counts per source. Each queries only its own database. Existing write behavior, NATS contracts and immutable revisions are unchanged.

## Pages and semantics

- Overview: six health/readiness states, available counters, last stored BTCUSDT quote.
- Events: searchable title, filters for type/source/quality/lifecycle/latest LLM status for the current canonical revision.
- Event detail: exact canonical evidence, collapsed 1,000-character excerpts, decision/provenance, three causal points, separate event-anchor outcomes, and stored analyses for that revision.
- Analyses and analysis detail: mode, model, prompt, status, attempts, latency/token usage; completed forecasts for 1/5/15/60 minutes. Model confidence is explicitly uncalibrated.
- Market: last stored quote, bid/ask/spread, connection state, last snapshot/candle/update, reconnect and outbox counts.
- Sources: Fed/ECB/SEC ingestion state, stored document counts and enrichment errors; SEC 403 remains `partial / RSS fallback`.
- System: upstream URL, health/readiness, request latency and last check in UTC.

Evidence comes from the immutable Event Engine input, checked against the canonical document's `input_message_id`; it is never silently replaced by current fetched HTML. Decision basis defaults to `live`, with explicit `research_hypothetical` selection. The UI retains actual availability/fetch timestamps and `historical_content_verified=false`.

Causal data comes exclusively from `/decision`, with offsets −900/−300/0. The client rejects positive offsets and mismatched basis/simulation metadata. Unavailable prices, bids, asks and spreads are not rendered. Reasons such as `stale_market_data` and `not_collected` remain visible. Stored outcomes +1/+5/+15/+60 minutes use their original event anchor, shown explicitly; they are not relabelled relative to live `decision_at` and are never passed to an LLM by this service.

## Deliberate limits

- No dashboard operation starts an analysis, edits pipeline records, backfills data or trades. Readiness does not make a provider request or validate paid Astra access.
- Ingestion has no cumulative news counter, so News displays `Unavailable`.
- Catalogues load at most 1,000 records, with a visible truncation warning; filters/search apply to that loaded set. Event context lookup inspects the API's first 100 contexts. This fits the current research corpus, not an unbounded production catalogue.
- Completed LLM output is covered by mocked fixtures; the current real corpus has a blocked run, not a completed Astra forecast.
- No charts, custom design system or write controls were added.
