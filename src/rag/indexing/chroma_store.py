"""Persistent vector store: chunks, their embeddings and metadata in ChromaDB.

One collection per index configuration (chunking strategy, chunk size, overlap,
embedding model), so several configurations can coexist and be compared.
Embeddings are always computed by our Embedder, never by Chroma: no default
embedding model is downloaded and the model in use is explicit.
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.collection_configuration import (
    CreateCollectionConfiguration,
    CreateHNSWConfiguration,
)
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from rag.models import Chunk, RetrievedChunk

COLLECTION_CONFIGURATION = CreateCollectionConfiguration(
    hnsw=CreateHNSWConfiguration(space="cosine")
)
WRITE_BATCH_SIZE = 500
_INVALID_NAME_CHARS = re.compile(r"[^a-zA-Z0-9._-]+")


def collection_name(strategy: str, chunk_size: int, chunk_overlap: int, model: str) -> str:
    """Readable, Chroma-safe name identifying an index configuration."""
    raw = f"{strategy}-{chunk_size}-{chunk_overlap}-{model}"
    return _INVALID_NAME_CHARS.sub("-", raw).strip("-._")


class ChromaStore:
    def __init__(self, path: Path, name: str, metadata: Mapping[str, Any] | None = None) -> None:
        self._client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.name = name
        self._metadata = dict(metadata or {})
        self._collection = self._get_or_create()

    def _get_or_create(self) -> Collection:
        return self._client.get_or_create_collection(
            name=self.name,
            embedding_function=None,
            configuration=COLLECTION_CONFIGURATION,
            metadata=self._metadata or None,
        )

    def count(self) -> int:
        return self._collection.count()

    @property
    def metadata(self) -> dict[str, Any]:
        """How and from what the collection was built (set by scripts/build_index.py)."""
        return dict(self._collection.metadata or {})

    def reset(self) -> None:
        """Drop every chunk of this collection (used before a full rebuild)."""
        if self.name in {collection.name for collection in self._client.list_collections()}:
            self._client.delete_collection(self.name)
        self._collection = self._get_or_create()

    def add(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings")
        for start in range(0, len(chunks), WRITE_BATCH_SIZE):
            batch = chunks[start : start + WRITE_BATCH_SIZE]
            self._collection.upsert(
                ids=[chunk.chunk_id for chunk in batch],
                embeddings=list(embeddings[start : start + len(batch)]),
                documents=[chunk.text for chunk in batch],
                metadatas=[chunk_metadata(chunk) for chunk in batch],
            )

    def query(self, embedding: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        """Nearest chunks by cosine similarity (1 - cosine distance), best first."""
        query_embeddings: list[Sequence[float]] = [embedding]
        result = self._collection.query(
            query_embeddings=query_embeddings,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        distances = (result["distances"] or [[]])[0]
        return [
            RetrievedChunk(
                chunk=Chunk.model_validate({**metadata, "chunk_id": chunk_id, "text": text}),
                score=1.0 - distance,
                rank=rank,
            )
            for rank, (chunk_id, text, metadata, distance) in enumerate(
                zip(ids, documents, metadatas, distances, strict=True), start=1
            )
        ]


def chunk_metadata(chunk: Chunk) -> dict[str, str | int]:
    """Chunk fields except id and text, as Chroma metadata (no None values allowed)."""
    fields = chunk.model_dump(exclude={"chunk_id", "text"}, exclude_none=True)
    return {key: value for key, value in fields.items() if isinstance(value, str | int)}
