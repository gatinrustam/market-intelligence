# DI-5 Semantic Article Intelligence

Independent CPU service (`article-semantic`, port 8012, database `article_semantic`). Reads retained `document.intelligence.v1`, retrieves the exact enriched document by ID and verifies input ID, source lineage and body SHA-256. Its transactional outbox publishes `article.semantic.v1` into its own `ARTICLE_SEMANTIC` stream. No calls to Astra/OpenAI; no changes to canonical events, production routing or existing DI facts.

## Local models and reproducibility

- BAAI/bge-m3 @ `5617a9f61b028005a4858fdac845db406aefb181`, Sentence Transformers, normalized dense embeddings, CPU per-channel INT8 Linear layers with compact FP16 word-embedding storage and FP32 activations (QNNPACK).
- urchade/gliner_multi-v2.1 @ `443d26d654e0324125a96bebd8e796c14ff2efe6`, original FP32 weights; entity-quality checks rejected GLiNER INT8.
- microsoft/mdeberta-v3-base tokenizer/config @ `a0484667b22365f84929a935b5e50a51f71f159d`.

`config/article_semantic/models.lock.json` fixes revisions and files; `model-artifacts.lock.json` fixes SHA-256 and byte lengths. Weights stay in ignored `.models/article_semantic`, mounted read-only at runtime. The original BGE FP32 pickle is converted locally into FP16 safetensors, then into a prepared CPU checkpoint in a separate process. Pipeline v5 loads that checkpoint directly, avoiding an in-worker transformation while GLiNER is resident. The locally generated checkpoint is hash-verified before deserialization; no pickled CPU checkpoint is downloaded. Original and runtime checkpoint hashes are both recorded. Rebuilding the serialized artifact requires pinning its actual byte hash in a new policy version if serialization bytes differ. GLiNER tensors are copied in bounded slices. Hash verification precedes model use. Runtime is offline (`HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`), libraries are pinned, model loading is attempted once per worker, and embedding batches contain at most two chunks.

A configuration version cannot be rebound to different content. New model, ontology, threshold or fusion policies require a new pipeline version; old results and snapshots are retained. Identity is DI intelligence ID + pipeline version. Frozen snapshots include full observed text, chunks, dense vectors and model observations internally; the public contract omits body and chunk text. Frozen-observation replay checks fusion reproducibility; this is distinct from bit-identical inference across different CPU/library platforms.

## Evidence and limitations

Chunking preserves every Unicode character exactly once, including whitespace. Sentence/paragraph boundaries are preferred; oversized sentences split without truncation. Each chunk has document ID, deterministic chunk ID, character offsets, sentence IDs and token count. The original text remains in the internal snapshot. Public evidence spans contain exact text with absolute offsets; a sentence spanning chunks names its starting chunk, and its end offset may cross that chunk boundary.

The bilingual ontology contains 24 concepts. Every chunk records its top four cosine similarities, including below-threshold audit matches. Thresholds and ontology descriptions are configuration, not learned labels. Cosine similarity is not a probability. Accepted concepts aggregate evidence, not independently verified events.

Fusion order: DI facts, then entity-supported predicate candidates, then extractive semantic candidates. DI facts are copied unchanged. GLiNER is an entity model: relations are explicitly labelled **GLiNER entity candidates plus a same-sentence predicate rule**, not a neural relation classification probability. Their confidence is entity confidence only. Claims are exact source fragments; no abstractive summary is generated. Pipeline v2 retains complete claim sentences so a late object/value is not cut away. Explicit INTERVIEW/SPEECH document headers determine genre while preserving every underlying DI fact. Semantic conflicts preserve both layers. Ten independent information-value features each have reasons and supporting source spans where applicable; source/document quality use explicit provenance metadata rather than invented textual evidence.

