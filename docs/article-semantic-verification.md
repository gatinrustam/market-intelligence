# DI-5 — Semantic Article Intelligence: verification report

Verified locally on 2026-09-20. Pipeline `semantic_pipeline_v5`. Independent local BGE-M3 + multilingual GLiNER + unchanged DI-1. No external LLM requests, no trading, no production router switch.

## Implementation

- Independent `article-semantic` service, port 8012; dedicated database, retained NATS consumer and transactional outbox on `article.semantic.v1`.
- Lossless full **stored body** chunking, maximum 192 BGE tokens, batch size 2. Character offsets and DI sentence IDs; internal snapshots retain text and embeddings. Public output contains references/evidence, not a body field.
- Strict contract, immutable configuration-bound research revisions, read-only `/documents/{document_id}/insight` and authenticated append-only review labels.
- Top News Detail `ARTICLE INSIGHT`: why it matters, topics, assets and their basis, exact claims, numbers, entities, independent importance features, limitations and old/semantic route comparison. Archived versions are collapsed below the latest result.
- DI facts remain unchanged and take precedence. GLiNER supplies NER; relations use explicit same-sentence predicate rules and entity confidence, not a neural relation probability. Semantic claims are extracts, not generated summaries.

## Models and exact revisions

| Component | Model | Revision |
|---|---|---|
| Encoder | BAAI/bge-m3 | 5617a9f61b028005a4858fdac845db406aefb181 |
| NER | urchade/gliner_multi-v2.1 | 443d26d654e0324125a96bebd8e796c14ff2efe6 |
| NER backbone/tokenizer | microsoft/mdeberta-v3-base | a0484667b22365f84929a935b5e50a51f71f159d |

Exact original and derived file SHA-256 hashes: [artifact lock](../config/article_semantic/model-artifacts.lock.json). Prepared local BGE checkpoint SHA-256: `30ba401e590463584607ed3fae0786ffd5b811e11d186ca20b85ca176283066c`. It is verified before deserialization; no serialized CPU checkpoint is downloaded. Public provenance records upstream and runtime hashes.

Runtime: Python 3.13.12, torch 2.8.0, transformers 4.57.6, sentence-transformers 5.1.2, GLiNER 0.2.24, NumPy 2.2.6. BGE Linear layers use per-channel INT8/QNNPACK, vocabulary storage FP16 and arithmetic FP32; GLiNER retains FP32. Quantization is a documented deviation from upstream full precision, not a claim of identical predictions. Both models load once per worker, with offline inference.

## Ontology and thresholds

`semantic_ontology_v1`: 24 concepts with EN/RU descriptions; `semantic_thresholds_v1`: acceptance 0.48, high 0.62, top four concepts per chunk. Cosine similarity is not probability. GLiNER candidate threshold 0.5. No thresholds were fitted to the review labels. Full policy: [configuration](../config/article_semantic/policy.v1.json).

## Tests and regression

- Previous stages: 669 passed (ingestion 40, enrichment 95, events 103, market data 56, context 105, LLM 60, evaluation 46, event intelligence 24, DI-1 55, router 27, event research 58).
- DI-5: 36 passed, including NATS/outbox, immutable runs/replay, failure isolation, lossless chunks, exact claims, named-asset support, independent labels, current-version jobs, CPU dtype restoration and embedding collapse rejection.
- Dashboard: 54 passed, 218 assertions. Pint passed on changed files; explicit file list used because runtime image does not contain Git.
- Total: **759 tests passed**. UI checked in the browser; one source review saved through the actual form and read back as revision 1. Old DI-2 review remained revision 0.

## 55-document semantic smoke

| Metric | Value |
|---|---:|
| Current-version documents | 55 |
| Status | {'complete': 30, 'partial': 25} |
| Concepts/document | 5.109 |
| Claims/document | 5.527 |
| Assets/document | 2.145 |
| DI facts present | 16 |
| Semantic candidates where DI facts absent | 37 |
| Conflicts with DI | 0 |
| Routing disagreements | 18 |

All 55 have both models available. Smoke verifies complete stored-body coverage, bounded tokens, exact claim spans, unchanged DI facts, frozen fusion replay, contract validation and **equality to the actual NATS JSON payload**. This verifies replay of frozen observations, not bit-identical neural inference across hardware.

