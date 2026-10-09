from pathlib import Path

import pytest

from rag.indexing.chroma_store import ChromaStore
from rag.models import Chunk
from rag.retrieval.dense import DenseRetriever


class FakeEmbedder:
    model = "fake"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.vectors[text]


def make_chunk(position: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"F1:fixed:{position:04d}",
        doc_id="F1",
        text=text,
        strategy="fixed",
        position=position,
        start_char=0,
        end_char=len(text),
        doc_title="Titre",
        url="https://example.org/F1",
    )


def test_dense_retriever_returns_nearest_chunks_best_first(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path, "test-collection")
    chunks = [make_chunk(0, "préavis"), make_chunk(1, "loyer"), make_chunk(2, "caution")]
    store.add(chunks, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.7, 0.7, 0.0]])
    embedder = FakeEmbedder({"question": [1.0, 0.1, 0.0]})

    results = DenseRetriever(embedder, store).retrieve("question", top_k=2)

    assert [r.chunk.text for r in results] == ["préavis", "caution"]
    assert [r.rank for r in results] == [1, 2]
    assert results[0].score > results[1].score
    assert results[0].score == pytest.approx(0.995, abs=1e-3)
    assert results[0].chunk == chunks[0]
