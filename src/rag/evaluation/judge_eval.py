"""Score a saved generation run with the LLM judge.

Per answer (metrics are None when they do not apply):
- faithfulness: share of claim sentences supported by the context given to the LLM
  ("partial" is not supported). Measures what the generator added on its own.
- citation accuracy: share of cited claim sentences where at least one cited block
  is among the blocks that support it. Catches real citations attached to claims
  their source does not make.
- citation precision: share of (claim sentence, cited block) pairs where the block
  supports the sentence. Low when the generator cites every block "just in case".
- correctness: share of the golden set key facts stated by the answer ("partial"
  counts half). An answerable question that was refused scores 0, without a judge call.

Unanswerable questions that were refused need no judge (refusals are measured in the
generation run); answered unanswerable questions still get a faithfulness score.
"""

import logging
from collections import Counter
from collections.abc import Sequence
from statistics import mean

from pydantic import BaseModel

from rag.evaluation.generation_eval import QuestionGeneration
from rag.evaluation.golden_set import Category, GoldenItem
from rag.evaluation.grouping import group_results
from rag.evaluation.judge import FactVerdict, Judge, JudgeError, SupportVerdict
from rag.evaluation.sentences import split_sentences
from rag.generation.llm import LLMResponse

logger = logging.getLogger(__name__)

PARTIAL_FACT_CREDIT = 0.5
REFUSAL_REASON = "The answer is a refusal."


class SentenceJudgment(BaseModel):
    id: int
    text: str
    cited: list[int]
    reason: str
    verdict: SupportVerdict
    supporting_blocks: list[int]


class KeyFactJudgment(BaseModel):
    id: int
    fact: str
    reason: str
    verdict: FactVerdict


class QuestionJudgment(BaseModel):
    question_id: str
    question: str
    category: Category
    split: str
    refused: bool
    sentences: list[SentenceJudgment] = []
    key_facts: list[KeyFactJudgment] = []
    faithfulness: float | None = None
    citation_accuracy: float | None = None
    citation_precision: float | None = None
    correctness: float | None = None
    judge_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


class JudgeSummary(BaseModel):
    """Per-question metrics averaged over a group (macro average), plus verdict counts."""

    n_questions: int
    n_errors: int
    faithfulness: float | None
    citation_accuracy: float | None
    citation_precision: float | None
    correctness: float | None
    sentence_verdicts: dict[str, int]
    fact_verdicts: dict[str, int]
    judge_calls: int
    prompt_tokens: int
    completion_tokens: int


def _claims(sentences: Sequence[SentenceJudgment]) -> list[SentenceJudgment]:
    return [s for s in sentences if s.verdict != SupportVerdict.NO_CLAIM]


def faithfulness(sentences: Sequence[SentenceJudgment]) -> float | None:
    claims = _claims(sentences)
    if not claims:
        return None
    return sum(s.verdict == SupportVerdict.SUPPORTED for s in claims) / len(claims)


def citation_accuracy(sentences: Sequence[SentenceJudgment]) -> float | None:
    cited = [s for s in _claims(sentences) if s.cited]
    if not cited:
        return None
    return sum(bool(set(s.cited) & set(s.supporting_blocks)) for s in cited) / len(cited)


def citation_precision(sentences: Sequence[SentenceJudgment]) -> float | None:
    pairs = [(s, block) for s in _claims(sentences) for block in s.cited]
    if not pairs:
        return None
    return sum(block in s.supporting_blocks for s, block in pairs) / len(pairs)


def correctness(facts: Sequence[KeyFactJudgment]) -> float | None:
    if not facts:
        return None
    credit = {FactVerdict.PRESENT: 1.0, FactVerdict.PARTIAL: PARTIAL_FACT_CREDIT}
    return sum(credit.get(f.verdict, 0.0) for f in facts) / len(facts)


def judge_question(
    judge: Judge, generation: QuestionGeneration, item: GoldenItem
) -> QuestionJudgment:
    base = QuestionJudgment(
        question_id=generation.question_id,
        question=generation.question,
        category=generation.category,
        split=generation.split,
        refused=generation.answer is not None and generation.answer.refused,
    )
    answer = generation.answer
    if answer is None:
        return base.model_copy(update={"error": f"generation failed: {generation.error}"})

    responses: list[LLMResponse] = []
    update: dict[str, object] = {}
    try:
        if not answer.refused:
            sentences = split_sentences(answer.text)
            verdicts, calls = judge.judge_sentences(answer.question, answer.retrieved, sentences)
            responses += calls
            judged = [
                SentenceJudgment(
                    id=s.id,
                    text=s.text,
                    cited=s.cited,
                    reason=v.reason,
                    verdict=v.verdict,
                    supporting_blocks=v.supporting_blocks,
                )
                for s, v in zip(sentences, verdicts, strict=True)
            ]
            update |= {
                "sentences": judged,
                "faithfulness": faithfulness(judged),
                "citation_accuracy": citation_accuracy(judged),
                "citation_precision": citation_precision(judged),
            }
        if item.key_facts:
            if answer.refused:
                facts = [
                    KeyFactJudgment(id=i, fact=f, reason=REFUSAL_REASON, verdict=FactVerdict.ABSENT)
                    for i, f in enumerate(item.key_facts, start=1)
                ]
            else:
                fact_verdicts, calls = judge.judge_key_facts(
                    answer.question, answer.text, item.key_facts
                )
                responses += calls
                facts = [
                    KeyFactJudgment(id=v.id, fact=f, reason=v.reason, verdict=v.verdict)
                    for f, v in zip(item.key_facts, fact_verdicts, strict=True)
                ]
            update |= {"key_facts": facts, "correctness": correctness(facts)}
    except JudgeError as error:
        logger.warning("Judge failed for %s: %s", item.id, error)
        responses += error.responses
        update = {"error": f"judge failed: {error}"}
    return base.model_copy(
        update={
            **update,
            "judge_calls": len(responses),
            "prompt_tokens": sum(r.prompt_tokens for r in responses),
            "completion_tokens": sum(r.completion_tokens for r in responses),
        }
    )


def judge_run(
    judge: Judge, generations: Sequence[QuestionGeneration], items: dict[str, GoldenItem]
) -> list[QuestionJudgment]:
    results = []
    for index, generation in enumerate(generations, start=1):
        results.append(judge_question(judge, generation, items[generation.question_id]))
        logger.info("Judged %d/%d (%s)", index, len(generations), generation.question_id)
    return results


def summarize(results: Sequence[QuestionJudgment]) -> JudgeSummary:
    ok = [r for r in results if r.error is None]
    return JudgeSummary(
        n_questions=len(results),
        n_errors=len(results) - len(ok),
        faithfulness=_mean([r.faithfulness for r in ok]),
        citation_accuracy=_mean([r.citation_accuracy for r in ok]),
        citation_precision=_mean([r.citation_precision for r in ok]),
        correctness=_mean([r.correctness for r in ok]),
        sentence_verdicts=dict(Counter(s.verdict.value for r in ok for s in r.sentences)),
        fact_verdicts=dict(Counter(f.verdict.value for r in ok for f in r.key_facts)),
        judge_calls=sum(r.judge_calls for r in results),
        prompt_tokens=sum(r.prompt_tokens for r in results),
        completion_tokens=sum(r.completion_tokens for r in results),
    )


def summarize_by_group(results: Sequence[QuestionJudgment]) -> dict[str, JudgeSummary]:
    """Summaries overall, per category and per split, keyed "all", "category:…", "split:…"."""
    return {name: summarize(group) for name, group in group_results(results).items()}


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None