Asset links require evidence and a stated basis. An isolated Bitcoin mention is insufficient. Named BTC/ETH links in pipeline v2 also require the named entity to occur inside a DI fact or an explicit entity-predicate candidate; closed EN/RU aliases handle basic inflection. USD/EUR need macro context plus the relevant official source; broad macro exposure is a candidate, not a directional forecast. Gold is a supported output vocabulary item but has no dedicated v1 ontology concept, so mention-only gold links are deliberately withheld. This limits recall. Short RSS bodies remain explicitly partial; attachment-only content is not inferred. Model candidates are not verified facts, and an exact quote can still be contextually unimportant or incomplete.

## API / dashboard / labels

- `GET /documents/{document_id}/insight`: read-only list of compact insights across immutable versions, newest first, with separate review state.
- `GET /articles?offset=0&limit=100`, `/articles/{semantic_id}`, `/semantic/{semantic_id}`, `/stats`.
- `POST /reviews/{semantic_id}/labels`: independent, authenticated append-only review labels; optimistic revisions and idempotent request UUIDs. This is the only review mutation. It never changes machine results or learns from labels.

Dashboard News Detail shows **ARTICLE INSIGHT** above existing raw/debug sections, including key claims, assets, evidence, limitations and old-versus-semantic routing. Review fields cover semantic/claim/asset/importance correctness and missing context; optional explicit gold importance/assets/correct claim IDs support subset metrics. `ARTICLE_SEMANTIC_REVIEW_TOKEN` is shared server-side with the dashboard and must never enter HTML. `production_switch=false` is a contract invariant.

BGE failure produces failed/partial semantic output while preserving DI facts. GLiNER failure leaves embeddings and DI available with a warning. The old Article Router continues independently. Failed semantic results are immutable: recovery uses a new research pipeline version, rather than silently overwriting a failed history entry.

## Running / audit

Download pinned public weights with `python3 scripts/download-semantic-models.py`. Build the image; use `scripts/prepare-semantic-cpu-weights.py` in it with a writable `/cpu-weights` mount before starting workers, followed by `scripts/prepare-semantic-int8.py` in a separate process. Verify the printed derived artifact hashes against the lock file. Both preparation steps require the pinned runtime libraries; the second saves only the Sentence Transformers modules, not credentials or service state. The worker always uses read-only `/models`.

`docker compose up -d --build article-semantic dashboard` provisions the service and consumes retained DI inputs. Do not run the explicit research runner concurrently with the normal worker. `scripts/research-article-semantic.py` is an alternative bounded research runner over retained NATS inputs and prepared RU fixtures, reusing the same models for the whole run. `scripts/semantic-ru-inputs.py` prepares synthetic RU snapshots through real DI-1 without DB/NATS writes. Fixture outputs remain separate from published articles.

Run `scripts/test-article-semantic.sh` and dashboard tests. `scripts/smoke-article-semantic.py` verifies full stored-body coverage, exact claim spans, unchanged DI facts, frozen replay and equality between DB and actual NATS payloads. It does not call models or external APIs.

Pipeline v5 uses QNNPACK and checks four distinct EN/RU control texts for finite, normalized, non-collapsed embeddings before accepting the encoder. The oneDNN per-channel run on this ARM host produced collapsed vectors and is retained only as an invalid experimental revision.

Final pilot artifacts: [verification report](../article-semantic-verification.md), [all 55 payloads and wire/replay proof](../article-semantic-verification.json), [metrics](../article-semantic-metrics.json). Recompute descriptive metrics with:

```sh
python3 scripts/evaluate-article-semantic.py docs/article-semantic-verification.json datasets/article_semantic/review/completed-review.v1.json datasets/article_semantic/review/ru-results.semantic_pipeline_v5.jsonl
```

For a bounded research run, set `ARTICLE_SEMANTIC_WORKERS_ENABLED=false` on the API container before launching the runner. Re-enable it after the runner exits; duplicate retained inputs are idempotent and inactive older versions are not claimed. The current 55-document run has no pending jobs. Older unfinished experimental versions remain audit-only.
