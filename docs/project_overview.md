# Project overview

High-level view of how the project evolves: one line per step, key decisions, key numbers.
Details, alternatives and reproduction commands are in [`project_log.md`](project_log.md).
Interview talking points, grouped by theme, are in [`interview_notes.md`](interview_notes.md).

**Goal**: a production-grade RAG over French public-service fiches (Service-Public.gouv.fr, *Logement*), where every choice is measured: faithfulness, citation accuracy, hybrid vs. dense retrieval, chunking strategies.

## Status

- **Current**: v0 fully measured on dev, judge checked by adjudication: Recall@5 0.67, refusal accuracy 0.93; judge metrics faithfulness 0.93, citation accuracy 0.95, precision 0.80, correctness 0.61, i.e. 0.90 / 0.92–0.93 / 0.77–0.78 / 0.59 after correcting the judge's errors on the hard-case sample. Aggregates and correctness are usable (±3 points); sentence verdicts miss a third of unsupported claims.
- **Next**: merge the evaluation harness, then improve retrieval (header-based chunking, hybrid dense + BM25, reranking), each change measured.

## Roadmap

| # | Milestone | Status |
|---|---|---|
| 1 | Corpus and ingestion (incl. merged table cells fix) | ✅ Done |
| 2 | Minimal end-to-end RAG (v0) | ✅ Done |
| 3 | Golden set (50 questions) | ✅ Done |
| 3b | Evaluation harness | ✅ Done (judge validated by an LLM panel; human labels still open) |
| 4 | Baseline evaluation of v0 | ✅ Done on dev |
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
| 2026-10-09 | 6. Golden set | 50 questions (20 lookup, 12 multi-hop, 10 unanswerable, 8 ambiguous), 30 dev / 20 test | Every reference fact backed by a verbatim quote checked automatically; bias measured (title overlap 0.16, 20/28 sub-themes) |
| 2026-10-10 | 7. Table cells fix | Merged cells (colspan/rowspan) laid out on a grid, two-row headers merged; 17 fiches, 242 chunks re-embedded | Repeat merged text in every covered cell so each row reads on its own |
| 2026-10-10 | 8a. Retrieval evaluation | Recall@k, All@k, MRR, evidence recall; one JSON run file per run with commit, config, index and golden set hash. v0 dev: R@5 0.67, Evid@5 0.50, multi-hop All@5 0.14 | Fiche-level metrics (independent of chunking) plus evidence recall for the passage level |
| 2026-10-10 | 8b-0. Judge choice | Free plan has no model stronger than the generator; prices compared; switched to the paid plan | Mistral Large 3 as judge (~$0.21 per dev run, ~4x cheaper than Medium 3.5) |
| 2026-10-10 | 8b-1. Generation run | Answers + contexts saved for later judging; refusal accuracy 0.93, 6/6 correct refusals, 2/24 false refusals; cost $0.017 | Generate once, judge later: judges compared on identical answers |
| 2026-10-10 | 8b-2. LLM judge | Sentence-level support and key-fact correctness; v0 dev: faithfulness 0.93, citation accuracy 0.95, precision 0.80, correctness 0.61; $0.06 per run | Strict JSON-schema output (JSON mode returned invalid JSON); judge stability measured: 94% |
| 2026-10-12 | 8b-3. Judge validation | 61-item blind sample labelled by Claude; 24 items (16 disagreements + 8 audited agreements) adjudicated by a panel of 3 Claude subagents (Fleiss κ 0.83). Judge vs. final labels: sentences 0.70 (κ 0.52), facts 0.84 (κ 0.77); corrected faithfulness 0.90, correctness 0.59 | Human labelling stopped after 1 item (time): LLM panel instead, limit stated (same model family, validity vs. a human not measured) |

## Key numbers so far

