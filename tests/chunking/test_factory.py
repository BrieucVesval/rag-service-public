import pytest
from pydantic import ValidationError

from rag.chunking.factory import index_collection_name, make_chunker
from rag.chunking.fixed import FixedSizeChunker
from rag.chunking.headers import HeaderChunker
from rag.config import Settings


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_fixed_is_the_default_and_keeps_the_baseline_collection_name() -> None:
    settings = make_settings()

    assert isinstance(make_chunker(settings), FixedSizeChunker)
    assert index_collection_name(settings) == "fixed-2000-200-mistral-embed"


def test_headers_strategy_and_prefix_are_part_of_the_collection_name() -> None:
    settings = make_settings(chunk_strategy="headers", header_prefix="none")

    chunker = make_chunker(settings)

    assert isinstance(chunker, HeaderChunker)
    assert (chunker.max_size, chunker.overlap, chunker.prefix) == (2000, 200, "none")
    assert index_collection_name(settings) == "headers-none-2000-200-mistral-embed"


def test_unknown_strategy_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(chunk_strategy="semantic")
