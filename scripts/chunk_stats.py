"""Chunk statistics and evidence-quote check for the configured chunking (no API call).

Chunks the processed documents with the chunker selected in the settings and reports
chunk counts and sizes, plus whether every golden set evidence quote fits inside at
least one chunk of its fiche. A quote cut by every chunk boundary could never be
found, so evidence recall would be biased (step 8a check).

Usage:
    uv run python scripts/chunk_stats.py
    RAG_CHUNK_STRATEGY=headers uv run python scripts/chunk_stats.py
    RAG_CHUNK_STRATEGY=headers RAG_HEADER_PREFIX=none uv run python scripts/chunk_stats.py
"""

import sys
from collections import defaultdict

from rag.chunking.factory import index_collection_name, make_chunker
from rag.config import get_settings
from rag.evaluation.golden_set import load_golden_set, quote_in_text
from rag.ingestion.processed import load_processed_documents
from rag.models import Chunk

# Characters per mistral-embed token, measured on the fixed-size index (step 5b).
CHARS_PER_TOKEN = 3.06
# Chunks shorter than this are reported as "small" (a heading and a line or two).
SMALL_CHUNK_CHARS = 200


def quantiles(values: list[int]) -> str:
    ordered = sorted(values)
    n = len(ordered)
    picks = {"min": 0, "p10": n // 10, "p25": n // 4, "median": n // 2, "p75": 3 * n // 4}
    picks |= {"p90": int(n * 0.9), "max": n - 1}
    return ", ".join(f"{name} {ordered[index]:,}" for name, index in picks.items())


def main() -> int:
    settings = get_settings()
    chunker = make_chunker(settings)
    documents = load_processed_documents(settings.processed_dir)
    if not documents:
        print(f"No documents in {settings.processed_dir}; run scripts/ingest.py", file=sys.stderr)
        return 1
    by_doc: dict[str, list[Chunk]] = {d.doc_id: chunker.chunk(d) for d in documents}
    chunks = [chunk for doc_chunks in by_doc.values() for chunk in doc_chunks]
    texts = [len(chunk.text) for chunk in chunks]
    passages = [chunk.end_char - chunk.start_char for chunk in chunks]
    total_chars = sum(texts)

    print(f"Collection {index_collection_name(settings)}: {len(documents)} documents")
    print(f"Chunks: {len(chunks):,}")
    print(f"Chunk text (embedded), chars: {quantiles(texts)}")
    print(f"Passage in the document, chars: {quantiles(passages)}")
    print(f"Chunks per document: {quantiles([len(c) for c in by_doc.values()])}")
    small = sum(size < SMALL_CHUNK_CHARS for size in texts)
    print(f"Chunks under {SMALL_CHUNK_CHARS} chars: {small} ({small / len(chunks):.1%})")
    over = sum(size > settings.chunk_size for size in passages)
    print(f"Passages over chunk_size ({settings.chunk_size}): {over}")
    paths = [len(chunk.heading_path) for chunk in chunks if chunk.heading_path]
    if paths:
        print(f"Heading path, chars ({len(paths)} chunks): {quantiles(paths)}")
    print(
        f"Text to embed: {total_chars:,} chars, ~{total_chars / CHARS_PER_TOKEN / 1e6:.2f}M tokens"
    )

    golden = load_golden_set(settings.golden_set_path)
    missing: dict[str, list[str]] = defaultdict(list)
    quotes = 0
    for item in golden.questions:
        for evidence in item.evidence:
            quotes += 1
            doc_chunks = by_doc.get(evidence.doc_id, [])
            if not any(quote_in_text(evidence.quote, chunk.text) for chunk in doc_chunks):
                missing[item.id].append(f"{evidence.doc_id}: {evidence.quote[:80]}")
    found = quotes - sum(len(quotes_) for quotes_ in missing.values())
    print(f"Evidence quotes inside one chunk: {found}/{quotes}")
    for item_id, problems in missing.items():
        for problem in problems:
            print(f"  NOT FOUND {item_id} {problem}")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