NATS stream messages: 77; archived results verified: 22. Previous v1/v3/v4 results remain unchanged. v2 has no outputs. Failed and invalid experiments are audit history, excluded from final metrics. Unfinished old-version jobs remain inactive; only the current policy can be claimed.

## Reviewed subset and metrics

**15 purposively selected real documents were manually inspected by Codex against source text and exact final outputs. This is NOT independent human validation.** The review UI is ready for a human reviewer; these pilot labels must not be presented as human gold or broad accuracy.

Important means a substantive specific policy/data/regulation/enforcement development; personnel, scheduling and routine administration are negative. A predicted important article means route `critical` or `important`; `review` counts as not-important. Asset evaluation uses exact sets of evidence-supported markets, not forecasts. Claim acceptance requires text support plus appropriate type/relation and substantive content; exact bibliography quotes or misleading typed relations can fail.

| Reviewed metric | Result |
|---|---:|
| Important precision | 100.0% |
| Important recall | 60.0% |
| Asset micro precision | 51.9% |
| Asset micro recall | 87.5% |
| Claim precision | 58.8% (40/68) |
| Documents with useful added semantic context | 9/15 |

Useful added context is assessed only on the 15 reviewed documents; the other 40 have not been assigned a usefulness label. Semantic candidates without DI facts are not counted as proven useful.

Labels/comments/accepted claim IDs: [completed review](../datasets/article_semantic/review/completed-review.v1.json). Labels are separate from machine outputs, with explicit Codex attribution; one UI row uses the authenticated local account plus that attribution in its comment.

| Reviewed article | Semantic correct | Claims correct | Assets correct | Importance correct | Missing context |
|---|---|---|---|---|---|
| Federal Reserve issues FOMC statement | False | False | True | True | False |
| Federal Reserve Board and Federal Open Market Committee release economic projections from the September 15-16 FOMC meeting | True | True | True | False | True |
| SEC Announces Departure of Principal Deputy Director of Enforcement Sam Waldon | False | False | True | True | True |
| SEC Proposes New Regulation Crypto Assets | False | True | True | False | True |
| SEC Charges Private Fund Adviser Adit Ventures Management, Its CEO and Affiliated General Partners in Alleged Fraud | False | True | False | True | True |
| SEC Proposes New E-Delivery Approach to Make Information More Readily Accessible and Useful for Investors | False | True | False | True | True |
| SEC Announces Continuation of Small Business Advisory Committee Meeting | False | False | True | True | True |
| SEC Issues “Innovation Exemption” to Facilitate the Trading of Tokenized NMS Stock and Request for Comment | False | True | False | False | True |
| SEC: 38 Entities Feigned Legitimacy as U.S. Advisers Through False Filings to Lure Retail Investors | False | True | False | True | True |
| SEC Establishes Financial Reporting and Accounting Unit in Enforcement Division | False | True | False | False | True |
| SEC Office of Municipal Securities Updates FAQs for Registration of Municipal Advisors | False | False | False | False | True |
| Monetary policy decisions | False | False | False | True | True |
| ECB Consumer Expectations Survey results – August 2026 | False | False | True | True | True |
| Christine Lagarde: Interview with Ouest-France | False | False | False | False | True |
| Piero Cipollone: The future of euro cash: trusted today, designed for tomorrow | False | False | False | False | True |

## Old versus semantic routing

| Route pair | Documents |
|---|---:|
| important -> important | 7 |
| important -> review | 2 |
| low -> review | 1 |
| review -> important | 15 |
| review -> review | 30 |

Production DI-2 decisions were not changed. Comparison is descriptive; high similarity alone does not establish an important event.

## Russian fixtures

Ten synthetic RU fixtures were run through actual DI-1 and both local neural models, outside DB/NATS corpus publication. These are behavioral examples, not representative language accuracy.

| Fixture | Expected concepts found | Missing | Assets | GLiNER entities |
|---|---|---|---|---:|
| ru_rate | interest_rates, monetary_policy | — | rates | 5 |
| ru_inflation | inflation | — | rates | 2 |
| ru_withdrawal | crypto_exchange, withdrawal_suspension | — | crypto_market, BTC, ETH | 4 |
| ru_hack | hack, security_incident | — | crypto_market | 2 |
| ru_depeg | depeg, stablecoin | — | crypto_market | 6 |
| ru_etf | crypto_regulation, etf, institutional_crypto | — | crypto_market | 2 |
| ru_treasury | institutional_crypto, treasury_purchase | — | crypto_market, BTC | 3 |
| ru_earnings | earnings | equities | specific_company | 4 |
| ru_personnel | personnel | — | crypto_market | 2 |
| ru_administrative |  | administrative | crypto_market | 1 |

