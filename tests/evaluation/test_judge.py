import json
from typing import Any

import pytest

from rag.evaluation.judge import (
    RETRY_INSTRUCTION,
    FactVerdict,
    Judge,
    JudgeError,
    SupportVerdict,
)
from rag.evaluation.sentences import split_sentences
from rag.generation.llm import LLMResponse
from rag.models import RetrievedChunk


class ScriptedLLM:
    """Returns the queued replies in order and records every prompt it receives."""

    model = "fake-judge"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> LLMResponse:
        self.prompts.append((system, user))
        return LLMResponse(
            text=self.replies.pop(0), model=self.model, prompt_tokens=100, completion_tokens=20
        )


def sentence_reply(*entries: dict[str, Any]) -> str:
    return json.dumps({"sentences": list(entries)})


def entry(id: int, verdict: str = "supported", blocks: tuple[int, ...] = (1,)) -> dict[str, Any]:
    return {"id": id, "reason": "r", "verdict": verdict, "supporting_blocks": list(blocks)}


def test_sentence_verdicts_are_parsed_and_markers_hidden_from_judge(
    retrieved: list[RetrievedChunk],
) -> None:
    sentences = split_sentences("Trois mois [1]. Un mois à Paris [3].")
    llm = ScriptedLLM(sentence_reply(entry(1), entry(2, "unsupported", ())))

    verdicts, responses = Judge(llm).judge_sentences("Préavis ?", retrieved, sentences)

    assert [v.verdict for v in verdicts] == [SupportVerdict.SUPPORTED, SupportVerdict.UNSUPPORTED]
    assert verdicts[0].supporting_blocks == [1]
    assert len(responses) == 1
    user_prompt = llm.prompts[0][1]
    assert "(1) Trois mois." in user_prompt and "[1]." not in user_prompt.split("Answer")[1]
    assert "[3] Titre F2" in user_prompt  # numbered source blocks


def test_invalid_reply_is_retried_with_the_error(retrieved: list[RetrievedChunk]) -> None:
    sentences = split_sentences("Trois mois [1]. Un mois [2].")
    llm = ScriptedLLM("not json", sentence_reply(entry(1), entry(2)))

    verdicts, responses = Judge(llm).judge_sentences("Q ?", retrieved, sentences)

    assert len(verdicts) == 2
    assert len(responses) == 2
    assert RETRY_INSTRUCTION.split(":")[0].strip() in llm.prompts[1][1]


@pytest.mark.parametrize(
    "bad_reply",
    [
        sentence_reply(entry(1)),  # one sentence missing
        sentence_reply(entry(2), entry(1)),  # wrong order
        sentence_reply(entry(1, blocks=(9,)), entry(2)),  # block that does not exist
        sentence_reply(entry(1, verdict="maybe"), entry(2)),  # unknown verdict
    ],
)
def test_inconsistent_replies_fail_after_one_retry(
    retrieved: list[RetrievedChunk], bad_reply: str
) -> None:
    sentences = split_sentences("Trois mois [1]. Un mois [2].")
    llm = ScriptedLLM(bad_reply, bad_reply)

    with pytest.raises(JudgeError):
        Judge(llm).judge_sentences("Q ?", retrieved, sentences)
    assert len(llm.prompts) == 2


def test_key_fact_verdicts() -> None:
    reply = json.dumps(
        {
            "facts": [
                {"id": 1, "reason": "r", "verdict": "present"},
                {"id": 2, "reason": "r", "verdict": "contradicted"},
            ]
        }
    )
    llm = ScriptedLLM(reply)

    verdicts, _ = Judge(llm).judge_key_facts("Q ?", "Trois mois [1].", ["3 mois", "1 mois"])

    assert [v.verdict for v in verdicts] == [FactVerdict.PRESENT, FactVerdict.CONTRADICTED]
    assert "(2) 1 mois" in llm.prompts[0][1]
    assert "Sources:" not in llm.prompts[0][1]  # correctness is judged without the context
