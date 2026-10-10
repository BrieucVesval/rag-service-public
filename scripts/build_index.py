"""Chunk the processed documents, embed the chunks and store them in Chroma.

The collection name encodes the index configuration (strategy, chunk size,
overlap, embedding model); its metadata records how and from what it was built.

Usage:
    uv run python scripts/build_index.py
    uv run python scripts/build_index.py --rebuild   # drop and rebuild the collection
"""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime

from rag.chunking.fixed import FixedSizeChunker
from rag.config import get_settings
from rag.indexing.chroma_store import ChromaStore, collection_name
from rag.indexing.embedder import MistralEmbedder
from rag.ingestion.processed import MANIFEST_NAME, load_processed_documents
from rag.provenance import git_commit, git_is_dirty


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rebuild", action="store_true", help="Drop the existing collection first")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Request-level logs from the HTTP client are too verbose for a batch job.
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    settings = get_settings()
    chunker = FixedSizeChunker(settings.chunk_size, settings.chunk_overlap)
    name = collection_name(
        chunker.name, settings.chunk_size, settings.chunk_overlap, settings.embedding_model
    )

    manifest_path = settings.processed_dir / MANIFEST_NAME
    processed_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    dirty = git_is_dirty()
    metadata = {
        "chunk_strategy": chunker.name,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "embedding_model": settings.embedding_model,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        # Chroma metadata cannot hold None: "unknown" when git is unavailable.
        "git_dirty": "unknown" if dirty is None else str(dirty).lower(),
        "processed_at": processed_manifest.get("processed_at", "unknown"),
        "raw_downloaded_at": processed_manifest.get("raw_downloaded_at") or "unknown",
    }
    store = ChromaStore(settings.chroma_dir, name, metadata)
    if store.count() and not args.rebuild:
        print(
            f"Collection {name} already holds {store.count()} chunks; pass --rebuild to rebuild.",
            file=sys.stderr,
        )
        return 1

    documents = load_processed_documents(settings.processed_dir)
    if not documents:
        print(f"No documents in {settings.processed_dir}; run scripts/ingest.py", file=sys.stderr)
        return 1
    chunks = [chunk for document in documents for chunk in chunker.chunk(document)]
    print(f"{len(documents)} documents -> {len(chunks)} chunks, collection {name}")

    embedder = MistralEmbedder.from_settings(settings)
    started = time.perf_counter()
    embeddings = embedder.embed_documents([chunk.text for chunk in chunks])
    elapsed = time.perf_counter() - started

    if args.rebuild:
        store.reset()
    store.add(chunks, embeddings)

    print(f"Stored {store.count()} chunks in {settings.chroma_dir} ({name})")
    print(f"Embedding: {embedder.tokens_used} tokens, {elapsed:.0f} s, dim {len(embeddings[0])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
