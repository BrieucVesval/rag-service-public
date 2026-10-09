from pathlib import Path

import pytest

from rag.indexing.chroma_store import ChromaStore, chunk_metadata, collection_name
from rag.models import Chunk


def make_chunk(position: int, url: str | None = "https://example.org/F1") -> Chunk:
    return Chunk(
        chunk_id=f"F1:fixed:{position:04d}",
        doc_id="F1",
        text=f"texte {position}",
        strategy="fixed",
        position=position,
        start_char=position * 10,
        end_char=position * 10 + 8,
        doc_title="Titre",
        url=url,
    )


def test_collection_name_is_chroma_safe() -> None:
    assert collection_name("fixed", 2000, 200, "mistral-embed") == "fixed-2000-200-mistral-embed"
    assert collection_name("fixed", 2000, 200, "org/model:v1") == "fixed-2000-200-org-model-v1"


def test_chunk_metadata_drops_id_text_and_none() -> None:
    metadata = chunk_metadata(make_chunk(3, url=None))

    assert metadata == {
        "doc_id": "F1",
        "strategy": "fixed",
        "position": 3,
        "start_char": 30,
        "end_char": 38,
        "doc_title": "Titre",
    }


def test_add_count_and_persistence(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path, "test-collection", {"embedding_model": "fake"})
    chunks = [make_chunk(i) for i in range(3)]

    store.add(chunks, [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

    assert store.count() == 3
    assert ChromaStore(tmp_path, "test-collection").count() == 3


def test_add_is_idempotent_for_same_ids(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path, "test-collection")
    chunks = [make_chunk(0)]

    store.add(chunks, [[1.0, 0.0]])
    store.add(chunks, [[0.0, 1.0]])

    assert store.count() == 1


def test_reset_empties_collection(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path, "test-collection")
    store.add([make_chunk(0)], [[1.0, 0.0]])

    store.reset()

    assert store.count() == 0


def test_mismatched_lengths_raise(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path, "test-collection")

    with pytest.raises(ValueError, match="1 chunks but 0 embeddings"):
        store.add([make_chunk(0)], [])
