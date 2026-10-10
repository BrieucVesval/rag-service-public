# Project log

Chronological catalogue of every step of the project: what was done, why, and how to reproduce it.
Newest entries at the bottom. Each entry: date, phase, what, why (alternatives considered), how to reproduce, files touched, open points.

---

## Step 1 — Corpus choice

- **Date**: 2026-10-07
- **Phase**: 0
- **What**: Chose the Service-Public.gouv.fr "Fiches pratiques et ressources – Particuliers" dataset as the corpus. Starting with the *Logement* theme only.
- **Why**:
  - Looks like a real client use case (customer-service / public-service assistant).
  - French content, which showcases multilingual handling.
  - Clean, structured XML (sections, metadata, breadcrumbs), so effort goes into RAG rather than parsing.
  - Easy to write a golden set without domain expertise. Multi-hop questions arise naturally (conditions + exceptions, linked Q&A fiches).
  - Open license (Licence Ouverte 2.0, attribution required).
  - Alternatives considered: public PDF reports (Cour des comptes, annual reports; realistic but PDF extraction is a large upfront effort) and drug leaflets from ANSM (high stakes, sensitive domain). PDFs may be added later for multi-format ingestion.
  - Starting with one theme (~350 fiches) keeps iterations fast and cheap, and answers can be checked by hand.
- **Dataset facts** (2026-10-07):
  - Full archive: 23 MB zipped, 149 MB unzipped, 5,574 XML files.
  - F = content fiches (~3,000), R = resources such as forms and simulators (~2,300), N = navigation (~240).
  - XML schema v3.5, updated daily. New fields may appear at any time, so parsers must ignore unknown fields.
- **Open points**: incremental re-ingestion (the feed changes daily; avoid re-embedding everything).

## Step 2 — Fetch the raw corpus

- **Date**: 2026-10-07
- **Phase**: 0
- **What**: Wrote `scripts/fetch_corpus.py`, which downloads the official archive, keeps the F fiches whose `dc:subject` contains the theme, copies them untouched into `data/raw/service_public/`, and writes a `manifest.json` (source, license, producer, download date, file list).
- **Why**: reproducibility (anyone can rebuild the same corpus), traceability of which data version an experiment ran on, and easy refresh or extension to other themes. Uses the standard library only (no dependency). Refuses to write into a non-empty output directory to protect raw data.
- **Result**: 350 fiches (147 information fiches, 169 Q&A, 17 guided searches, plus multi-theme fiches), 14 MB.
- **Reproduce**: `python scripts/fetch_corpus.py --theme Logement`
- **Files**: `scripts/fetch_corpus.py`, `data/raw/service_public/`
- **Open points**: the 17 "guided search" fiches are decision trees (~10k words each); decide at ingestion whether to keep, split or exclude them.

## Step 3 — Version control

- **Date**: 2026-10-07
- **Phase**: 0
- **What**: Git repository with a `.gitignore` and a branch workflow (documented in `CLAUDE.md`, section "Git workflow").
- **Why**: history and rollback, one branch per feature so `main` always works, and a clean public history for the portfolio.
  - Raw XML is not versioned: it is reproducible with `scripts/fetch_corpus.py`, changes daily and would bloat the history. `manifest.json` is versioned so each commit records which data snapshot it used.
  - Alternative considered: committing the raw XML (fully self-contained repo, but ~14 MB per snapshot and noisy diffs). Git LFS or DVC could be revisited if the corpus grows.
- **Files**: `.gitignore`, `CLAUDE.md`

## Step 4 — XML loader (raw XML → Markdown Documents)

- **Date**: 2026-10-07
- **Phase**: 1 (ingestion)
- **What**:
  - Python project set up with uv (`pyproject.toml`): `pydantic` for data models, `defusedxml` for safe XML parsing (protects against entity-expansion "XML bomb" attacks); dev tools `pytest`, `ruff`, `mypy --strict`.
  - `Document` model (`src/rag/models.py`): normalized Markdown text + metadata (doc_id, source, title, url, doc_type, modified_at, breadcrumb, themes, description).
  - Parser `src/rag/ingestion/service_public.py`: `parse_fiche(bytes)` / `fiche_to_document(Element)` → `Document`. Pure functions, no I/O.
  - Script `scripts/ingest.py`: reads `data/raw/service_public/`, writes one JSON Document per fiche to `data/processed/service_public/<ID>.json` plus a `manifest.json` (raw snapshot date, counts per type, excluded IDs, parser warning count).
- **Why** (choices and alternatives):
  - **Markdown rendering that preserves structure**: `Chapitre`/`SousChapitre`/`Situation` become `##`/`###` headings; conditional cases (`BlocCas`/`Cas`, e.g. "À Paris" vs "Cas général") become nested headings prefixed `Cas : `, capped at `######`. A rule therefore stays attached to the condition it applies to, which header-based chunking can exploit. Alternative: plain text extraction (`itertext`), simpler but loses which case a rule belongs to, a classic source of wrong answers.
  - Lists → Markdown bullets/numbers (nested), tables → Markdown tables with caption (first row as header), callouts (`ASavoir`, `Attention`, `ANoter`, `Exemple`…) → blockquotes with their title, "Où s'adresser" / "Service en ligne" → one line with their title only.
  - **Inline markup flattened** (link text kept, URLs/emphasis dropped): clean text for embeddings and BM25. Inter-fiche links could be used later for multi-hop retrieval.
  - **Dropped**: navigation (`DossierPere`, `VoirAussi`, `QuestionReponse`…), legal references, questionnaire logic (`Condition`), media, and the glossary (`Definition`, `Abreviation`) for v1.
  - **Robust to schema drift** (the feed changes daily): unknown body elements keep their text and log a warning; unknown top-level elements log a warning. Never raises except on a missing fiche ID.
  - **17 "Recherche guidée" fiches excluded** from v1: ~10k-word decision trees that overlap other fiches and are hard to chunk well. Recorded in the processed manifest; re-including them can be measured later.
  - **One JSON per fiche** rather than a single JSONL: easy to inspect by hand and to update per fiche (incremental re-ingestion). JSONL would load faster but is less readable.
  - Paths passed as CLI arguments for now; `config.py` (pydantic-settings) will be introduced with the first real tunable parameters (chunk sizes, top-k).
  - `processed/` is regenerable (gitignored), so `--overwrite` is allowed and removes stale files; without it the script refuses to touch a non-empty output.
