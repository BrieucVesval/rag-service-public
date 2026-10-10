import json

import pytest

from rag.evaluation.generation_eval import QuestionGeneration
from rag.evaluation.golden_set import GoldenItem
from rag.evaluation.grouping import OVERALL
from rag.evaluation.judge import FactVerdict, Judge, SupportVerdict
from rag.evaluation.judge_eval import (
    KeyFactJudgment,
    SentenceJudgment,
    citation_accuracy,
    citation_precision,
    correctness,
    faithfulness,
    judge_question,
    summarize_by_group,
)
from rag.generation.prompts import REFUSAL_MESSAGE
from rag.models import RetrievedChunk
from tests.evaluation.test_generation_eval import make_answer
from tests.evaluation.test_golden_set import lookup_item, unanswerable_item
from tests.evaluation.test_judge import ScriptedLLM, entry, sentence_reply


def sentence(
    verdict: SupportVerdict, cited: tuple[int, ...] = (), supporting: tuple[int, ...] = ()
) -> SentenceJudgment:
    return SentenceJudgment(
        id=1,
        text="t",
        cited=list(cited),
        reason="r",
        verdict=verdict,
        supporting_blocks=list(supporting),
    )


def fact(verdict: FactVerdict) -> KeyFactJudgment:
    return KeyFactJudgment(id=1, fact="f", reason="r", verdict=verdict)


def test_faithfulness_counts_only_fully_supported_claims() -> None:
    sentences = [
        sentence(SupportVerdict.SUPPORTED),
        sentence(SupportVerdict.PARTIAL),
        sentence(SupportVerdict.UNSUPPORTED),
        sentence(SupportVerdict.NO_CLAIM),  # ignored
    ]

    assert faithfulness(sentences) == pytest.approx(1 / 3)
    assert faithfulness([sentence(SupportVerdict.NO_CLAIM)]) is None


def test_citation_accuracy_and_precision() -> None:
    sentences = [
        sentence(
            SupportVerdict.SUPPORTED, cited=(1, 2, 3), supporting=(2,)
        ),  # accurate, 1/3 precise
        sentence(SupportVerdict.UNSUPPORTED, cited=(4,)),  # real block, does not support it
        sentence(SupportVerdict.SUPPORTED, supporting=(1,)),  # uncited: not counted
    ]

    assert citation_accuracy(sentences) == 0.5
    assert citation_precision(sentences) == pytest.approx(1 / 4)
    assert citation_accuracy([sentence(SupportVerdict.SUPPORTED)]) is None


def test_correctness_gives_half_credit_to_partial_facts() -> None:
    facts = [fact(FactVerdict.PRESENT), fact(FactVerdict.PARTIAL), fact(FactVerdict.ABSENT)]

    assert correctness(facts) == pytest.approx(0.5)
    assert correctness([]) is None


def generation(
    item: GoldenItem, text: str, refused: bool, cited: tuple[int, ...] = (1,)
) -> QuestionGeneration:
    return QuestionGeneration(
        question_id=item.id,
        question=item.question,
        category=item.category,
        split=item.split.value,
        expected_refusal=not item.key_facts,
        answer=make_answer(item.question, text, refused=refused, cited=cited),
    )


@pytest.fixture
def lookup() -> GoldenItem:
    return GoldenItem.model_validate(lookup_item())


@pytest.fixture
def unanswerable() -> GoldenItem:
    return GoldenItem.model_validate(unanswerable_item())


def with_context(result: QuestionGeneration, retrieved: list[RetrievedChunk]) -> QuestionGeneration:
    assert result.answer is not None
    answer = result.answer.model_copy(update={"retrieved": retrieved})
    return result.model_copy(update={"answer": answer})


def test_answered_question_gets_both_judgments(
    lookup: GoldenItem, retrieved: list[RetrievedChunk]
) -> None:
    llm = ScriptedLLM(
        sentence_reply(entry(1, blocks=(1,)), entry(2, "unsupported", ())),
        json.dumps({"facts": [{"id": 1, "reason": "r", "verdict": "present"}]}),
    )
    result = with_context(
        generation(lookup, "Trois mois [1]. À Paris, un mois [2].", False), retrieved
    )

    judged = judge_question(Judge(llm), result, lookup)

    assert judged.error is None
    assert [s.cited for s in judged.sentences] == [[1], [2]]
    assert judged.faithfulness == 0.5
    assert judged.citation_accuracy == 0.5
    assert judged.correctness == 1.0
    assert (judged.judge_calls, judged.prompt_tokens, judged.completion_tokens) == (2, 200, 40)


def test_refused_answerable_question_scores_zero_without_judge_call(lookup: GoldenItem) -> None:
    llm = ScriptedLLM()

    judged = judge_question(Judge(llm), generation(lookup, REFUSAL_MESSAGE, True, ()), lookup)

    assert judged.correctness == 0.0
    assert judged.faithfulness is None
    assert judged.judge_calls == 0


def test_refused_unanswerable_question_needs_no_judge(unanswerable: GoldenItem) -> None:
    judged = judge_question(
        Judge(ScriptedLLM()), generation(unanswerable, REFUSAL_MESSAGE, True, ()), unanswerable
    )

    assert (judged.correctness, judged.faithfulness, judged.judge_calls) == (None, None, 0)


def test_judge_failure_is_recorded(lookup: GoldenItem, retrieved: list[RetrievedChunk]) -> None:
    llm = ScriptedLLM("nope", "still nope")
    result = with_context(generation(lookup, "Trois mois [1].", False), retrieved)

    judged = judge_question(Judge(llm), result, lookup)

    assert judged.error is not None and judged.error.startswith("judge failed")
    assert judged.judge_calls == 2  # tokens of failed calls are still counted
    summaries = summarize_by_group([judged])
    assert summaries[OVERALL].n_errors == 1
    assert summaries[OVERALL].faithfulness is None