RU limitations: the ETF fixture misses the explicit BTC link; the earnings fixture misses equities and adds M&A. Personnel and administrative fixtures wrongly receive crypto_market. The incidental Bitcoin mention does not produce a BTC link, but broad digital-asset false positives remain.

## Example Article Insights

### Federal Reserve issues FOMC statement

Type: `primary_announcement`; importance: `high`; status: `complete`. Topics: employment, etf, inflation, interest_rates, monetary_policy.

Candidate assets: rates, USD.

> In support of its goals, the Committee decided to maintain the target range for the federal funds rate at 3‑1/2 to 3‑3/4 percent.

> The Committee seeks to achieve maximum employment and inflation at the rate of 2 percent over the longer run.

Reviewer caveat: Codex-assisted source review. Correct immutable hold range 3.5–3.75; semantic extracts add voting dissent, employment, inflation and uncertainty. ETF theme is unsupported. Claims 9-11 are exact policy-guidance quotes but inherit an overly narrow inflation type; excluded under the same strict text-plus-type rubric as the survey. Assets USD/rates and high importance are supported; no BTC link is invented.

### Federal Reserve Board and Federal Open Market Committee release economic projections from the September 15-16 FOMC meeting

Type: `data_release`; importance: `medium`; status: `complete`. Topics: economic_growth, employment, inflation, monetary_policy.

Candidate assets: rates, USD.

> September 16, 2026 Federal Reserve Board and Federal Open Market Committee release economic projections from the September 15-16 FOMC meeting For release at 2:00 p.m. EDT The attached tables and charts released on Wednesday summarize the economic projections made by Federal Open Market Committee participants in conjunction with the September 15-16 meeting. 

Reviewer caveat: Codex-assisted source review, not independent human validation. Correct macro themes and USD/rates links; exact release announcement retained. Numeric projection tables are only referenced, not present in the stored body. Review route misses the gold-important release; the broad inflation claim type is thematic, not a measured inflation fact.

### SEC Proposes New Regulation Crypto Assets

Type: `regulatory_action`; importance: `medium`; status: `partial`. Topics: crypto_exchange, crypto_regulation, financial_regulation, institutional_crypto.

Candidate assets: crypto_market.

> The Securities and Exchange Commission today announced that it proposed new rules, titled “Regulation Crypto Assets,” that would create a clear and fit-for-purpose framework for certain investment contracts involving crypto assets.

Reviewer caveat: Codex-assisted source review. GLiNER-supported SEC/proposed/Crypto Assets relation is grounded in the exact sentence; regulatory genre and crypto_market are appropriate. crypto_exchange is too specific for the available investment-contract proposal. No BTC/ETH is invented. Conservative partial-body review route misses the important proposal; full rule scope is unavailable.

### Christine Lagarde: Interview with Ouest-France

Type: `interview`; importance: `medium`; status: `complete`. Topics: crypto_exchange, economic_growth, employment, enforcement, equities, exchange_outage, inflation, institutional_crypto, interest_rates, monetary_policy, treasury_purchase.

Candidate assets: rates, EUR, crypto_market.

> We have an inflation target of 2% over the medium term.

> Today, inflation is well above 2%, at 3.3% in the euro area, and there has been a major shock that will probably last longer than we had expected.

Reviewer caveat: Codex-assisted source review. Interview structure is correctly detected and the 2% target, 3.3% inflation and energy-supply shock add useful context. Crypto exchange/outage, institutional-crypto and treasury themes are unsupported. crypto_market is false-positive; US-equity exposure discussed in the AI correction passage is missed. Claims 5-7 are a question or fragmentary answers; 8-11 are header/social introductions, not substantive monetary-policy claims. Key claims omit the explicit rate-hike explanation and US AI-equity discussion. Important gold article remains routed review.

### Piero Cipollone: The future of euro cash: trusted today, designed for tomorrow