- **Result** (raw snapshot downloaded 2026-10-07):
  - 333 documents (176 Q&A, 157 information fiches), 17 guided searches excluded, **0 parser warnings**.
  - Words per document: min 24 (F20554), median 1,303, p90 ~4,750, max 39,645 (F1314); 30 documents above 5,000 words; 800k words total.
  - Rough embedding cost of the whole corpus with `text-embedding-3-small` (~1.1M tokens): a few cents.
- **Tests**: `tests/ingestion/test_service_public.py`, 15 tests on hand-written minimal XML (metadata, heading hierarchy and cap, situations, lists, tables, callouts, skipped elements, unknown elements, missing ID). Hand-written fixtures instead of real fiches: the real feed changes daily and is not versioned, so tests stay deterministic.
- **Reproduce**:
  ```bash
  uv sync
  uv run pytest
  uv run python scripts/ingest.py --overwrite
  ```
- **Files**: `pyproject.toml`, `uv.lock`, `README.md`, `src/rag/models.py`, `src/rag/ingestion/`, `scripts/ingest.py`, `tests/ingestion/test_service_public.py`
- **Open points**:
  - Very long fiches (up to ~40k words) make chunking essential; compare strategies in the chunking step.
  - Glossary entries (`Definition`, `Abreviation`) could become separate small documents.
  - Missing `dc:title` yields an empty title (never observed in the corpus).

## Step 5 — Minimal end-to-end RAG (v0)

- **Date**: 2026-10-08
- **Phase**: 0 (minimal end-to-end)
- **Goal**: a naive but complete pipeline, question → dense retrieval → grounded answer with citations. It is the baseline every later improvement is measured against.
- **Provider decision**: Mistral API, free "Experiment" tier, for both embeddings (`mistral-embed`) and generation (Mistral Small).
  - Why: zero cost while developing; strong French; relevant to the Mistral application. The corpus is public, so the free tier's data-usage terms are not a concern.
  - Alternatives considered:
    - OpenAI `text-embedding-3-small` + Claude Sonnet 5.5 (initial plan). Estimated cost ~$0.03 per full indexing and ~1 cent per question; ~$15–30 for the whole project including evaluations. Kept as a later comparison.
    - Local LLM with Ollama (Mistral 7B / Ministral 8B). Free and offline, but weaker at citing and refusing, and the dev machine (M4, 16 GB RAM, ~15 GB free disk) leaves little room. Kept as a later "self-hosted" comparison.
  - Trade-off: free-tier rate limits (~1 request/s) slow down indexing and evaluation runs.
- **Sub-steps**: 5a config + chunk model + fixed-size chunker (no API calls); 5b embeddings + Chroma index; 5c dense retrieval + generation + CLI.

### 5a — Config, Chunk model, fixed-size chunker

- **What**:
  - `src/rag/config.py`: `Settings` (pydantic-settings) loaded from env and `.env`. Pipeline settings use the `RAG_` prefix; the API key is `MISTRAL_API_KEY`, stored as `SecretStr` so it never appears in logs or reprs. Validates `chunk_overlap < chunk_size`. `.env.example` documents every setting.
  - `Chunk` model (`src/rag/models.py`): text, deterministic `chunk_id` (`<doc_id>:<strategy>:<position>`), strategy, position, character offsets in the document, document title and URL (needed for citations).
  - `Chunker` protocol (`src/rag/chunking/base.py`) and `FixedSizeChunker` (`src/rag/chunking/fixed.py`): windows of `chunk_size` characters with `chunk_overlap` characters of overlap, boundaries snapped to whitespace so words are never cut.
- **Why**:
  - Fixed-size is the baseline the structure-aware strategies (headers, semantic) must beat. It deliberately ignores the Markdown structure.
  - Sizes in characters rather than tokens: no tokenizer dependency, simple and deterministic; ~4 characters per token in French, so 2,000 characters ≈ 500 tokens, far below `mistral-embed`'s input limit. Alternative: token-based sizes (exact w.r.t. model limits, but ties chunking to one tokenizer).
  - Overlap (10%) so a sentence cut at a boundary still appears whole in one of the two chunks. Cost: ~10% more text to embed and some duplicate hits at retrieval.
  - Custom ~60-line implementation instead of LangChain's `CharacterTextSplitter`: no dependency for the baseline, exact offsets for each chunk. LangChain splitters will be used for the header-based strategy.
  - Deterministic chunk IDs: re-chunking gives the same IDs, which keeps the dense and BM25 indexes in sync and allows incremental updates.
- **Result** (dry run on the 333 processed documents, defaults 2,000 / 200):
  - 2,828 chunks; median length 1,997 characters, min 180; median 5 chunks per document, max 129 (F1314); 29 documents fit in a single chunk.
  - ~5.3M characters to embed (~1.4M tokens).
  - Visible weakness: chunks start mid-section and lose the heading context, e.g. a chunk about "Cas : Votre époux … est hébergé en Ehpad" does not contain the fiche title or parent section. This is what header-based chunking (or contextual headers) should fix, and will be measured.
