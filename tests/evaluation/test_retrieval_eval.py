from collections.abc import Iterator

import pytest

from rag.evaluation.golden_set import GoldenItem
from rag.evaluation.grouping import OVERALL
from rag.evaluation.retrieval_eval import (
    evaluate_question,
    evaluate_retrieval,
    summarize,
    summarize_by_group,
)
from rag.models import RetrievedChunk
from tests.conftest import make_retrieved
from tests.evaluation.test_golden_set import lookup_item, unanswerable_item


class FakeRetriever:
    """Returns a fixed ranking per question and records the requested top_k."""

    name = "fake"

    def __init__(self, rankings: dict[str, list[RetrievedChunk]]) -> None:
        self.rankings = rankings
        self.top_k_requested: list[int] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.top_k_requested.append(top_k)
        return self.rankings[query][:top_k]


def fake_clock(step_s: float = 0.25) -> Iterator[float]:
    now = 0.0
    while True:
        yield now
        now += step_s


def ranking(*doc_ids: str, top_score: float = 0.9) -> list[RetrievedChunk]:
    return [
        make_retrieved(position, doc_id, score=top_score - position / 100)
        for position, doc_id in enumerate(doc_ids)
    ]


@pytest.fixture
def lookup() -> GoldenItem:
    return GoldenItem.model_validate(lookup_item())  # expects F1, evidence "délai de préavis"


@pytest.fixture
def unanswerable() -> GoldenItem:
    return GoldenItem.model_validate(unanswerable_item())


def test_evaluate_question_retrieves_once_at_deepest_k(lookup: GoldenItem) -> None:
    retriever = FakeRetriever({lookup.question: ranking("F2", "F1", "F1")})
    clock = fake_clock()

    result = evaluate_question(retriever, lookup, [1, 3], clock=lambda: next(clock))

    assert retriever.top_k_requested == [3]
    assert result.recall_at == {1: 0.0, 3: 1.0}
    assert result.all_found_at == {1: False, 3: True}
    assert result.first_relevant_rank == 2
    assert result.reciprocal_rank == 0.5
    assert result.evidence_recall_at == {1: 0.0, 3: 0.0}  # chunk texts do not contain the quote
    assert [hit.chunk_id for hit in result.hits] == [
        "F2:fixed:0000",
        "F1:fixed:0001",
        "F1:fixed:0002",
    ]
    assert result.top_score == pytest.approx(0.9)
    assert result.latency_ms == pytest.approx(250.0)


def test_unanswerable_question_has_no_metrics_but_keeps_top_score(
    unanswerable: GoldenItem,
) -> None:
    retriever = FakeRetriever({unanswerable.question: ranking("F7", top_score=0.8)})

    result = evaluate_question(retriever, unanswerable, [1])

    assert result.recall_at is None
    assert result.reciprocal_rank is None
    assert result.top_score == pytest.approx(0.8)


def test_summary_averages_answerable_questions_only(
    lookup: GoldenItem, unanswerable: GoldenItem
) -> None:
    second = lookup.model_copy(update={"id": "q003", "question": "Autre question ?"})
    retriever = FakeRetriever(
        {
            lookup.question: ranking("F1", "F2"),  # found at rank 1
            second.question: ranking("F2", "F3"),  # not found
            unanswerable.question: ranking("F4", top_score=0.7),
        }
    )

    results = evaluate_retrieval(retriever, [lookup, second, unanswerable], [1, 2])
    summary = summarize(results)

    assert summary.n_questions == 3
    assert summary.n_answerable == 2
    assert summary.recall_at == {1: 0.5, 2: 0.5}
    assert summary.mrr == 0.5
    assert summary.mean_top_score == pytest.approx((0.9 + 0.9 + 0.7) / 3)


def test_summarize_by_group_splits_by_category_and_split(
    lookup: GoldenItem, unanswerable: GoldenItem
) -> None:
    retriever = FakeRetriever(
        {lookup.question: ranking("F1"), unanswerable.question: ranking("F4")}
    )

    summaries = summarize_by_group(evaluate_retrieval(retriever, [lookup, unanswerable], [1]))

    assert set(summaries) == {
        OVERALL,
        "category:lookup",
        "category:unanswerable",
        "split:dev",
        "split:test",
    }
    assert summaries["category:unanswerable"].n_answerable == 0
    assert summaries["category:unanswerable"].mrr is None
    assert summaries["category:unanswerable"].recall_at == {}
    assert summaries["split:dev"].recall_at == {1: 1.0}
