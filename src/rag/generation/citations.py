"""Extract `[n]` citation markers from an answer and resolve them to context blocks.

This checks citations structurally (does block n exist?). Whether block n actually
supports the sentence is checked later by an LLM-as-judge.
"""

import re
from collections.abc import Sequence

from rag.models import Citation, RetrievedChunk

# Matches [1], [12] and grouped forms like [1, 2] or [1,2,3].
_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def cited_numbers(text: str) -> list[int]:
    """Distinct cited numbers, in order of first appearance."""
    numbers: list[int] = []
    for match in _MARKER.finditer(text):
        for part in match.group(1).split(","):
            number = int(part)
            if number not in numbers:
                numbers.append(number)
    return numbers


def resolve_citations(
    text: str, retrieved: Sequence[RetrievedChunk]
) -> tuple[list[Citation], list[int]]:
    """Return (valid citations, numbers that point to no context block)."""
    citations: list[Citation] = []
    invalid: list[int] = []
    for number in cited_numbers(text):
        if not 1 <= number <= len(retrieved):
            invalid.append(number)
            continue
        chunk = retrieved[number - 1].chunk
        citations.append(
            Citation(
                number=number,
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                url=chunk.url,
            )
        )
    return citations, invalid
