"""Dense retrieval: embed the question, return the nearest chunks in the vector store."""

from collections.abc import Sequence
from typing import Protocol

from rag.indexing.embedder import Embedder
from rag.models import RetrievedChunk


class VectorStore(Protocol):
    def query(self, embedding: Sequence[float], top_k: int) -> list[RetrievedChunk]: ...


class DenseRetriever:
    name = "dense"

    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self.embedder = embedder
        self.store = store

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return self.store.query(self.embedder.embed_query(query), top_k)
