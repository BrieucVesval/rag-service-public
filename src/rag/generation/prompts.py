"""Grounded prompt: the LLM answers only from numbered context blocks and cites them."""

from collections.abc import Sequence

from rag.models import RetrievedChunk

REFUSAL_MESSAGE = "Je ne trouve pas cette information dans les sources disponibles."

SYSTEM_PROMPT = f"""You answer questions about French public-service procedures \
(service-public.gouv.fr), using only the numbered sources given in the user message.

Rules:
1. Use only information stated in the sources. Never add outside knowledge.
2. After each sentence that states a fact, cite its source numbers in square brackets, \
e.g. [1] or [2][3]. Cite only numbers that exist in the sources.
3. When rules differ by situation (e.g. Paris vs. other communes, tenant vs. owner), \
say which situation each rule applies to.
4. If the sources do not contain the answer, reply exactly: "{REFUSAL_MESSAGE}" and nothing else.
5. If the sources answer only part of the question, answer that part and say what is missing.
6. Answer in French, concisely."""


def format_context(retrieved: Sequence[RetrievedChunk]) -> str:
    """Number each chunk as a source block: [n] title, URL, text."""
    blocks = []
    for number, item in enumerate(retrieved, start=1):
        header = f"[{number}] {item.chunk.doc_title}"
        if item.chunk.url:
            header += f"\nURL: {item.chunk.url}"
        blocks.append(f"{header}\n{item.chunk.text}")
    return "\n\n".join(blocks)


def build_user_prompt(question: str, retrieved: Sequence[RetrievedChunk]) -> str:
    return f"Sources:\n\n{format_context(retrieved)}\n\nQuestion: {question}"


def is_refusal(answer_text: str) -> bool:
    return answer_text.strip().startswith(REFUSAL_MESSAGE)
