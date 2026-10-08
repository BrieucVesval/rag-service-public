import pytest

from rag.chunking.fixed import FixedSizeChunker
from rag.models import Document

WORDS = " ".join(f"mot{i}" for i in range(400))  # ~2,700 characters


def make_document(text: str) -> Document:
    return Document(
        doc_id="F1",
        source="test",
        title="Titre",
        text=text,
        url="https://example.org/F1",
    )


def test_short_document_gives_one_chunk_with_metadata() -> None:
    chunks = FixedSizeChunker(chunk_size=100, chunk_overlap=10).chunk(make_document("  Court.  "))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == "Court."
    assert chunk.chunk_id == "F1:fixed:0000"
    assert (chunk.doc_id, chunk.strategy, chunk.position) == ("F1", "fixed", 0)
    assert (chunk.doc_title, chunk.url) == ("Titre", "https://example.org/F1")


def test_empty_document_gives_no_chunk() -> None:
    assert FixedSizeChunker(chunk_size=100, chunk_overlap=10).chunk(make_document("   ")) == []


def test_chunks_respect_size_and_never_cut_words() -> None:
    document = make_document(WORDS)

    chunks = FixedSizeChunker(chunk_size=300, chunk_overlap=50).chunk(document)

    assert len(chunks) > 1
    words = set(WORDS.split())
    for chunk in chunks:
        assert len(chunk.text) <= 300
        assert set(chunk.text.split()) <= words


def test_offsets_match_text_and_chunks_cover_whole_document() -> None:
    document = make_document(WORDS)

    chunks = FixedSizeChunker(chunk_size=300, chunk_overlap=50).chunk(document)

    for chunk in chunks:
        assert document.text[chunk.start_char : chunk.end_char] == chunk.text
    assert chunks[0].start_char == 0
    assert chunks[-1].end_char == len(WORDS)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_char <= previous.end_char  # no gap


def test_consecutive_chunks_overlap() -> None:
    chunks = FixedSizeChunker(chunk_size=300, chunk_overlap=50).chunk(make_document(WORDS))

    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_char < previous.end_char
        assert previous.text.split()[-1] in current.text.split()


def test_zero_overlap_gives_disjoint_chunks() -> None:
    chunks = FixedSizeChunker(chunk_size=300, chunk_overlap=0).chunk(make_document(WORDS))

    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_char >= previous.end_char
    assert " ".join(chunk.text for chunk in chunks).split() == WORDS.split()


def test_text_without_spaces_is_cut_at_chunk_size() -> None:
    chunks = FixedSizeChunker(chunk_size=10, chunk_overlap=2).chunk(make_document("x" * 25))

    assert [len(chunk.text) for chunk in chunks] == [10, 10, 9]


def test_chunk_ids_are_deterministic_and_sequential() -> None:
    chunker = FixedSizeChunker(chunk_size=300, chunk_overlap=50)

    first = chunker.chunk(make_document(WORDS))
    second = chunker.chunk(make_document(WORDS))

    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.position for c in first] == list(range(len(first)))


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, -1)])
def test_invalid_parameters_raise(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        FixedSizeChunker(chunk_size=size, chunk_overlap=overlap)
