# Astra real API smoke — 2026-09-20

PASSED: three real gpt-6-astra requests (Fed, ECB, SEC), medium reasoning, max_output_tokens=6000. All completed with HTTP 200 on the first attempt, without retries. Automatic live analysis remains disabled. These are real model outputs in an explicitly hypothetical historical research run, not live predictions and not labelled fixtures.

| Example | Input tokens | Output tokens | Total | API latency |
| --- | ---: | ---: | ---: | ---: |
| Fed | 2846 | 564 | 3410 | 13.927 s |
| ECB | 3537 | 573 | 4110 | 12.699 s |
| SEC | 2407 | 547 | 2954 | 11.685 s |
| Total | 8790 | 1684 | 10474 | |

Provider-reported cost is unavailable; no dollar amount is inferred. Usage is retained exactly in the full JSON, including cache metadata.

All three responses satisfy analysis.v1. Their exact payloads were found on analysis.completed.v1; downstream evaluations satisfy evaluation.v1 and exactly match evaluation.created.v1 messages. Frozen input hashes match. Every market input offset is -15m/-5m/T and every available price is causal. No outcome point was sent to the model.

Manual review against the frozen inputs found: Fed facts match the supplied statement, ECB survey is not misrepresented as a policy decision, SEC partial RSS/failed HTML is acknowledged. Mechanisms are framed as conditional inferences. Every response acknowledges historical simulation, unverified historical content, missing consensus/surprise and data limitations. This review does not independently certify historical source content or predictive validity.

All twelve directions are unclear with low confidence. Evaluation correctly records eight Fed/ECB horizons as not_scored, and four SEC horizons as unavailable due to stale/missing outcomes. Model-only accuracy is null with n=0 for every horizon, not 0% or 100%. Three prior labelled fixtures remain separate.

[Full inputs, outputs, audit, usage and NATS/evaluation verification](astra-real-smoke.json)

- [Fed event](http://localhost:8006/admin/events/d9b482b8-af7e-4fc9-970a-52b30196142e?basis=research_hypothetical)
- [Real model evaluations](http://localhost:8006/admin/evaluations?origin=model)

No application code or contracts changed for this verification. The prior 514-test regression remains applicable. This report supersedes the previous missing-key smoke blocker recorded in llm-analysis-verification.json; the earlier report is retained as historical evidence.