- **Tests**: `tests/test_config.py` (3 tests: defaults, env override, secret not in repr, overlap validation) and `tests/chunking/test_fixed.py` (11 tests: metadata, empty text, size limit, no cut words, offsets, full coverage, overlap, zero overlap, text without spaces, deterministic IDs, invalid parameters). 29 tests pass in total.
- **Dependency added**: `pydantic-settings` (typed config from env/.env).
- **Reproduce**: `uv sync && uv run pytest`
- **Files**: `src/rag/config.py`, `src/rag/models.py`, `src/rag/chunking/`, `tests/test_config.py`, `tests/chunking/`, `.env.example`, `pyproject.toml`, `uv.lock`

### 5b — Embeddings and Chroma index

- **Date**: 2026-10-09
- **What**:
  - `src/rag/indexing/embedder.py`: `Embedder` protocol, `MistralEmbedder` (batches of `embedding_batch_size` texts, client-side `RateLimiter`, tokens counted from the API usage, vectors re-ordered by the returned index), `make_mistral_client` (SDK retries on 429/5xx with exponential backoff, honoring `Retry-After`).
  - `src/rag/indexing/chroma_store.py`: `ChromaStore` (persistent client, telemetry off, cosine distance, no Chroma default embedding function, idempotent `upsert` by chunk ID, `reset` for rebuilds) and `collection_name(strategy, size, overlap, model)`.
  - `src/rag/ingestion/processed.py`: `load_processed_documents`.
  - `scripts/build_index.py`: chunk → embed → store. Refuses to overwrite a non-empty collection without `--rebuild`. Collection metadata records chunking parameters, embedding model, build date, git commit, and the processed/raw snapshot dates.
  - New settings: `chroma_dir`, `embedding_model`, `embedding_batch_size`, `mistral_requests_per_minute`, `mistral_timeout_s`, `mistral_max_retry_s`.
- **Why**:
  - One Chroma collection per index configuration (e.g. `fixed-2000-200-mistral-embed`): chunking strategies and embedding models can coexist and be compared without rebuilding.
  - Embeddings computed by our `Embedder`, never by Chroma: otherwise Chroma silently downloads and uses its own default model, which would make results depend on a hidden component.
  - Batch size 32 measured, not guessed: on 2026-10-08, 32 chunks (~21k tokens) and 64 chunks (~42k tokens) were accepted, 128 chunks were rejected with "Too many tokens overall". 32 leaves a 2x safety margin for longer chunks.
  - Rate limiting at two levels: a client-side limiter at 50 requests/minute (free tier allows 60) and SDK retries for the 429s that still happen.
  - Official `mistralai` SDK rather than raw HTTP: typed responses and built-in retries. Alternative: `httpx` calls (one dependency less, more code to maintain).
  - Cosine distance: standard for text embeddings, independent of vector norm.
- **Result** (2026-10-09):
  - 2,828 chunks embedded and stored in 155 s; 1,736,868 tokens (~3.1 characters per token, more than the ~4 estimated: French + Markdown); vectors of dimension 1,024; index size 61 MB. Cost: 0 (free tier).
  - Three 429 responses during the run despite the limiter, all recovered by SDK retries: the free tier likely also limits tokens per minute, not only requests.
  - Smoke test, top-3 by cosine similarity:
    - "Quel est le préavis pour quitter un logement loué vide ?" → F1168 (préavis et formalités du congé donné par le locataire), then F32360 twice (calcul du délai de préavis). Relevant.
    - "Faut-il une autorisation pour transformer un bureau en logement à Paris ?" → F35336 (changement de destination ou d'usage), F37976 (division d'un bâtiment), F35336. Relevant, but F2416 ("Comment transformer un local professionnel ou commercial en logement ?") is not in the top 3. A case to track in the golden set.
- **Observations / pitfalls**:
  - `mistral-embed` similarities are compressed in a narrow band (0.868–0.884 for the top-3 above). Absolute thresholds are therefore fragile: the planned dedup threshold (cosine > 0.95) and any retrieval-confidence threshold must be calibrated on this model's score distribution, not copied from OpenAI defaults.
  - The same document can occupy several top-k slots (adjacent chunks of F32360 and F35336), reducing the diversity of the context given to the LLM.
- **Tests**: `tests/indexing/test_embedder.py` (7 tests, fake client and fake clock: batching, ordering, token counting, incomplete response, rate limiter spacing, missing API key), `tests/indexing/test_chroma_store.py` (6 tests on a temporary on-disk Chroma: naming, metadata without None, persistence, idempotent upsert, reset, length mismatch), `tests/ingestion/test_processed.py` (2 tests). 44 tests pass in total, no network.
- **Dependencies added**: `mistralai` (official Mistral SDK: embeddings, chat, retries), `chromadb` (persistent vector store). The virtual environment grew from 110 MB to 437 MB.
- **Reproduce**:
  ```bash
  uv sync
  echo "MISTRAL_API_KEY=..." > .env   # free "Experiment" tier is enough
  uv run python scripts/build_index.py            # --rebuild to rebuild
  ```
- **Files**: `src/rag/config.py`, `src/rag/indexing/`, `src/rag/ingestion/processed.py`, `scripts/build_index.py`, `tests/indexing/`, `tests/ingestion/test_processed.py`, `.env.example`, `pyproject.toml`, `uv.lock`
- **Open points**: dedup before insertion (threshold to calibrate), BM25 index on the same chunk IDs, incremental re-indexing (only changed fiches).

### 5c — Dense retrieval, grounded generation, `ask` CLI

- **Date**: 2026-10-09
- **What**:
  - Models: `RetrievedChunk` (chunk, cosine similarity, rank), `Citation` (a `[n]` marker resolved to a chunk), `Answer` (text, refused flag, citations, invalid citation numbers, retrieved chunks, resolved model name, tokens, latency per stage).
  - `ChromaStore.query` and `src/rag/retrieval/`: `Retriever` protocol, `DenseRetriever` (embed the question, nearest chunks by cosine similarity).
  - `src/rag/generation/`: `prompts.py` (system prompt with grounding rules, context as numbered blocks `[n] title / URL / text`, fixed refusal sentence), `citations.py` (extract `[1]`, `[1, 2]`, `[1][3]`; flag numbers that point to no block), `llm.py` (`LLM` protocol, `MistralLLM` with temperature 0, fixed `random_seed`, its own rate limiter, resolved model name and token usage returned).
  - `src/rag/pipeline.py`: `RAGPipeline` (retrieve → generate → resolve citations). No LLM call when nothing is retrieved. One structured JSON log line per query: chunk IDs, scores, ranks, cited and invalid numbers, tokens, latency per stage (retrieval, generation, total).
  - `scripts/ask.py "question"` (`--show-context`, `--json`).
