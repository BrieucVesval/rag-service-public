"""LLM-as-judge: sentence-level support checks and key-fact correctness.

Two independent judgments per answer:
- faithfulness: for each answer sentence, do the context blocks support it, and
  which blocks? Citation markers are removed from the sentences shown to the judge,
  so the supporting blocks it reports are not influenced by what the generator cited.
- correctness: for each reference key fact of the golden set, does the answer state
  it? The judge does not see the context here, only the answer and the facts.

The judge writes a short reason before each verdict (reasoning first improves
verdicts) and replies in JSON mode. The reply is validated with pydantic; an invalid
reply is retried once with the validation error, then reported as JudgeError.
"""

import json
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from rag.evaluation.sentences import AnswerSentence
from rag.generation.llm import LLM, LLMResponse
from rag.generation.prompts import format_context
from rag.models import RetrievedChunk


class SupportVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    NO_CLAIM = "no_claim"


class FactVerdict(StrEnum):
    PRESENT = "present"
    PARTIAL = "partial"
    ABSENT = "absent"
    CONTRADICTED = "contradicted"


class SentenceVerdict(BaseModel):
    id: int
    reason: str
    verdict: SupportVerdict
    supporting_blocks: list[int]


class KeyFactVerdict(BaseModel):
    id: int
    reason: str
    verdict: FactVerdict


class _SentenceReply(BaseModel):
    sentences: list[SentenceVerdict]


class _FactReply(BaseModel):
    facts: list[KeyFactVerdict]


VerdictT = TypeVar("VerdictT", SentenceVerdict, KeyFactVerdict)


class JudgeError(RuntimeError):
    """The judge did not return valid verdicts, even after one retry.

    Carries the failed calls' responses: their tokens were paid and must be counted.
    """

    def __init__(self, message: str, responses: Sequence[LLMResponse]) -> None:
        super().__init__(message)
        self.responses = list(responses)


FAITHFULNESS_SYSTEM_PROMPT = """You are a strict fact-checker for an assistant that answers \
questions about French public-service rules from numbered source blocks.

You receive the source blocks, the user's question, and the assistant's answer split into \
numbered sentences. For each sentence, decide whether the source blocks support it.

Verdicts:
- "supported": every factual element of the sentence is stated in the sources (paraphrase is fine).
- "partial": some elements are stated in the sources, others are not.
- "unsupported": the sources do not state it. This includes plausible inferences, \
generalisations, and conclusions drawn from what the sources do not say.
- "contradicted": the sources state something incompatible with the sentence.
- "no_claim": the sentence states no fact (heading, transition, question, offer to help).

Rules:
- Judge only against the sources. Ignore your own knowledge, even if the sentence is true.
- A sentence saying the information is missing from the sources is "supported" if the \
sources indeed do not contain it, "contradicted" if they do.
- "supporting_blocks": the numbers of every block that states the sentence's content; \
empty for "unsupported", "contradicted" and "no_claim".
- Write "reason" first: one short sentence in English. Then give the verdict.

Reply with a JSON object, one entry per sentence, in order:
{"sentences": [{"id": 1, "reason": "...", "verdict": "supported", "supporting_blocks": [2]}]}"""


CORRECTNESS_SYSTEM_PROMPT = """You grade an assistant's answer to a question about French \
public-service rules against a list of reference facts.

For each reference fact, decide whether the answer states it.

Verdicts:
- "present": the answer states the fact or a clearly equivalent statement. Numbers, \
durations, thresholds and conditions must match.
- "partial": the answer states the fact incompletely (a missing condition, a vaguer \
statement, only part of a list).
- "absent": the answer does not state the fact.
- "contradicted": the answer states something incompatible with the fact.

Rules:
- Ignore extra information in the answer that is not about the reference facts.
- Ignore citation markers such as [1].
- Write "reason" first: one short sentence in English. Then give the verdict.

Reply with a JSON object, one entry per fact, in order:
{"facts": [{"id": 1, "reason": "...", "verdict": "present"}]}"""


RETRY_INSTRUCTION = (
    "\n\nYour previous reply was invalid: {error}\n"
    "Reply again with a valid JSON object only, with exactly one entry per id."
)


def faithfulness_prompt(
    question: str, retrieved: Sequence[RetrievedChunk], sentences: Sequence[AnswerSentence]
) -> str:
    numbered = "\n".join(f"({s.id}) {s.text_without_citations}" for s in sentences)
    return (
        f"Sources:\n\n{format_context(retrieved)}\n\n"
        f"Question: {question}\n\n"
        f"Answer sentences:\n{numbered}"
    )


def correctness_prompt(question: str, answer: str, key_facts: Sequence[str]) -> str:
    facts = "\n".join(f"({index}) {fact}" for index, fact in enumerate(key_facts, start=1))
    return f"Question: {question}\n\nAnswer:\n{answer}\n\nReference facts:\n{facts}"


class Judge:
    """Calls an LLM in JSON mode and returns validated verdicts plus token usage."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.model = llm.model

    def judge_sentences(
        self,
        question: str,
        retrieved: Sequence[RetrievedChunk],
        sentences: Sequence[AnswerSentence],
    ) -> tuple[list[SentenceVerdict], list[LLMResponse]]:
        user = faithfulness_prompt(question, retrieved, sentences)
        n_blocks = len(retrieved)

        def parse(text: str) -> list[SentenceVerdict]:
            verdicts = _SentenceReply.model_validate(json.loads(text)).sentences
            _check_ids([v.id for v in verdicts], len(sentences))
            for verdict in verdicts:
                out_of_range = [b for b in verdict.supporting_blocks if not 1 <= b <= n_blocks]
                if out_of_range:
                    raise ValueError(f"sentence {verdict.id}: unknown blocks {out_of_range}")
            return verdicts

        return self._call(FAITHFULNESS_SYSTEM_PROMPT, user, parse)

    def judge_key_facts(
        self, question: str, answer: str, key_facts: Sequence[str]
    ) -> tuple[list[KeyFactVerdict], list[LLMResponse]]:
        user = correctness_prompt(question, answer, key_facts)

        def parse(text: str) -> list[KeyFactVerdict]:
            verdicts = _FactReply.model_validate(json.loads(text)).facts
            _check_ids([v.id for v in verdicts], len(key_facts))
            return verdicts

        return self._call(CORRECTNESS_SYSTEM_PROMPT, user, parse)

    def _call(
        self, system: str, user: str, parse: Callable[[str], list[VerdictT]]
    ) -> tuple[list[VerdictT], list[LLMResponse]]:
        responses = [self.llm.generate(system, user)]
        try:
            return parse(responses[0].text), responses
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            retry_user = user + RETRY_INSTRUCTION.format(error=_short(error))
            responses.append(self.llm.generate(system, retry_user))
            try:
                return parse(responses[1].text), responses
            except (json.JSONDecodeError, ValidationError, ValueError) as second_error:
                raise JudgeError(
                    f"invalid judge reply after retry: {_short(second_error)}", responses
                ) from second_error


def _check_ids(ids: list[int], expected: int) -> None:
    if ids != list(range(1, expected + 1)):
        raise ValueError(f"expected ids 1..{expected} in order, got {ids}")


def _short(error: Exception, limit: int = 300) -> str:
    return str(error).replace("\n", " ")[:limit]
