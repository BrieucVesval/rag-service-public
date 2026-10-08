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
