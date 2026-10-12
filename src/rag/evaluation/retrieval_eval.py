"""Run a retriever over golden set questions and aggregate retrieval metrics.

Each question is retrieved once at the deepest cut-off; metrics at smaller k are
computed from the same ranking. Unanswerable questions have no expected fiche, so
they get no recall or MRR, but their top similarity is kept: comparing it with
answerable questions tells whether retrieval scores can flag out-of-corpus questions.
"""

import time
from collections.abc import Callable, Sequence
from statistics import mean

from pydantic import BaseModel

from rag.evaluation.golden_set import Category, GoldenItem
from rag.evaluation.grouping import group_results
from rag.evaluation.retrieval_metrics import (
    all_found_at_k,
    evidence_recall_at_k,
    first_rank_per_doc,
    first_relevant_rank,
    recall_at_k,
    reciprocal_rank,
)
from rag.retrieval.base import Retriever

MS_PER_SECOND = 1000


class RetrievedHit(BaseModel):
    """A retrieved chunk as stored in a run file: identifiers and score, no text."""

    rank: int
    chunk_id: str
    doc_id: str
    score: float


class QuestionRetrieval(BaseModel):
    """Retrieval outcome for one golden set question. Metrics are None if unanswerable."""

    question_id: str
    question: str
    category: Category
    split: str
    expected_docs: list[str]
    hits: list[RetrievedHit]
    recall_at: dict[int, float] | None
    all_found_at: dict[int, bool] | None
    evidence_recall_at: dict[int, float] | None
    first_relevant_rank: int | None
    reciprocal_rank: float | None
    top_score: float | None
    latency_ms: float


class RetrievalSummary(BaseModel):
    """Metrics averaged over a group of questions (answerable ones for recall and MRR)."""

    n_questions: int
    n_answerable: int
    recall_at: dict[int, float]
    all_found_at: dict[int, float]
    evidence_recall_at: dict[int, float]
    mrr: float | None
    mean_top_score: float | None
    mean_latency_ms: float


def evaluate_question(
    retriever: Retriever,
    item: GoldenItem,
    k_values: Sequence[int],
    clock: Callable[[], float] = time.perf_counter,
) -> QuestionRetrieval:
    started = clock()
    retrieved = retriever.retrieve(item.question, max(k_values))
    latency_ms = (clock() - started) * MS_PER_SECOND

    hits = [
        RetrievedHit(rank=r.rank, chunk_id=r.chunk.chunk_id, doc_id=r.chunk.doc_id, score=r.score)
        for r in retrieved
    ]
    top_score = max((r.score for r in retrieved), default=None)
    common = {
        "question_id": item.id,
        "question": item.question,
        "category": item.category,
        "split": item.split.value,
        "expected_docs": item.expected_docs,
        "hits": hits,
        "top_score": top_score,
        "latency_ms": latency_ms,
    }
    if not item.expected_docs:
        return QuestionRetrieval(
            **common,
            recall_at=None,
            all_found_at=None,
            evidence_recall_at=None,
            first_relevant_rank=None,
            reciprocal_rank=None,
        )

    doc_ranks = first_rank_per_doc(retrieved)
    return QuestionRetrieval(
        **common,
        recall_at={k: recall_at_k(doc_ranks, item.expected_docs, k) for k in k_values},
        all_found_at={k: all_found_at_k(doc_ranks, item.expected_docs, k) for k in k_values},
        evidence_recall_at={k: evidence_recall_at_k(retrieved, item.evidence, k) for k in k_values},
        first_relevant_rank=first_relevant_rank(doc_ranks, item.expected_docs),
        reciprocal_rank=reciprocal_rank(doc_ranks, item.expected_docs),
    )


def evaluate_retrieval(
    retriever: Retriever,
    items: Sequence[GoldenItem],
    k_values: Sequence[int],
    clock: Callable[[], float] = time.perf_counter,
) -> list[QuestionRetrieval]:
    return [evaluate_question(retriever, item, k_values, clock) for item in items]


def summarize(results: Sequence[QuestionRetrieval]) -> RetrievalSummary:
    answerable = [r for r in results if r.recall_at is not None]
    k_values = sorted(answerable[0].recall_at) if answerable and answerable[0].recall_at else []
    top_scores = [r.top_score for r in results if r.top_score is not None]
    return RetrievalSummary(
        n_questions=len(results),
        n_answerable=len(answerable),
        recall_at={k: mean(r.recall_at[k] for r in answerable if r.recall_at) for k in k_values},
        all_found_at={
            k: mean(float(r.all_found_at[k]) for r in answerable if r.all_found_at)
            for k in k_values
        },
        evidence_recall_at={
            k: mean(r.evidence_recall_at[k] for r in answerable if r.evidence_recall_at)
            for k in k_values
        },
        mrr=mean(r.reciprocal_rank or 0.0 for r in answerable) if answerable else None,
        mean_top_score=mean(top_scores) if top_scores else None,
        mean_latency_ms=mean(r.latency_ms for r in results) if results else 0.0,
    )


def summarize_by_group(results: Sequence[QuestionRetrieval]) -> dict[str, RetrievalSummary]:
    """Summaries overall, per category and per split, keyed "all", "category:…", "split:…"."""
    return {name: summarize(group) for name, group in group_results(results).items()}
