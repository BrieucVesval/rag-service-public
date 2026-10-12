"""Chunker protocol: every chunking strategy turns one Document into Chunks."""

from typing import Protocol

from rag.models import Chunk, Document


class Chunker(Protocol):
    # Strategy recorded on every chunk ("fixed", "headers").
    name: str
    # Strategy plus the options that change the chunk texts, used to name the index.
    label: str

    def chunk(self, document: Document) -> list[Chunk]: ...


def make_chunk_id(doc_id: str, strategy: str, position: int) -> str:
    """Deterministic ID: re-chunking the same document gives the same IDs (index sync)."""
    return f"{doc_id}:{strategy}:{position:04d}"
