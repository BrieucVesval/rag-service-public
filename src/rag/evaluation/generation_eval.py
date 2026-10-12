"""Run the RAG pipeline over golden set questions and compute LLM-free generation metrics.

The run stores every full Answer, including the retrieved chunk texts given to the
LLM, so the LLM judge (correctness, faithfulness, citation accuracy) can score the
saved answers later without regenerating them: several judges or judge prompts are
then compared on exactly the same answers, and generation is paid only once.

Metrics computed here need no LLM:
- refusals: unanswerable questions should be refused, answerable ones should not;
- citation structure: answers without any citation, citations pointing to no block.
"""

import logging
from collections.abc import Sequence
from statistics import mean
from typing import Protocol

from pydantic import BaseModel

from rag.evaluation.golden_set import Category, GoldenItem
from rag.evaluation.grouping import group_results
from rag.models import Answer

logger = logging.getLogger(__name__)

TOTAL_LATENCY_KEY = "total"


class QuestionAnswerer(Protocol):
    def answer(self, question: str) -> Answer: ...


class QuestionGeneration(BaseModel):
    """One golden set question, the pipeline's full Answer, or the error that prevented it."""

    question_id: str
    question: str
    category: Category
    split: str
    expected_refusal: bool
    answer: Answer | None
    error: str | None = None


class GenerationSummary(BaseModel):
    """LLM-free generation metrics over a group of questions (errors excluded).

    Rates are None when their denominator is empty (e.g. no unanswerable question).
    """

    n_questions: int
    n_errors: int
    refusal_accuracy: float | None
    correct_refusal_rate: float | None
    false_refusal_rate: float | None
    uncited_answer_rate: float | None
    invalid_citation_rate: float | None
    mean_citations: float | None
    prompt_tokens: int
    completion_tokens: int
    mean_latency_ms: float | None


def evaluate_question(answerer: QuestionAnswerer, item: GoldenItem) -> QuestionGeneration:
    """Answer one question. A failed call is recorded, not raised, so a run is never lost."""
    fields = {
        "question_id": item.id,
        "question": item.question,
        "category": item.category,
        "split": item.split.value,
        "expected_refusal": item.category == Category.UNANSWERABLE,
    }
    try:
        answer = answerer.answer(item.question)
    except Exception as error:  # network, rate limit after retries, malformed response
        logger.exception("Generation failed for %s", item.id)
        return QuestionGeneration(**fields, answer=None, error=f"{type(error).__name__}: {error}")
    return QuestionGeneration(**fields, answer=answer)


def evaluate_generation(
    answerer: QuestionAnswerer, items: Sequence[GoldenItem]
) -> list[QuestionGeneration]:
    results = []
    for index, item in enumerate(items, start=1):
        results.append(evaluate_question(answerer, item))
        logger.info("Generated %d/%d (%s)", index, len(items), item.id)
    return results


def summarize(results: Sequence[QuestionGeneration]) -> GenerationSummary:
    answered = [r for r in results if r.answer is not None]
    should_refuse = [r for r in answered if r.expected_refusal]
    should_answer = [r for r in answered if not r.expected_refusal]
    # Citation metrics only make sense for answers that are not refusals.
    substantive = [r.answer for r in answered if r.answer is not None and not r.answer.refused]
    return GenerationSummary(
        n_questions=len(results),
        n_errors=len(results) - len(answered),
        refusal_accuracy=_rate([_refused(r) == r.expected_refusal for r in answered]),
        correct_refusal_rate=_rate([_refused(r) for r in should_refuse]),
        false_refusal_rate=_rate([_refused(r) for r in should_answer]),
        uncited_answer_rate=_rate([not answer.citations for answer in substantive]),
        invalid_citation_rate=_rate([bool(a.invalid_citation_numbers) for a in substantive]),
        mean_citations=mean(len(a.citations) for a in substantive) if substantive else None,
        prompt_tokens=sum(r.answer.prompt_tokens for r in answered if r.answer),
        completion_tokens=sum(r.answer.completion_tokens for r in answered if r.answer),
        mean_latency_ms=_mean_latency(answered),
    )


def summarize_by_group(results: Sequence[QuestionGeneration]) -> dict[str, GenerationSummary]:
    """Summaries overall, per category and per split, keyed "all", "category:…", "split:…"."""
    return {name: summarize(group) for name, group in group_results(results).items()}


def _refused(result: QuestionGeneration) -> bool:
    return result.answer is not None and result.answer.refused


def _rate(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _mean_latency(results: Sequence[QuestionGeneration]) -> float | None:
    latencies = [
        r.answer.latency_ms[TOTAL_LATENCY_KEY]
        for r in results
        if r.answer is not None and TOTAL_LATENCY_KEY in r.answer.latency_ms
    ]
    return mean(latencies) if latencies else None
