"""Retriever protocol: a question in, the most relevant chunks out (best first)."""

from typing import Protocol

from rag.models import RetrievedChunk


class Retriever(Protocol):
    name: str

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...