- **Why**:
  - Fixed refusal sentence, detected by string match: simple and testable. Alternative: structured JSON output (`{"answer", "refused", "citations"}`), more robust but harder for a small model and less readable; to revisit if refusal detection proves unreliable.
  - Citations checked structurally here (block exists); whether the block supports the claim is the job of the LLM-as-judge (step 6 of the architecture).
  - Prompt instructions in English, answers requested in French: repo convention; instruction language vs. answer quality could be measured later.
  - Temperature 0 and fixed seed: reproducible runs for evaluation.
- **Provider change (measured)**: on the free plan, `mistral-small-*`, `mistral-medium-*` and `magistral-small` return 429 with `x-ratelimit-limit-req-minute: 0` (no access), while `ministral-14b-2512` (30 req/min, 937k tokens/min), `ministral-8b-2512` (188 req/min) and `ministral-3b` are available. Default generation model is therefore `ministral-14b-2512`, the largest available. Mistral Small remains a later comparison (needs a paid plan).
- **Result** (4 manual questions, `ministral-14b-2512`, top-5, 2026-10-09):
  - "Quel est le préavis pour quitter un logement loué vide ?" → 3 mois, 1 mois en zone tendue, cited [1][2][5]. Correct and grounded. 2.9k tokens in / 99 out, 2.2 s.
  - "Faut-il une autorisation pour transformer un bureau en logement à Paris ?" → long answer; F2416 now appears in the top-5 (ranks 4–5). **Faithfulness problems**: it states that Paris has no compensation requirement (not in the sources, and an inference from absence), conflates *changement d'usage* (housing → other use) with *changement de destination*, and adds an irrelevant exemption. Several claims carry a citation that does not support them. 5.3 s.
  - "Combien coûte un passeport ?" (out of corpus) → correct refusal. Top similarity 0.799 vs. 0.85–0.88 for in-domain questions: even with compressed scores, out-of-domain questions show a visible gap, a candidate signal for the confidence score.
  - "Mon propriétaire peut-il garder mon dépôt de garantie si je laisse des trous de cheville… ?" → "Oui… s'ils sont considérés comme des dégradations" with correct justification documents [5]. The sources never mention wall plugs: the "Oui" is an unsupported inference. Retrieval is all from F31269 (5 chunks of the same fiche).
  - Latency 2–5 s, dominated by generation (retrieval 0.3–0.9 s). Cost: 0.
- **Takeaways for the next steps**: citations that are present but do not support the claim are the main failure mode, so citation verification (LLM-as-judge) is needed and the golden set must include cases like "bureau → logement à Paris" and "trous de cheville". Top-k is often filled by one fiche, limiting context diversity.
- **Tests**: `tests/generation/` (citations, prompts, LLM with fake client), `tests/retrieval/test_dense.py` (on-disk Chroma with fake embedder), `tests/test_pipeline.py` (fake retriever and LLM: citations, invalid citations, refusal, no-retrieval short-circuit, structured log). Shared fixture in `tests/conftest.py`. 60 tests pass, no network.
- **Reproduce**:
  ```bash
  uv run python scripts/build_index.py   # once (5b)
  uv run python scripts/ask.py --show-context "Quel est le préavis pour quitter un logement loué vide ?"
  ```
- **Files**: `src/rag/models.py`, `src/rag/config.py`, `src/rag/indexing/chroma_store.py`, `src/rag/retrieval/`, `src/rag/generation/`, `src/rag/pipeline.py`, `scripts/ask.py`, `tests/conftest.py`, `tests/generation/`, `tests/retrieval/`, `tests/test_pipeline.py`, `.env.example`, `CLAUDE.md`
- **Open points**: golden set and first measured evaluation of v0; LLM-as-judge for citations; per-stage latency split of retrieval into embedding vs. vector search; context diversity (one fiche filling the top-k).

#### 5c analysis — Citations that exist but do not support the claim

- **Observed case**: for "Faut-il une autorisation pour transformer un bureau en logement à Paris ?", the answer contains "Aucune mention de compensation obligatoire (contrairement à certaines communes) [1]". Block [1] (F35336) only says the procedure differs depending on whether the commune requires compensating the loss of housing; it says nothing about Paris. The model inferred "no compensation in Paris" from the absence of Paris in the chunk, and the inference is wrong (Paris is one of the communes that require compensation). The citation points to a real, on-topic source, so the sentence looks grounded.
- **Three levels of citation quality**:

  | Level | Example | Detected by v0? |
  |---|---|---|
  | 1. No citation | "Le préavis est de 3 mois." | Yes (easy) |
  | 2. Citation to a non-existent block | "… [9]" with 5 blocks | Yes (`invalid_citation_numbers`) |
  | 3. Citation to a real block that does not say it | "Pas de compensation à Paris [1]" | **No** |

- **Why level 3 is the most harmful**: the citation gives an appearance of reliability to an invented statement, so the user has no reason to double-check. In an administrative context, it can lead someone to skip a mandatory step. Our v0 only checks that `[n]` points to an existing block, not that the block entails the sentence.
- **Planned fix: LLM-as-judge citation verification** (architecture step 6):
  - Split the answer into (claim, cited block) pairs; ask a judge LLM whether the block **supports**, **does not support**, or **contradicts** the claim. The judge's task (entailment on a short passage) is much simpler than answering.
  - Metric: **citation accuracy** = share of cited claims supported by their source. Also usable at runtime to drop or flag unsupported sentences before showing the answer.
  - Pitfall: the judge is itself an LLM and can be wrong. Its verdicts must be checked by hand on a sample to measure its own agreement with a human before trusting the metric.
