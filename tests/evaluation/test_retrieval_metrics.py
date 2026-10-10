import pytest

from rag.evaluation.golden_set import Evidence
from rag.evaluation.retrieval_metrics import (
    all_found_at_k,
    evidence_recall_at_k,
    first_rank_per_doc,
    first_relevant_rank,
    recall_at_k,
    reciprocal_rank,
)
from rag.models import RetrievedChunk
from tests.conftest import make_retrieved


def ranking(*doc_ids: str) -> list[RetrievedChunk]:
    """Chunks ranked 1..n, the i-th from the given fiche."""
    return [make_retrieved(position, doc_id) for position, doc_id in enumerate(doc_ids)]


def with_text(item: RetrievedChunk, text: str) -> RetrievedChunk:
    return item.model_copy(update={"chunk": item.chunk.model_copy(update={"text": text})})


def test_first_rank_per_doc_keeps_best_rank_of_each_fiche() -> None:
    assert first_rank_per_doc(ranking("F1", "F2", "F1", "F3")) == {"F1": 1, "F2": 2, "F3": 4}


def test_recall_at_k_counts_fiches_not_chunks() -> None:
    ranks = first_rank_per_doc(ranking("F1", "F1", "F1", "F2"))

    assert recall_at_k(ranks, ["F1", "F2"], 3) == 0.5
    assert recall_at_k(ranks, ["F1", "F2"], 4) == 1.0
    assert recall_at_k(ranks, ["F9"], 4) == 0.0


def test_all_found_only_when_every_expected_fiche_is_in_top_k() -> None:
    ranks = first_rank_per_doc(ranking("F1", "F3", "F2"))

    assert not all_found_at_k(ranks, ["F1", "F2"], 2)
    assert all_found_at_k(ranks, ["F1", "F2"], 3)


@pytest.mark.parametrize(
    ("doc_ids", "expected_rank", "expected_rr"),
    [
        (("F1", "F2"), 1, 1.0),
        (("F3", "F2", "F1"), 2, 0.5),
        (("F3", "F4"), None, 0.0),
    ],
)
def test_reciprocal_rank_uses_first_relevant_chunk(
    doc_ids: tuple[str, ...], expected_rank: int | None, expected_rr: float
) -> None:
    ranks = first_rank_per_doc(ranking(*doc_ids))

    assert first_relevant_rank(ranks, ["F1", "F2"]) == expected_rank
    assert reciprocal_rank(ranks, ["F1", "F2"]) == expected_rr


def test_evidence_recall_matches_quotes_in_top_k_chunks_of_their_fiche() -> None:
    first, second, third = ranking("F1", "F2", "F1")
    retrieved = [
        with_text(first, "Le préavis est de 3 mois."),
        with_text(second, "Le dépôt de garantie est d'un mois."),
        with_text(third, "En zone tendue, le délai est réduit à 1 mois."),
    ]
    evidence = [
        Evidence(doc_id="F1", quote="le  PRÉAVIS est de 3 mois"),  # whitespace and case ignored
        Evidence(doc_id="F1", quote="le délai est réduit à 1 mois"),
    ]

    assert evidence_recall_at_k(retrieved, evidence, 2) == 0.5
    assert evidence_recall_at_k(retrieved, evidence, 3) == 1.0


def test_evidence_recall_ignores_quote_found_in_another_fiche() -> None:
    retrieved = [with_text(make_retrieved(0, "F2"), "Le préavis est de 3 mois.")]

    assert evidence_recall_at_k(retrieved, [Evidence(doc_id="F1", quote="préavis")], 1) == 0.0
