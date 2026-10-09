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
