import pytest

from rag.evaluation.generation_eval import (
    evaluate_generation,
    evaluate_question,
    summarize,
    summarize_by_group,
)
from rag.evaluation.golden_set import GoldenItem
from rag.evaluation.grouping import OVERALL
from rag.generation.prompts import REFUSAL_MESSAGE
from rag.models import Answer, Citation
from tests.evaluation.test_golden_set import lookup_item, unanswerable_item


def make_answer(
    question: str,
    text: str = "Trois mois [1].",
    *,
    refused: bool = False,
    cited: tuple[int, ...] = (1,),
    invalid: tuple[int, ...] = (),
    tokens: tuple[int, int] = (1000, 50),
    latency_ms: float = 2000.0,
) -> Answer:
    citations = [
        Citation(number=n, chunk_id=f"F1:fixed:{n:04d}", doc_id="F1", doc_title="Titre")
        for n in cited
    ]
    return Answer(
        question=question,
        text=text,
        refused=refused,
        citations=citations,
        invalid_citation_numbers=list(invalid),
        retrieved=[],
        model="fake-llm",
        prompt_tokens=tokens[0],
        completion_tokens=tokens[1],
        latency_ms={"retrieval": 100.0, "total": latency_ms},
    )


class FakeAnswerer:
    """Returns a prepared Answer per question; raises for questions mapped to an exception."""

    def __init__(self, answers: dict[str, Answer | Exception]) -> None:
        self.answers = answers

    def answer(self, question: str) -> Answer:
        outcome = self.answers[question]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def lookup() -> GoldenItem:
    return GoldenItem.model_validate(lookup_item())


@pytest.fixture
def unanswerable() -> GoldenItem:
    return GoldenItem.model_validate(unanswerable_item())


def test_evaluate_question_keeps_full_answer_and_expectation(
    lookup: GoldenItem, unanswerable: GoldenItem
) -> None:
    answerer = FakeAnswerer(
        {
            lookup.question: make_answer(lookup.question),
            unanswerable.question: make_answer(
                unanswerable.question, REFUSAL_MESSAGE, refused=True, cited=()
            ),
        }
    )

    answered = evaluate_question(answerer, lookup)
    refused = evaluate_question(answerer, unanswerable)

    assert answered.expected_refusal is False
    assert answered.answer is not None and answered.answer.text == "Trois mois [1]."
    assert refused.expected_refusal is True
    assert refused.split == "test"


def test_failed_call_is_recorded_not_raised(lookup: GoldenItem, unanswerable: GoldenItem) -> None:
    answerer = FakeAnswerer(
        {
            lookup.question: RuntimeError("Server disconnected"),
            unanswerable.question: make_answer(unanswerable.question, refused=True, cited=()),
        }
    )

    results = evaluate_generation(answerer, [lookup, unanswerable])

    assert results[0].answer is None
    assert results[0].error == "RuntimeError: Server disconnected"
    assert results[1].answer is not None
    summary = summarize(results)
    assert summary.n_errors == 1
    assert summary.refusal_accuracy == 1.0  # computed on the answered question only


def test_summary_refusal_and_citation_metrics(lookup: GoldenItem, unanswerable: GoldenItem) -> None:
    second = lookup.model_copy(update={"id": "q003", "question": "Autre question ?"})
    third = lookup.model_copy(update={"id": "q004", "question": "Encore une ?"})
    other_unanswerable = unanswerable.model_copy(update={"id": "q005", "question": "Hors sujet ?"})
    answerer = FakeAnswerer(
        {
            lookup.question: make_answer(lookup.question, cited=(1, 2)),  # good answer
            second.question: make_answer(second.question, cited=(), invalid=(7,)),  # bad citation
            third.question: make_answer(third.question, refused=True, cited=()),  # false refusal
            unanswerable.question: make_answer(unanswerable.question, refused=True, cited=()),
            other_unanswerable.question: make_answer(other_unanswerable.question),  # answered
        }
    )

    summary = summarize(
        evaluate_generation(answerer, [lookup, second, third, unanswerable, other_unanswerable])
    )

    assert summary.n_questions == 5
    assert summary.refusal_accuracy == pytest.approx(3 / 5)
    assert summary.correct_refusal_rate == 0.5
    assert summary.false_refusal_rate == pytest.approx(1 / 3)
    # Citation metrics over the 3 non-refused answers: cited (1, 2), (), (1).
    assert summary.uncited_answer_rate == pytest.approx(1 / 3)
    assert summary.invalid_citation_rate == pytest.approx(1 / 3)
    assert summary.mean_citations == pytest.approx(1.0)
    assert summary.prompt_tokens == 5000
    assert summary.completion_tokens == 250
    assert summary.mean_latency_ms == pytest.approx(2000.0)


def test_rates_are_none_without_denominator(lookup: GoldenItem) -> None:
    answerer = FakeAnswerer({lookup.question: make_answer(lookup.question, refused=True, cited=())})

    summary = summarize(evaluate_generation(answerer, [lookup]))

    assert summary.correct_refusal_rate is None  # no unanswerable question
    assert summary.uncited_answer_rate is None  # no non-refused answer
    assert summary.mean_citations is None


def test_summarize_by_group(lookup: GoldenItem, unanswerable: GoldenItem) -> None:
    answerer = FakeAnswerer(
        {
            lookup.question: make_answer(lookup.question),
            unanswerable.question: make_answer(unanswerable.question, refused=True, cited=()),
        }
    )

    summaries = summarize_by_group(evaluate_generation(answerer, [lookup, unanswerable]))

    assert summaries[OVERALL].refusal_accuracy == 1.0
    assert summaries["category:unanswerable"].correct_refusal_rate == 1.0
    assert summaries["category:lookup"].false_refusal_rate == 0.0
    assert set(summaries) == {
        OVERALL,
        "category:lookup",
        "category:unanswerable",
        "split:dev",
        "split:test",
    }
