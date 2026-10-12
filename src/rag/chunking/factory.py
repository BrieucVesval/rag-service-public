"""Build the chunker selected in the settings and name the index it produces."""

from rag.chunking.base import Chunker
from rag.chunking.fixed import FixedSizeChunker
from rag.chunking.headers import HeaderChunker
from rag.config import Settings
from rag.indexing.chroma_store import collection_name


def make_chunker(settings: Settings) -> Chunker:
    if settings.chunk_strategy == "headers":
        return HeaderChunker(settings.chunk_size, settings.chunk_overlap, settings.header_prefix)
    return FixedSizeChunker(settings.chunk_size, settings.chunk_overlap)


def index_collection_name(settings: Settings) -> str:
    """Chroma collection of the configured chunking and embedding model."""
    return collection_name(
        make_chunker(settings).label,
        settings.chunk_size,
        settings.chunk_overlap,
        settings.embedding_model,
    )