- **Interview narrative**: "My first version cited its sources and correctly refused out-of-scope questions, so it looked reliable. Testing showed it attached citations to claims the source did not contain. Checking that a citation exists is not enough; it must support the sentence. I added LLM-as-judge verification and measured citation accuracy before and after." (Fill in the measured numbers once step 6 is done.)

## Step 6 — Golden set

- **Goal**: a fixed set of ~50 questions with reference answers, used to evaluate every version of the pipeline. Without it, "strategy A is better than B" is an opinion; with it, it is a measured difference.
- **Composition target**: 20 lookup, 12 multi-hop, 10 unanswerable, 8 ambiguous; 30 `dev` / 20 `test` with the same category proportions. `test` questions are never looked at while tuning (avoids overfitting the pipeline to the exam).
- **Method**:
  - Fiches sampled across sub-themes (breadcrumb level 3: urbanisme, bail, loyer, copropriété, diagnostics, aides…) so questions do not cluster on one topic.
  - Claude drafts questions in batches of 10, phrased as a user's situation ("mon proprio", "ma caution"), never copying the fiche title; reference answers and quotes come from the fiche text.
  - The user reviews each batch for realism and lexical overlap with the fiches, without reading the fiches. Answer correctness is guaranteed mechanically instead (verbatim evidence quotes).
  - Unanswerable questions are checked against the corpus (text search and index) before being accepted.
- **Known limitation**: all questions are drafted by an LLM, then reviewed. LLM-drafted questions tend to reuse the corpus vocabulary, which makes retrieval look easier than with real users. Handwritten questions by the user, written without looking at the corpus, would reduce this bias; they are optional for now and the limitation will be stated in the case study.

### 6a — Format and validator

- **Date**: 2026-10-09
- **What**:
  - `src/rag/evaluation/golden_set.py`: pydantic models `GoldenItem` / `GoldenSet` (category, split, origin as enums; unknown fields rejected; unanswerable questions must have no docs/evidence, others must have key facts, expected docs and evidence from those docs; unique IDs), `load_golden_set` (YAML), `check_against_corpus` (expected docs exist, every quote appears in its fiche, ignoring whitespace, case and typographic apostrophes), `composition`.
  - `scripts/validate_golden_set.py`: runs all checks, compares `corpus_snapshot` with the processed data, prints the category × split table; exit code 1 on any problem.
  - File `data/golden_set/golden_set.yaml` (versioned).
- **Why**:
  - `key_facts`: atomic facts are easier and more reliable for a judge to check one by one than comparing whole answers.
  - `expected_docs`: retrieval metrics (Recall@k, MRR) without any LLM, so free and deterministic.
  - `evidence` quotes checked mechanically: reference answers cannot be invented, including by the LLM that drafts them. This is what lets the user review questions without reading the fiches.
  - `corpus_snapshot`: Service-Public changes daily; a reference answer is only valid for the snapshot it was written on.
  - YAML rather than JSON: readable and editable by hand, supports comments. Alternative: JSONL (easier to append programmatically, harder to review).
- **Dependencies added**: `pyyaml` (read the golden set), `types-PyYAML` (dev, type stubs for mypy).
- **Tests**: `tests/evaluation/test_golden_set.py` (10 tests: valid items, required fields per category, unanswerable without docs, evidence from expected docs, unknown field/category, duplicate IDs, tolerant quote matching, missing doc and invented quote reported, YAML loading). 71 tests pass.
- **Reproduce**: `uv run python scripts/validate_golden_set.py`

### 6b — 50 questions drafted, validated and rebalanced

- **Date**: 2026-10-09
- **What**: 50 questions in `data/golden_set/golden_set.yaml`, in 5 batches: 20 lookup, 12 multi-hop, 10 unanswerable, 8 ambiguous; 30 dev / 20 test with the same proportions. 109 verbatim evidence quotes (113 key facts), all found in the corpus by `scripts/validate_golden_set.py`. (Corrected on 2026-10-10: this entry first said 128, a miscount found while building the evaluation harness.)
- **Review**: the user chose to trust the drafted questions without line-by-line review ("le but étant d'avoir un benchmark le plus fiable possible, avec le moins de biais"). Bias controls were therefore made mechanical and measured instead of relying on human review:
  - **Evidence quotes**: every key fact is backed by a verbatim quote checked against the fiche text.
  - **Lexical overlap with fiche titles** (`title_overlap`: share of the question's content words found in the expected fiche's title), reported by the validator. First pass: mean 0.19, one question at 0.75 (q046, rephrased). Final: **mean 0.16, max 0.40**.
  - **Sub-theme coverage** (breadcrumb level 3), reported by the validator. First pass: 15/28, rental topics over-represented and urbanism (the largest sub-theme, 52 fiches) under-represented. Six questions were replaced, same IDs, categories and splits (q005, q011, q012, q013, q018, q019 → noise, renovation aids, decennial guarantee, urbanism certificate, social housing, syndic). Final: **20/28**; uncovered sub-themes are small (3–10 fiches each).
  - **Answer depth**: lookups were deliberately taken deep in long fiches (up to ~95% of a 23k-character fiche) and from tables, since answers in the first paragraph are easy for any chunking.
  - **Unanswerable questions**: absence verified by text search over all 333 fiches. One candidate ("prix d'un DPE") was rejected because the corpus does answer it ("le prix du DPE n'est pas réglementé").
  - **No selection by the system under test**: questions were never run through the pipeline while being written, to avoid keeping only the ones the current retriever handles.
