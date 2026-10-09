import pytest

from rag.models import Chunk, RetrievedChunk


def make_retrieved(position: int, doc_id: str = "F1", score: float = 0.9) -> RetrievedChunk:
    chunk = Chunk(
        chunk_id=f"{doc_id}:fixed:{position:04d}",
        doc_id=doc_id,
        text=f"Texte du chunk {position}.",
        strategy="fixed",
        position=position,
        start_char=0,
        end_char=10,
        doc_title=f"Titre {doc_id}",
        url=f"https://example.org/{doc_id}",
    )
    return RetrievedChunk(chunk=chunk, score=score, rank=position + 1)


@pytest.fixture
def retrieved() -> list[RetrievedChunk]:
    """Three retrieved chunks from two documents, ranked 1 to 3."""
    return [make_retrieved(0, "F1"), make_retrieved(1, "F1"), make_retrieved(2, "F2")]
