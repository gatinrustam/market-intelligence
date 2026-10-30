# Stage 4 — LLM Analysis Service

Independent Python service in `services/llm_analysis`, MariaDB logical database `llm_analysis`, localhost HTTP port 8005. Only the Stage 3.5.3 decision endpoint supplies the analysis content. Canonical EVENTS delivery is a trigger containing event identity; full market context messages and outcome histories are never read. There is no trading, signal generation, consensus collection or outcome evaluation.

## Input and causality boundary

The worker requires `decision_ready=true` and `causal_asof_fresh_v1`. It independently checks event revision, exact evidence document/message/source identities, schema validity, observed availability and fetch/enrichment timestamps, live/historical markers, fixed causal offsets, targets relative to decision time, freshness limits, selected price timestamps, and fresh T. A hypothetical package must explicitly carry simulation markers and source-publication basis. Live evidence cannot arrive after decision time. Insufficient provenance or not-ready market context becomes internal `analysis_status=blocked`, without an LLM call or completed forecast publication.

A separate allowlisted `analysis_input` contains canonical event, linked evidence, decision provenance, and only −15m/−5m/T market points. Arbitrary extra market metadata, candle payloads, snapshot payloads and precomputed returns are not forwarded. Unavailable historical points carry no price. A fresh T is sufficient; missing earlier points remain explicit uncertainty. No HTTP request uses the full market.context.v1 projection or context revision history.

The canonical JSON representation uses UTF-8, sorted keys, compact separators, no NaN, with SHA-256 over those bytes. This is the service's defined canonicalization, not a claim to implement RFC 8785. Exact JSON is saved in `analysis_inputs` before the provider call, referenced by hash. Every provider attempt stores its exact request body, including that input string and versioned prompt/schema. A restart/retry reuses those input bytes without requerying the evolving market backfill.

## OpenAI Responses API

`LLMProvider` abstracts the transport; `OpenAIProvider` uses HTTP POST to `https://api.openai.com/v1/responses`. Defaults: `gpt-6-astra`, medium reasoning, max 6000 output tokens. Model and reasoning effort are configurable. No model substitution is performed.

The request specifies Structured Outputs via `text.format.type=json_schema`, `strict=true`, `tools=[]`, `tool_choice=none`, and `store=false`. There is no conversation ID, prior response, web/file search, browser, computer use, code execution or external function. Transport has no implicit retries; the service owns attempt budgets.

Official references used: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra). Raw structured output text and response ID/status/model/usage/latency are saved. Reasoning items are discarded; reasoning summaries are not requested. Error audit stores a safe error code/status and request ID, not authentication headers or possibly credential-echoing error bodies. API keys are never part of persisted requests or logs. API responses do not provide billed USD cost; `cost_usd=null` is explicit, with usage retained for later accounting.

## Prompt and contracts

`app/prompts/btc_event_analysis_v1.txt` and its model-output JSON schema are immutable versioned assets. `manifest.json` pins their SHA-256; modified or unknown versions fail closed. New prompts require a new filename/version and manifest entry. Per-job prompt hash and full request snapshots make previous attempts auditable after deployment.

The prompt requests concise summary, mechanism and uncertainties, not chain-of-thought. It separates source facts from conditional mechanisms, flags simulation/late content, rejects instructions embedded in evidence, and prohibits invented consensus/surprise/Fed probabilities. Those fields have controlled `unavailable` output labels. Confidence is low/medium/high and explicitly model-reported, not statistically calibrated.

The strict public contract is `contracts/analysis/v1.schema.json`, subject `analysis.completed.v1`, stream `ANALYSES`. The application sets IDs/event/decision/audit fields; the LLM supplies only interpretation/relevance/forecasts/uncertainties/unavailable-data labels. Forecast horizons must be exactly 60, 300, 900, 3600 seconds in order. Public schema additionally enforces this via fixed prefix items. Unknown fields/enums, numeric confidence percentages and BUY/SELL direction values are rejected.

## Persistence, identity and retries

