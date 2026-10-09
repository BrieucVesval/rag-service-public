# Project overview

High-level view of how the project evolves: one line per step, key decisions, key numbers.
Details, alternatives and reproduction commands are in [`project_log.md`](project_log.md).

**Goal**: a production-grade RAG over French public-service fiches (Service-Public.gouv.fr, *Logement*), where every choice is measured: faithfulness, citation accuracy, hybrid vs. dense retrieval, chunking strategies.

## Status

- **Current**: v0 works end to end (question → dense retrieval → cited answer), not yet evaluated.
- **Next**: golden set, then the first measured evaluation of v0.

## Roadmap

| # | Milestone | Status |
|---|---|---|
| 1 | Corpus and ingestion | ✅ Done |
| 2 | Minimal end-to-end RAG (v0) | ✅ Done |
| 3 | Golden set (50+ questions) and evaluation harness | ⬜ Next |
| 4 | Baseline evaluation of v0 | ⬜ |
| 5 | Citation verification (LLM-as-judge) and confidence score | ⬜ |
| 6 | Chunking comparison (fixed vs. headers vs. semantic) | ⬜ |
| 7 | Hybrid retrieval (dense + BM25, RRF) and reranking | ⬜ |
| 8 | Provider comparisons (Mistral Small, Claude, GPT-4o, self-hosted) | ⬜ |
| 9 | API (FastAPI), dashboard (Streamlit), Docker | ⬜ |
| 10 | Case study with measured results | ⬜ |

## Timeline

| Date | Step | What was done | Key decision |
|---|---|---|---|
| 2026-10-07 | 1. Corpus choice | Service-Public "Particuliers" fiches, *Logement* theme | Structured, French, open license; easy to write a golden set |
| 2026-10-07 | 2. Corpus fetch | Reproducible download script, 350 fiches + manifest | Raw data not versioned, manifest is |
| 2026-10-07 | 3. Version control | Git with one branch per feature | User runs every git command |
| 2026-10-07 | 4. XML loader | 333 fiches → Markdown documents, 0 parser warnings | Conditional cases kept as headings; guided searches excluded |
| 2026-10-08 | 5. Provider choice | Mistral API free plan for embeddings and generation | Zero cost; relevant to the Mistral application |
| 2026-10-08 | 5a. Chunking | Fixed-size chunker (2,000 chars, 200 overlap): 2,828 chunks | Simplest baseline that smarter strategies must beat |
| 2026-10-09 | 5b. Indexing | `mistral-embed` vectors in ChromaDB (1.7M tokens, 155 s) | One collection per configuration, batch size measured |
| 2026-10-09 | 5c. Retrieval + generation | Top-5 dense retrieval, grounded prompt, citations, `ask` CLI | `ministral-14b` (Mistral Small not available on the free plan) |

## Key numbers so far

- Corpus: 333 documents, 800k words, median 1,303 words per fiche, max ~40k.
- Index: 2,828 chunks, vectors of 1,024 dimensions, 61 MB.
- v0 on 4 manual questions: 1 correct, 1 correct refusal, 2 with unsupported claims. Latency 2–5 s, cost 0.
- Tests: 60 unit tests, no network.

## Key lessons

1. **A citation can exist without supporting the claim.** v0 attaches real, on-topic sources to invented statements. Checking that `[n]` exists is not enough; an LLM judge must check that the source entails the sentence (citation accuracy).
2. **Embedding similarities are compressed** (`mistral-embed`: 0.85–0.88 in-domain). Thresholds must be calibrated on this model, not copied; out-of-domain questions still show a gap (~0.80).
3. **Measure limits instead of guessing them**: embedding batch size and free-plan model access were both found by testing the API, not from documentation.
4. **One fiche often fills the whole top-5**, which limits context diversity.