- **Design of the categories**:
  - Multi-hop: answers combine 2–3 fiches (e.g. deposit + tenant repairs, squat + winter truce, G-rated DPE + rent revision + rental ban). q021 and q022 come from the two v0 failures of step 5c.
  - Unanswerable: out of domain (passport, impound), false premise (non-existent "Ma Maison Verte" aid), local or contact data (Rennes recycling centre, ADIL Nantes), future value (IRL Q4 2027), near-domain traps (Bordeaux sale price vs. reference rents, taxe foncière amounts).
  - Ambiguous: under-specified questions whose answer depends on the lease type or the size of the project; the reference answer lists the cases.
- **Time-sensitive references**: q030 (rules change on 2027-01-01) and q031 (IRL table updated quarterly) are tied to the corpus snapshot.
- **Bug found while drafting**: the XML loader ignores merged table cells (`fusionHorizontale`, `fusionVerticale`; ~400 occurrences in the corpus). Columns shift: in F1165 the "Révision du loyer" row renders "Interdit" under "meublé" instead of "bail mobilité". This silently corrupts table facts given to the LLM. Questions avoid quoting affected rows; fixing the loader is the next fix (re-ingestion and re-indexing are free).
- **Known limitations**: all questions are LLM-drafted (no handwritten user questions yet); 50 questions give coarse metrics (one question = 2 points); the test split is small (20).
- **Tests**: 2 new tests for `content_words` and `title_overlap`. 73 tests pass.
- **Reproduce**: `uv run python scripts/validate_golden_set.py`
- **Files**: `data/golden_set/golden_set.yaml`, `src/rag/evaluation/golden_set.py`, `scripts/validate_golden_set.py`, `tests/evaluation/test_golden_set.py`
- **Open points**: fix merged table cells in the loader; evaluation harness and v0 baseline; optional handwritten questions.

## Step 7 — Fix merged table cells in the loader

- **Date**: 2026-10-10
- **Phase**: 1 (ingestion quality)
- **Problem**: the XML loader ignored the span attributes of `<Cellule>`: `fusionHorizontale="N"` (colspan) and `fusionVerticale="N"` (rowspan). Cells after a merged cell shifted left, so values ended up under the wrong column. In F1165, "Révision du loyer en cours de bail" showed "Interdit" under the furnished lease instead of the mobility lease, and the "Locataire" row put the mobility-lease conditions under the furnished lease. The LLM was given wrong table facts with nothing to flag them.
- **Inspection of the corpus** (`data/raw/service_public/`, 297 tables):
  - 405 merged cells in 90 tables across 17 fiches: 300 rowspan, 101 colspan, 4 both; spans from 2 to 5. Two are empty self-closing cells (`<Cellule fusionVerticale="2"/>`, the top-left corner of a two-row header).
  - Span values: rowspan 2 (280), rowspan 3 (19), rowspan 5 (1); colspan 2 (90), colspan 3 (8), colspan 4 (3); colspan 2 + rowspan 2 (4, in F1351, F2559, F31290, F34825).
  - Row types: 1,579 normal rows, 365 header rows; 229 tables with one header row, 68 with two.
  - Semantics are the same as HTML: covered cells are absent from the XML. Rebuilding the grid with this rule gives exactly the number of declared `<Colonne>` for every row of all 90 tables.
  - 68 tables have two header rows (never header rows mid-table), and that is where most spans are, e.g. F929: "Île-de-France" spanning "Paris ou ville limitrophe" and "Autre commune". Markdown tables allow a single header row, so the second one was rendered as a data row.
- **What**:
  - `_table_grid` lays cells out on a grid (standard HTML algorithm: skip columns still occupied by a rowspan from above, place each cell over its colspan × rowspan). The merged cell's text is **repeated in every covered position**.
  - Leading header rows are **merged column by column** into one Markdown header: distinct labels joined with " – " ("Île-de-France – Paris ou ville limitrophe de Paris"; a label spanning both rows is not duplicated).
  - Malformed span values fall back to 1 instead of raising.
- **Why** (and alternatives):
  - Repeat the text vs. leave covered cells empty (or a "↑" marker): repetition makes every row self-contained, which matters for the LLM and for chunking (a chunk can start mid-table and lose the row above). Cost: duplicated text (+10.7k characters, +0.22% of the corpus) and a repeated term weighs slightly more in BM25. An empty cell would be visually faithful but ambiguous ("empty" vs. "not applicable").
  - Merged header vs. two header rows: one explicit name per column, at the cost of longer labels.
  - Rejected for now: linearizing each row into sentences ("Révision du loyer – bail meublé : …"). Very readable for an LLM but verbose and changes every table; a possible chunking experiment later.
- **Result**:
  - Re-ingestion: 333 documents, 0 parser warnings, total words 800,548 → 802,413 (+1,865), median unchanged (1,303); **exactly the 17 expected fiches changed**, only their `text` field. Characters added per fiche: F33453 +2,853, F31290 +1,957, F1351 +1,924, F31601 +753, F2315 +615, F2559 +503, F21051 +490, F1165 +368, F35083 +208, F929 +208, F34825 +203, F1317 +156, F1219 +132, F17709 +132, F36961 +130, F35323 +46, F35784 +32. Corpus total 4,857,991 → 4,868,701 characters (+10,710, +0.22%).
  - Before / after (F1165, comparison table):
    ```
    before | Révision du loyer en cours de bail | Révision annuelle du loyer, si une clause du bail la prévoit | Interdit |  |
    after  | Révision du loyer en cours de bail | Révision annuelle du loyer, si une clause du bail la prévoit | Révision annuelle du loyer, si une clause du bail la prévoit | Interdit |
    before | Locataire | Toute personne peut être locataire | Le locataire doit être dans au moins 1 des situations suivantes : … |  |
    after  | Locataire | Toute personne peut être locataire | Toute personne peut être locataire | Le locataire doit être dans au moins 1 des situations suivantes : … |
    ```
  - Before / after (F929, two-row header):
    ```
    before | Nombre de personnes | Types de personnes | Île-de-France | Autre région |  |
    after  | Nombre de personnes | Types de personnes | Île-de-France – Paris ou ville limitrophe de Paris | Île-de-France – Autre commune | Autre région |
    ```
  - Re-indexing: 2,832 chunks (was 2,828), 1,740,254 tokens, 109 s, cost 0. **242 chunks changed (8.5%)** although only 5% of fiches changed: with fixed-size chunking, inserting text shifts every later window of the fiche.
  - F1165 checked in the Chroma index (`F1165:fixed:0001`): `| Révision du loyer en cours de bail | Révision annuelle … | Révision annuelle … | Interdit |`.
  - Golden set: all 109 evidence quotes still found ("All checks passed"); composition and bias indicators unchanged (title overlap mean 0.16, max 0.40; 20/28 sub-themes); q049's note updated.
  - Run times: re-ingestion a few seconds; rebuild 109 s of embedding (1 min 52 s wall clock including chunking and Chroma writes).
  - Checks: 78 unit tests pass, `ruff check` and `mypy src` clean.
