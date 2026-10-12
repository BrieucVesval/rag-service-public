"""Fixed-size chunking with overlap: the simplest baseline strategy.

Windows of `chunk_size` characters, each starting `chunk_size - chunk_overlap`
characters after the previous one. Boundaries are moved to the nearest whitespace
so words are never cut. The structure of the text is ignored on purpose: this is
the baseline that structure-aware strategies must beat.
"""

from rag.chunking.base import make_chunk_id
from rag.models import Chunk, Document


class FixedSizeChunker:
    name = "fixed"
    label = "fixed"

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap must be in [0, chunk_size)")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, document: Document) -> list[Chunk]:
        chunks: list[Chunk] = []
        for start, end in self.windows(document.text):
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(document.doc_id, self.name, len(chunks)),
                    doc_id=document.doc_id,
                    text=document.text[start:end],
                    strategy=self.name,
                    position=len(chunks),
                    start_char=start,
                    end_char=end,
                    doc_title=document.title,
                    url=document.url,
                )
            )
        return chunks

    def windows(self, text: str) -> list[tuple[int, int]]:
        """Character spans of the chunks, trimmed of surrounding whitespace."""
        spans: list[tuple[int, int]] = []
        start = 0
        while start < len(text):
            end = self._snap_end(text, start)
            span = trim_span(text, start, end)
            if span[0] < span[1]:
                spans.append(span)
            if end >= len(text):
                break
            start = self._next_start(text, start, end)
        return spans

    def _snap_end(self, text: str, start: int) -> int:
        end = start + self.chunk_size
        if end >= len(text):
            return len(text)
        # Cut at the last whitespace in the second half of the window, if any.
        cut = _last_space(text, start + self.chunk_size // 2, end)
        return cut if cut != -1 else end

    def _next_start(self, text: str, start: int, end: int) -> int:
        target = max(end - self.chunk_overlap, start + 1)
        if target >= end:
            return end
        # Start right after a whitespace so the overlap does not begin mid-word.
        space = _first_space(text, target, end)
        return space + 1 if space != -1 else target


def _last_space(text: str, lo: int, hi: int) -> int:
    for i in range(hi, lo - 1, -1):
        if text[i].isspace():
            return i
    return -1


def _first_space(text: str, lo: int, hi: int) -> int:
    for i in range(lo, hi):
        if text[i].isspace():
            return i
    return -1


def trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span so it neither starts nor ends with whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
