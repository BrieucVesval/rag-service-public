# RAG pipeline

Production-grade RAG pipeline: hybrid search (dense + BM25), reranking, grounded generation with verified citations, and an evaluation harness.

Work in progress. See `docs/project_overview.md` for the big picture and `docs/project_log.md` for every step taken and why.

## Data

Corpus: [Fiches pratiques et ressources de Service-Public.gouv.fr Particuliers](https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers), produced by the Direction de l'information légale et administrative (DILA), published under the Licence Ouverte / Open Licence 2.0. The download date and file list of the snapshot in use are recorded in `data/raw/service_public/manifest.json`.

```bash
python scripts/fetch_corpus.py --theme Logement   # download raw XML fiches
uv run python scripts/ingest.py                   # raw XML -> data/processed/ (Markdown documents)
```

## Usage

Requires a Mistral API key in `.env` (see `.env.example`; the free plan is enough).

```bash
uv sync
uv run python scripts/build_index.py              # chunk, embed, store in ChromaDB
uv run python scripts/ask.py "Quel est le préavis pour quitter un logement loué vide ?"
uv run pytest                                     # unit tests, no API calls
```