- Corpus: 333 documents, 800k words, median 1,303 words per fiche, max ~40k.
- Index: 2,832 chunks, vectors of 1,024 dimensions, 61 MB. Full rebuild: 1.74M tokens, ~2 min, cost 0.
- v0 on 4 manual questions: 1 correct, 1 correct refusal, 2 with unsupported claims. Latency 2–5 s, cost 0.
- Golden set: 50 questions, 109 verified evidence quotes (113 key facts), mean title overlap 0.16, 20/28 sub-themes covered.
- Merged table cells: 405 in 90 tables (17 fiches); the fix changed 5% of fiches but 8.5% of chunks.
- v0 retrieval, dev (24 answerable questions): Recall@5 0.67 (lookup 0.83, multi-hop 0.50, ambiguous 0.50), evidence recall@5 0.50, MRR 0.65, multi-hop All@5 0.14; 2.77 distinct fiches per top-5.
- Top similarity: answerable 0.846–0.917, unanswerable 0.788–0.840 (dev).
- v0 generation, dev: refusal accuracy 0.93 (6/6 unanswerable refused, 2/24 false refusals), 3.55 citations per answer, no invalid citation; $0.017 for 30 answers (78k prompt tokens).
- v0 judged, dev: faithfulness 0.93, citation accuracy 0.95, citation precision 0.80, correctness 0.61 (0.67 when the fiche is retrieved, 0.40 when not); judge $0.061 per dev run.
- Judge stability: 94% sentence and 89% key-fact verdict agreement between two runs on identical answers.
- Judge validation (61 hard-case items, final labels from a 3-Claude panel): sentences 0.70 (κ 0.52), key facts 0.84 (κ 0.77, 0.94 present vs. not); judge recall on unsupported claims 9/14; slightly lenient: faithfulness 0.93 → 0.90, citation accuracy 0.95 → 0.92–0.93, correctness 0.61 → 0.59.
- Tests: 137 unit tests, no network.

## Key lessons

1. **A citation can exist without supporting the claim.** v0 attaches real, on-topic sources to invented statements. Checking that `[n]` exists is not enough; an LLM judge must check that the source entails the sentence (citation accuracy).
2. **Embedding similarities are compressed** (`mistral-embed`: 0.85–0.88 in-domain). Thresholds must be calibrated on this model, not copied; out-of-domain questions still show a gap (~0.80).
3. **Measure limits instead of guessing them**: embedding batch size and free-plan model access were both found by testing the API, not from documentation.
4. **One fiche often fills the whole top-5**, which limits context diversity.
5. **Building the benchmark found a data bug**: merged table cells were dropped by the loader, shifting columns (fixed in step 7). Looking closely at the data while writing reference answers is a quality check in itself.
6. **Bias in an evaluation set can be measured, not only discussed**: lexical overlap with titles and topic coverage are reported by the validator.
7. **An upstream fix invalidates everything downstream, and fixed-size chunking amplifies it**: a loader fix on 17 fiches changed 242 chunks, because inserted text shifts every later window. Incremental indexing needs content hashes, and structure-aware chunking would confine changes to their section.
8. **Finding the right fiche is not finding the right passage**: v0 retrieves an expected fiche for 67% of questions but only 50% of the answering sentences. Measuring both (fiche recall and evidence recall) separates a search problem from a chunking problem.
9. **Check the metric before trusting it**: evidence recall could have been biased by quotes cut at chunk boundaries; all 109 quotes were verified to fit in a chunk. Building the harness also exposed a miscount in the docs (128 quotes reported, 109 real).
10. **The same query does not always give the same embedding**: two identical runs gave score drifts up to 0.0056 on 6/30 questions, enough to swap close chunks. A gain smaller than run-to-run noise is not a gain; caching query embeddings makes runs repeatable.
11. **An LLM judge is a measuring instrument with its own noise and errors**: two runs on identical answers agreed on 94% of verdicts, flipped on the most important case (q021), and one verdict contradicted its own reason. Human agreement must be measured before trusting it.
12. **"JSON mode" is not a guarantee**: it returned truncated JSON, identically on retry at temperature 0. Strict schema-constrained output fixed it; a retry cannot fix a deterministic error.
13. **Most v0 errors come from retrieval, not generation**: faithfulness 0.93 but correctness 0.61, and correctness drops from 0.67 to 0.40 when no expected fiche is retrieved.
14. **Validate the judge, then trust it for what it measures well**: the Mistral Large 3 judge agrees well on key facts (κ 0.77) but misses a third of unsupported sentences, including contradicted ones and the known q021 failure. Aggregates move by only 2–3 points, so the diagnosis holds; per-answer hallucination detection needs a better judge.
15. **An LLM panel measures consistency, not truth**: 3 Claude annotators agreed with each other (κ 0.83) and sided 13/16 with the first Claude annotator, which is partly a shared model bias. Only human labels (or another model family) measure validity.
