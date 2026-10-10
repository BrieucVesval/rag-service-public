"""Retrieval metrics against the golden set: deterministic, no LLM.

Metrics are measured at the fiche level: a fiche counts as retrieved at k if at
least one of its chunks is among the top-k chunks. This is independent of the
chunking strategy (chunk IDs change with it, fiche IDs do not), so strategies can
be compared on the same golden set. Evidence recall complements it at the passage
level: is the exact sentence that answers the question in what the LLM receives?

All functions take ranked chunks (best first, 1-based ranks) and are pure.
"""

from collections.abc import Sequence

from rag.evaluation.golden_set import Evidence, quote_in_text
from rag.models import RetrievedChunk


def first_rank_per_doc(retrieved: Sequence[RetrievedChunk]) -> dict[str, int]:
    """Best (lowest) chunk rank of each retrieved fiche."""
    ranks: dict[str, int] = {}
    for item in retrieved:
        doc_id = item.chunk.doc_id
        ranks[doc_id] = min(ranks.get(doc_id, item.rank), item.rank)
    return ranks


def recall_at_k(doc_ranks: dict[str, int], expected_docs: Sequence[str], k: int) -> float:
    """Share of the expected fiches with a chunk in the top k."""
    found = sum(1 for doc_id in expected_docs if doc_ranks.get(doc_id, k + 1) <= k)
    return found / len(expected_docs)


def all_found_at_k(doc_ranks: dict[str, int], expected_docs: Sequence[str], k: int) -> bool:
    """True if every expected fiche has a chunk in the top k (what multi-hop questions need)."""
    return recall_at_k(doc_ranks, expected_docs, k) == 1.0


def first_relevant_rank(doc_ranks: dict[str, int], expected_docs: Sequence[str]) -> int | None:
    """Chunk rank of the first chunk from any expected fiche, None if none was retrieved."""
    ranks = [doc_ranks[doc_id] for doc_id in expected_docs if doc_id in doc_ranks]
    return min(ranks) if ranks else None


def reciprocal_rank(doc_ranks: dict[str, int], expected_docs: Sequence[str]) -> float:
    """1 / rank of the first relevant chunk (1.0 if ranked first, 0.0 if never retrieved).

    Averaged over questions, this is the MRR (Mean Reciprocal Rank).
    """
    rank = first_relevant_rank(doc_ranks, expected_docs)
    return 1 / rank if rank is not None else 0.0


def evidence_recall_at_k(
    retrieved: Sequence[RetrievedChunk], evidence: Sequence[Evidence], k: int
) -> float:
    """Share of evidence quotes found verbatim in a top-k chunk of their fiche.

    A quote cut by a chunk boundary is missed even if both halves were retrieved; the
    chunk overlap makes this rare for quotes shorter than the overlap.
    """
    top = [item.chunk for item in retrieved if item.rank <= k]
    found = sum(
        1
        for quote in evidence
        if any(
            chunk.doc_id == quote.doc_id and quote_in_text(quote.quote, chunk.text) for chunk in top
        )
    )
    return found / len(evidence)