- **Incident**: the first rebuild failed after 142 s with `RemoteProtocolError: Server disconnected without sending a response` (Mistral API), after SDK retries. No harm done: `build_index.py` embeds everything before `store.reset()`, so the previous index stayed intact; the second run succeeded.
- **Production pitfalls**:
  - Any upstream change (loader, chunking) makes everything downstream stale: processed documents, chunks, embeddings, and later the BM25 index. Rebuilding everything is fine here (free, ~2 min); with paid embeddings, re-embed only chunks whose content hash changed (incremental indexing).
  - Fixed-size chunking amplifies small edits (17 fiches → 242 chunks). Structure-aware chunking (by headers) would confine a change to its section, a point in favour of it for incremental updates.
  - Embedding the whole corpus in one all-or-nothing pass: a network failure near the end loses the whole run. Batching with checkpoints (or upserting batch by batch into a staging collection) would make rebuilds resumable.
- **Tests**: 5 new tests in `tests/ingestion/test_service_public.py` (colspan on the F1165 case, rowspan in first and middle column, colspan + rowspan with an empty self-closing corner and two header rows, no duplicated label in a merged header). 78 tests pass.
- **Reproduce**:
  ```bash
  uv run python scripts/ingest.py --overwrite
  uv run python scripts/build_index.py --rebuild
  uv run python scripts/validate_golden_set.py
  ```
- **Files**: `src/rag/ingestion/service_public.py`, `tests/ingestion/test_service_public.py`, `data/golden_set/golden_set.yaml` (q049 note), `docs/project_log.md`, `docs/project_overview.md`
- **Open points**: incremental indexing (content hashes); resumable embedding runs; the evaluation harness and v0 baseline are next.

## Step 8 — Evaluation harness

- **Goal**: turn the golden set into numbers. Every later change (chunking, hybrid search, reranking, prompts, models) is judged by the difference it makes on these numbers, measured the same way.
- **Sub-steps**: 8a retrieval metrics (no LLM, deterministic, free); 8b generation metrics with an LLM judge (correctness, faithfulness, citation accuracy).

### 8a — Retrieval metrics and the v0 retrieval baseline

- **Date**: 2026-10-10
- **What**:
  - `src/rag/evaluation/retrieval_metrics.py` (pure functions on ranked chunks): `recall_at_k`, `all_found_at_k`, `reciprocal_rank` / `first_relevant_rank`, `evidence_recall_at_k`, `first_rank_per_doc`.
  - `src/rag/evaluation/retrieval_eval.py`: `evaluate_retrieval` (one query per question at the deepest k), per-question `QuestionRetrieval` (hits with chunk IDs and scores, metrics, top similarity, latency) and `summarize_by_group` (overall, per category, per split).
  - `src/rag/evaluation/experiment.py`: `RunInfo` and `write_run`: one JSON file per run in `experiments/`, named `<UTC time>-<kind>-<retriever>-<collection>-<split>.json`, never overwritten.
  - `src/rag/provenance.py`: `git_commit`, `git_is_dirty`, `file_sha256`; shared with `scripts/build_index.py`, which now also records `git_dirty` in the index metadata.
  - `scripts/eval_retrieval.py --split dev|test|all` (default `dev`).
  - New settings: `golden_set_path`, `experiments_dir`, `eval_k_values` (default `[1, 3, 5, 10]`, `retrieval_top_k` always added). `validate_golden_set.py` reads the golden set path from settings.
  - `pyproject.toml`: `pythonpath = ["."]` for pytest, so tests share helpers (`tests.conftest.make_retrieved`, golden set item factories).
- **Metrics** (answerable questions only; unanswerable ones have no expected fiche):
  - **Recall@k**: share of expected fiches with at least one chunk in the top-k chunks. Recall@5 is the headline: top-5 is what the LLM receives.
  - **All@k**: share of questions whose expected fiches are *all* in the top-k. The one that matters for multi-hop questions.
  - **MRR** (mean reciprocal rank): mean of 1 / rank of the first chunk from an expected fiche (1.0 if first, 0.5 if second, 0 if absent in the top-10).
  - **Evidence recall@k**: share of the golden set's evidence quotes found verbatim (whitespace/case-insensitive) in a top-k chunk of their fiche. Fiche-level recall says "the right fiche was found"; evidence recall says "the sentence that answers was given to the LLM".
  - **Top similarity**: kept for every question, including unanswerable ones, to test whether retrieval scores can flag out-of-corpus questions.