Type: `speech`; importance: `medium`; status: `complete`. Topics: crypto_exchange, crypto_regulation, economic_growth, employment, etf, financial_regulation, inflation, institutional_crypto, interest_rates, monetary_policy, stablecoin, treasury_purchase.

Candidate assets: rates, EUR, crypto_market.

> Understanding the demand for cash beyond transactional use”, Economic Bulletin, Issue 2, ECB; and ECB (2026), The international role of the euro, June. - See the “Banknotes and coins circulation” page on the ECB’s website. - Clipal, R. and Zamora-Pérez, A. (2025), “Cash is alive… and somewhat young?

> Together with the banking sector, we must ensure that everyone can access and use banknotes and coins, and we are fully committed to doing so.

Reviewer caveat: Codex-assisted source review. Correct speech format and useful extracts about cash access, issuance and trust. Claim 0 is bibliography. Claims 6-11 concern the Single Currency Package and legal tender of cash, not crypto regulation; their exact text is preserved but type is misleading. rates and crypto_market overstate exposure; EUR only is supported. Medium potential importance overstates immediate significance. Banknote redesign and survey context are underrepresented in key claims.

## Performance / RAM

Apple M3, 8 GiB host RAM, Docker VM limit 3.825 GiB, CPU inference with 2 threads. Cold load plus ontology/control preflight: **29.14 s**, measured separately from document inference.

- 398 chunks across 55 articles.
- Total document inference: 604.22 s; median 1.22 s; maximum 103.93 s.
- 0.0910 documents/s; 0.659 chunks/s (inference-only denominators, not end-to-end pipeline throughput).
- Peak process RSS: 2.710 GiB. RSS includes mapped/shared pages and differs from Docker working-set accounting. Figures depend strongly on body length and available memory.

## Known limitations and deviations

1. Small CPU memory budget required a separately prepared, pinned INT8 BGE checkpoint. Original FP32 loading exhausted memory. GLiNER INT8 was rejected after extraction quality checks; final GLiNER is FP32.
2. oneDNN per-channel arithmetic on this ARM host collapsed distinct control texts. QNNPACK passed the control; v5 now rejects non-finite, non-normalized or collapsed control embeddings before accepting BGE. [Backend evidence](../datasets/article_semantic/review/cpu-backend-check.v1.json). Invalid v4 outputs remain audit-only.
3. Input completeness limits analysis: stored RSS snippets are explicitly partial; missing PDFs/tables/full articles are not invented. Processing all stored characters does not mean recovering the entire publisher article.
4. Ontology cosine matching can over-assign adjacent themes. Sentence claims inherit chunk-level themes, which can mislabel otherwise exact quotes; bibliography and incidental details may enter the top claims. The review records these failures rather than treating exact offsets as semantic correctness.
5. DI-1 limitations are deliberately preserved. In the consumer expectations survey, the existing inflation fact describes perceived inflation, not realized CPI; the original evidence remains visible and the review flags this.
6. GLiNER is NER with conservative rule-assisted relation candidates, not an unrestricted relation extraction model. Basic alias/verb coverage limits RU recall. Named assets need a relation/fact; isolated Bitcoin mentions do not qualify. Gold is in the public vocabulary but has no dedicated ontology concept; mention-only gold links are withheld.
7. No independently human-reviewed gold subset was available. The 15-document Codex review is a transparent pilot, not a substitute for human acceptance and not a general accuracy claim.
8. Unrelated projects remain stopped. Resource-heavy background market/LLM/evaluation services were not restored. Their dashboard sections may report unavailable while the semantic/news services remain usable.

## Preservation and scope

Read-only preservation checks confirmed: 55 original canonical events plus revision/extraction histories; 55 DI outputs and DI-2 routes/reviews; 55 event-intelligence results; 55 DI-3 extraction snapshots; 55 correlation projections and 1,485 pairs; three prior paid Astra audit records/frozen inputs. Provider attempts remain three, no new external LLM call. No automatic event merge, production routing change, model training or learning from review labels.

Detailed machine-readable metrics: [metrics](article-semantic-metrics.json). All final payloads and exact-wire/replay evidence: [verification JSON](article-semantic-verification.json). Architecture and reproducible run commands: [architecture](architecture/article-semantic.md).
