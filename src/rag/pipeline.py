"""End-to-end RAG: retrieve chunks, generate a grounded answer, resolve its citations.

Every query emits one structured JSON log line: retrieved chunk IDs with scores,
cited and invalid citation numbers, token usage and latency per stage.
"""

import json
import logging
import time

from rag.generation.citations import resolve_citations
from rag.generation.llm import LLM
from rag.generation.prompts import (
    REFUSAL_MESSAGE,
    SYSTEM_PROMPT,
    build_user_prompt,
    is_refusal,
)
from rag.models import Answer
from rag.retrieval.base import Retriever

logger = logging.getLogger(__name__)

MS_PER_SECOND = 1_000


class RAGPipeline:
    def __init__(self, retriever: Retriever, llm: LLM, top_k: int) -> None:
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k

    def answer(self, question: str) -> Answer:
        started = time.perf_counter()
        retrieved = self.retriever.retrieve(question, self.top_k)
        retrieved_at = time.perf_counter()
        latency_ms = {"retrieval": _ms(started, retrieved_at)}

        if not retrieved:
            # Nothing to ground on: refuse without paying for an LLM call.
            answer = Answer(
                question=question,
                text=REFUSAL_MESSAGE,
                refused=True,
                citations=[],
                invalid_citation_numbers=[],
                retrieved=[],
                model=self.llm.model,
                latency_ms={**latency_ms, "total": _ms(started, retrieved_at)},
            )
            self._log(answer)
            return answer

        response = self.llm.generate(SYSTEM_PROMPT, build_user_prompt(question, retrieved))
        generated_at = time.perf_counter()
        citations, invalid = resolve_citations(response.text, retrieved)
        answer = Answer(
            question=question,
            text=response.text,
            refused=is_refusal(response.text),
            citations=citations,
            invalid_citation_numbers=invalid,
            retrieved=retrieved,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms={
                **latency_ms,
                "generation": _ms(retrieved_at, generated_at),
                "total": _ms(started, generated_at),
            },
        )
        self._log(answer)
        return answer

    def _log(self, answer: Answer) -> None:
        record = {
            "event": "rag_query",
            "question": answer.question,
            "retriever": self.retriever.name,
            "top_k": self.top_k,
            "retrieved": [
                {"rank": item.rank, "chunk_id": item.chunk.chunk_id, "score": round(item.score, 4)}
                for item in answer.retrieved
            ],
            "model": answer.model,
            "refused": answer.refused,
            "cited": [citation.number for citation in answer.citations],
            "invalid_citations": answer.invalid_citation_numbers,
            "prompt_tokens": answer.prompt_tokens,
            "completion_tokens": answer.completion_tokens,
            "latency_ms": answer.latency_ms,
        }
        logger.info(json.dumps(record, ensure_ascii=False))


def _ms(start: float, end: float) -> float:
    return round((end - start) * MS_PER_SECOND, 1)