- **Why** (and alternatives):
  - Fiche level rather than chunk level: chunk IDs change with the chunking strategy, fiche IDs do not, so strategies can be compared on the same golden set without re-annotating. Evidence recall recovers the passage-level view without chunk annotations.
  - One query per question at k = 10, all cut-offs computed from the same ranking: 1 embedding call per question instead of one per k.
  - The test split stays held out: default `dev`, `test` only for final reported numbers, to avoid tuning the pipeline on the exam.
  - Each run file records the git commit and whether the tree had uncommitted changes, the full settings (API key excluded), the index metadata (strategy, model, build date and commit), the golden set SHA-256 and corpus snapshot. Any number in the case study can be traced back to the code, config, index and exam that produced it.
  - Not used: libraries such as `ragas` or `ranx`. These metrics are ~60 lines, fully tested and transparent; a library would add a dependency and hide the definitions that will be discussed in interviews.
- **Check of the evidence-recall metric**: a quote cut by a chunk boundary could never be found, which would bias the metric. Verified: all 109 quotes fit inside at least one chunk (median 82 characters, max 171, chunk overlap 200). A zero evidence recall is therefore a real retrieval miss.
- **Result: v0 retrieval baseline, dev split** (30 questions, 24 answerable; dense `mistral-embed`, fixed chunks 2,000/200, top-k 5; run `experiments/20261010T162454Z-retrieval-dense-fixed-2000-200-mistral-embed-dev.json`, 36 s, cost 0):

  | Group | n | R@1 | R@3 | R@5 | R@10 | All@5 | Evid@5 | MRR | Top sim. |
  |---|---|---|---|---|---|---|---|---|---|
  | All (answerable) | 24 | 0.42 | 0.67 | **0.67** | 0.73 | 0.54 | **0.50** | 0.65 | 0.872 (all 30) |
  | Lookup | 12 | 0.58 | 0.83 | 0.83 | 0.92 | 0.83 | 0.65 | 0.69 | 0.885 |
  | Multi-hop | 7 | 0.36 | 0.50 | 0.50 | 0.57 | **0.14** | 0.60 | 0.76 | 0.896 |
  | Ambiguous | 5 | 0.10 | 0.50 | 0.50 | 0.50 | 0.40 | **0.00** | 0.40 | 0.874 |
  | Unanswerable | 6 | – | – | – | – | – | – | – | 0.815 |

- **Analysis**:
  - **One answerable question in three does not get its fiche into the LLM's context** (R@5 0.67), and only half of the answering sentences reach it (Evid@5 0.50). This bounds what generation can achieve: the LLM cannot cite what it was not given.
  - **Multi-hop is the weak spot**: only 1 of 7 questions gets all its fiches in the top-5 (All@5 0.14). A single query embedding lands near one of the topics, not all of them. Candidate fixes: more diverse results (one fiche filling several slots), query decomposition, hybrid search.
  - **Right fiche, wrong passage**: in q012, q045, q046 and q048 the fiche is in the top-5 but not the chunk with the answer (Evid@5 0, sometimes found at rank 6–10). Long fiches split into many 2,000-character chunks make this frequent; structure-aware chunking and reranking target it.
  - **Lack of diversity confirmed**: top-5 contains on average 2.77 distinct fiches out of 5 chunks; 2 questions get a top-5 from a single fiche.
  - **Total misses** (no expected fiche in top-5): q008 (lookup), q017 (lookup, expected fiche at rank 6), q024 (multi-hop, 0/3 fiches; neighbouring rent fiches F1310/F1314 retrieved instead of F1311 *révision du loyer*), q043 and q049 (ambiguous; both expect F1165, the generic lease comparison table, which is never retrieved).
  - **Out-of-corpus signal**: unanswerable questions have top similarity 0.788–0.840 (mean 0.815), answerable ones 0.846–0.917 (mean 0.886). On dev, a threshold around 0.843 separates them perfectly. With 6 vs. 24 questions this is a hint, not a calibrated threshold: to be validated on test before any use in the confidence score (step 5 of the roadmap).
  - **Latency**: 1.2 s mean per query (max 2.4 s), but this is dominated by the client-side rate limiter (50 requests/minute = one request every 1.2 s), not by the API or Chroma. Latency must be measured without the limiter to be meaningful; noted for the latency breakdown.
- **Provenance caveat**: this run was made with uncommitted changes (the harness itself), flagged `git_dirty: true` in the run file; the index was built during step 7 before its commit (metadata commit `2b6900d`). The baseline is re-run once the harness is committed, for a clean reference.
- **Tests**: `tests/evaluation/test_retrieval_metrics.py` (8: rank per fiche, recall counts fiches not chunks, all-found, reciprocal rank ×3, evidence recall with tolerant matching, evidence from another fiche ignored), `tests/evaluation/test_retrieval_eval.py` (4: single query at deepest k, unanswerable keeps top score, summary over answerable only, grouping), `tests/evaluation/test_experiment.py` (3: run ID, provenance without secrets, JSON written and never overwritten), `tests/test_provenance.py` (3), `tests/test_config.py` (+2: k values sorted with top-k, must be positive). 98 tests pass, no network.
- **Reproduce**:
  ```bash
  uv run python scripts/eval_retrieval.py              # dev split
  uv run python scripts/eval_retrieval.py --split test # final numbers only
  ```
- **Files**: `src/rag/evaluation/retrieval_metrics.py`, `src/rag/evaluation/retrieval_eval.py`, `src/rag/evaluation/experiment.py`, `src/rag/provenance.py`, `src/rag/config.py`, `src/rag/indexing/chroma_store.py` (`metadata` property), `src/rag/evaluation/golden_set.py` (`quote_in_text` made public), `scripts/eval_retrieval.py`, `scripts/build_index.py`, `scripts/validate_golden_set.py`, `tests/evaluation/`, `tests/test_provenance.py`, `tests/test_config.py`, `.env.example`, `pyproject.toml`, `experiments/`
- **Open points**: clean re-run of the baseline after commit; 8b generation metrics (LLM judge, choice of judge model); latency measured without the rate limiter; out-of-corpus threshold to validate on test.
