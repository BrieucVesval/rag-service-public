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
