import json
import logging

import pytest

from rag.generation.llm import LLMResponse
from rag.generation.prompts import REFUSAL_MESSAGE
from rag.models import RetrievedChunk
from rag.pipeline import RAGPipeline


class FakeRetriever:
    name = "fake"

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return self.results[:top_k]


class FakeLLM:
    model = "fake-llm"

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> LLMResponse:
        self.prompts.append((system, user))
        return LLMResponse(
            text=self.text, model="fake-llm-v1", prompt_tokens=50, completion_tokens=8
        )


def test_answer_with_citations(retrieved: list[RetrievedChunk]) -> None:
    retriever = FakeRetriever(retrieved)
    llm = FakeLLM("Un mois [2], trois mois sinon [3][9].")

    answer = RAGPipeline(retriever, llm, top_k=3).answer("Quel préavis ?")

    assert retriever.calls == [("Quel préavis ?", 3)]
    assert "[3] Titre F2" in llm.prompts[0][1]
    assert not answer.refused
    assert [c.chunk_id for c in answer.citations] == ["F1:fixed:0001", "F2:fixed:0002"]
    assert answer.invalid_citation_numbers == [9]
    assert answer.model == "fake-llm-v1"
    assert (answer.prompt_tokens, answer.completion_tokens) == (50, 8)
    assert set(answer.latency_ms) == {"retrieval", "generation", "total"}


def test_refusal_is_detected(retrieved: list[RetrievedChunk]) -> None:
    answer = RAGPipeline(FakeRetriever(retrieved), FakeLLM(REFUSAL_MESSAGE), top_k=3).answer("?")

    assert answer.refused
    assert answer.citations == []


def test_no_retrieved_chunk_refuses_without_calling_llm() -> None:
    llm = FakeLLM("should not be used")

    answer = RAGPipeline(FakeRetriever([]), llm, top_k=5).answer("?")

    assert answer.refused
    assert answer.text == REFUSAL_MESSAGE
    assert llm.prompts == []


def test_query_is_logged_as_structured_json(
    retrieved: list[RetrievedChunk], caplog: pytest.LogCaptureFixture
) -> None:
    pipeline = RAGPipeline(FakeRetriever(retrieved), FakeLLM("Réponse [1]."), top_k=2)

    with caplog.at_level(logging.INFO, logger="rag.pipeline"):
        pipeline.answer("Quel préavis ?")

    record = json.loads(caplog.records[-1].getMessage())
    assert record["event"] == "rag_query"
    assert record["retriever"] == "fake"
    assert [item["chunk_id"] for item in record["retrieved"]] == ["F1:fixed:0000", "F1:fixed:0001"]
    assert record["retrieved"][0]["score"] == 0.9
    assert record["cited"] == [1]
    assert "generation" in record["latency_ms"]