Tables: immutable `analysis_inputs`, mutable scheduling `analysis_jobs`, append-per-attempt `analysis_runs`, immutable `analysis_results`, transactional `outbox_events`, and rejected-trigger `dead_inputs`. Only this database is read directly. Bootstrap owns root credentials; runtime uses its separate DB account.

Live identity is deterministic by event ID/revision, BTCUSDT, provider, model and prompt version. Changing effort alone cannot silently create a second live forecast. Research uses an explicit run UUID and can reuse the same immutable input with another model or registered prompt version; previous results remain unchanged. Repeated requests with the same identity return the original analysis.

Claims use row locks, skip-locked selection and lease tokens. Claim lease exceeds the provider deadline by 60 seconds. Every completion is token-fenced. An expired started attempt is retained as abandoned with unknown provider outcome. Attempts are bounded across restarts. A crash after provider execution but before database commit can cause a second billable API call: exactly-once external execution is not claimed. At most one persisted result/outbox entry is created for an analysis ID.

429, timeout, connection failure and 5xx retry with exponential backoff plus jitter, at most four attempts by default. Invalid structured output has a separate two-attempt limit within the total budget. Authentication/other 4xx/refusal errors do not retry. Missing key is blocked. A blocked job is terminal; use an explicit new research run after fixing coverage/configuration. For an already frozen input, the research endpoint reuses it; for changed coverage create a new context-based hypothetical run.

Result and outbox insert occur in one transaction. Publishing uses stable message ID with JetStream deduplication (24-hour window). Broker outages leave durable pending outbox records, retried independently without another LLM request. Publication after a very long ambiguous outage can redeliver beyond the broker dedup window; downstream consumers must deduplicate by message_id/analysis_id.

## Operation and API

Set `OPENAI_API_KEY` locally in ignored `.env`, never in a request or source file. Compose exposes model and reasoning effort through `LLM_ANALYSIS_MODEL` and `LLM_ANALYSIS_REASONING_EFFORT`. Other Settings use the `LLM_ANALYSIS_` prefix; environment overrides can be added through Compose as needed.

Automatic canonical consumption is opt-in (`LLM_ANALYSIS_AUTO_LIVE_ENABLED=true`) and the durable starts with NEW delivery on first creation. This avoids billing for all existing historical events during initial installation. Subsequent restarts resume the durable. The worker/outbox still process explicitly submitted jobs with auto-live disabled. `/ready` reports provider configuration separately and returns 503 if the key is absent; it does not make a paid health-check request or guarantee model account access.

- `GET /health`, `/ready`, `/stats`
- `GET /analyses/{analysis_id}`: internal status, configuration, result and attempt audit
- `GET /analyses/{analysis_id}/input`: exact canonical JSON and hash
- `GET /events/{event_id}/analyses`: paginated analysis list
- `POST /analyses`: context_id, event_id, event_revision, basis (`live` default or `research_hypothetical`); hypothetical mode requires run_key UUID
- `POST /analyses/{analysis_id}/research`: run_key UUID, model, optional prompt_version and reasoning_effort; uses the saved input

These mutation endpoints are bound to localhost via Compose and enqueue potentially billable work; do not expose them publicly without authentication. Model defaults and explicit research overrides are part of the audit.

## Verification and limits

Run `scripts/test-llm-analysis.sh`, then `scripts/test-llm-analysis-faults.sh`. They use only isolated DB/test NATS, fake provider HTTP responses and no API key. Run regression/fault scripts sequentially because all stages share the test broker.

Bounded historical smoke uses Fed FOMC, ECB and SEC (including lower-quality unavailable HTML evidence). `docker compose exec -T llm-analysis python -m app.smoke --prepare-only` does read-only preflight. Without the flag, the same command submits at most three event analyses with bounded retries. Save stdout to a new artifact and manually review structured responses against frozen inputs. A new run-label is required to create a separate smoke run.

No-tools prevents external future-data retrieval. It cannot prove that the model has forgotten pretrained historical facts or that late-fetched HTML equals publication-time content. Hypothetical inputs are labelled accordingly; manual content review remains necessary and historical outputs are not verified live predictions. This stage does not calibrate confidence, estimate performance or evaluate outcomes.
