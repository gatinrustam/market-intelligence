# Stage 4.5 verification — 2026-09-20 UTC

## Automated checks

| Suite | Passed |
| --- | ---: |
| Dashboard, mocked upstream APIs | 24 (104 assertions) |
| Ingestion | 40 |
| Enrichment | 95 |
| Event Engine | 103 |
| Market Data | 56 |
| Market Context, including causal/decision/freshness | 97 |
| LLM Analysis, mocked provider | 46 |
| Total | 461 |

Dashboard tests passed both locally and in the final Docker image. Laravel Pint was run. Backend suites ran sequentially through existing test scripts; enrichment retained two existing warnings. Three added backend tests cover the new read-only catalogues/source summary, pagination validation, real repository results and absence of write side effects.

Dashboard checks cover auth, expected API responses, empty/malformed responses, connection failure, isolated backend outage, all pages, search/filters, LIVE/research labels, stale price suppression, not_run/blocked/completed fixtures, exact evidence rendering and escaping, invalid identifiers, rejection of outcomes in the decision response, and GET-only upstream traffic.

## Real browser smoke

Authenticated successfully at `http://localhost:8006/admin/login`, then opened Overview, Events, Fed/ECB/SEC detail, Analyses/detail, Market, Sources and System in the actual browser. Title search `FOMC` returned 6 matching events. Switching Fed from LIVE to RESEARCH HYPOTHETICAL updated the decision data and labels. Standard Filament layout and navigation rendered; JSON/body content remained collapsed.

Values were compared to public HTTP APIs; captured upstream evidence is in [dashboard-verification.json](dashboard-verification.json).

| Example | Observed UI and matching API |
| --- | --- |
| Fed `d9b482b8-af7e-4fc9-970a-52b30196142e` | Live decision 2026-09-19 19:50:19.777 UTC: market unavailable, blocked LLM reason `market_decision_not_ready`. Research decision 2026-04-29 18:00 UTC: historical_simulation=true, historical_content_verified=false. |
| Fed causal points | T−15: 76018.33 at 17:44:59.999; T−5: 75981.77 at 17:54:59.999; T: 76184.01 at 17:59:59.999. All candle ages 0.001 / 60 seconds. Outcomes separately display the event anchor. |
| ECB `bf6fd01f-7923-4c63-a8ca-5d8a20601d74` | Research T=2026-09-18 08:00 UTC; T−15 is `stale_market_data`, no price; T−5=77784.08, T=77798.01. decision_ready=true, complete=false. |
| SEC `006e85e2-6047-46f8-8d24-59fc133bd458` | `partial / RSS fallback`, medium evidence, 194 chars, failed full fetch HTTP 403. Research T=2026-09-17 12:55 UTC, T price 76788 at 12:54:59.999. |
| Market | UI snapshot 2026-09-20 02:35:21.402 UTC matched API observation 02:35:21.402171: last/bid 80917.99, ask 80918, spread 0.001235819053598646 bps. Provider connected; reconnects/outbox pending=0. |
| Sources | Fed 15 ready, ECB 15 ready, SEC 25 partial with 25 http_403 errors; all ingestion sources healthy at check time. |
| System / Overview | All six upstream services healthy/ready; documents=55, events=55, contexts=56, analyses=1. News total explicitly unavailable. |
| Analyses | Existing live Fed run `62d87b87-c182-584a-bc82-a57e3e44ae93` shown blocked; model gpt-6-astra, prompt btc_event_analysis_v1; no invented token usage or latency. |

No Astra/OpenAI request was made, no analysis job was submitted, and no existing immutable revision was rewritten by this work. Live collectors continue their normal independent operation.

## Limits and deviations

The only backend additions are three GET endpoints required for cross-service lists and source aggregation; no NATS/public message schema changed. No optional chart was implemented. Local SQLite is used only for dashboard authentication. Catalogues are capped at 1,000 records; details inspect up to 100 contexts. Real completed Astra results remain unavailable, so that UI state is verified with fixtures. Health/readiness is not proof of provider credit or model access. See [architecture](architecture/research-dashboard.md) for setup and boundaries.
