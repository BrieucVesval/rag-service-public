"""Ask a question to the RAG pipeline and print the cited answer with its sources.

Usage:
    uv run python scripts/ask.py "Quel est le préavis pour quitter un logement loué vide ?"
    uv run python scripts/ask.py --show-context "..."   # also print the retrieved chunks
    uv run python scripts/ask.py --json "..."           # full Answer as JSON
"""

import argparse
import logging
import sys

from rag.chunking.factory import index_collection_name
from rag.config import get_settings
from rag.generation.llm import MistralLLM
from rag.indexing.chroma_store import ChromaStore
from rag.indexing.embedder import MistralEmbedder
from rag.models import Answer
from rag.pipeline import RAGPipeline
from rag.retrieval.dense import DenseRetriever

CONTEXT_PREVIEW_CHARS = 300


def print_answer(answer: Answer, show_context: bool) -> None:
    print(answer.text)
    print()
    if answer.citations:
        print("Sources :")
        for citation in answer.citations:
            print(f"  [{citation.number}] {citation.doc_title} — {citation.url or citation.doc_id}")
    if answer.invalid_citation_numbers:
        print(f"⚠ Citations sans source correspondante : {answer.invalid_citation_numbers}")
    if show_context:
        print("\nContexte récupéré :")
        for item in answer.retrieved:
            preview = item.chunk.text[:CONTEXT_PREVIEW_CHARS].replace("\n", " ")
            print(f"  [{item.rank}] {item.score:.3f} {item.chunk.chunk_id} — {preview}…")
    print(
        f"\n{answer.model} | refus: {answer.refused} | "
        f"tokens: {answer.prompt_tokens} in / {answer.completion_tokens} out | "
        f"latence: {answer.latency_ms}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--show-context", action="store_true", help="Print retrieved chunks")
    parser.add_argument("--json", action="store_true", help="Print the full Answer as JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    settings = get_settings()
    name = index_collection_name(settings)
    store = ChromaStore(settings.chroma_dir, name)
    if store.count() == 0:
        print(f"Collection {name} is empty; run scripts/build_index.py", file=sys.stderr)
        return 1

    retriever = DenseRetriever(MistralEmbedder.from_settings(settings), store)
    pipeline = RAGPipeline(retriever, MistralLLM.from_settings(settings), settings.retrieval_top_k)
    answer = pipeline.answer(args.question)

    if args.json:
        print(answer.model_dump_json(indent=2))
    else:
        print_answer(answer, args.show_context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
