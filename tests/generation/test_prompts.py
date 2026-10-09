from rag.generation.prompts import (
    REFUSAL_MESSAGE,
    SYSTEM_PROMPT,
    build_user_prompt,
    format_context,
    is_refusal,
)
from rag.models import RetrievedChunk


def test_context_blocks_are_numbered_in_rank_order(retrieved: list[RetrievedChunk]) -> None:
    context = format_context(retrieved)

    assert context.startswith("[1] Titre F1\nURL: https://example.org/F1\nTexte du chunk 0.")
    assert context.index("[2] Titre F1") < context.index("[3] Titre F2")
    assert "Texte du chunk 2." in context


def test_user_prompt_puts_question_after_sources(retrieved: list[RetrievedChunk]) -> None:
    prompt = build_user_prompt("Quel préavis ?", retrieved)

    assert prompt.startswith("Sources:\n\n[1]")
    assert prompt.endswith("Question: Quel préavis ?")


def test_system_prompt_contains_refusal_message() -> None:
    assert REFUSAL_MESSAGE in SYSTEM_PROMPT


def test_is_refusal() -> None:
    assert is_refusal(f"  {REFUSAL_MESSAGE}")
    assert not is_refusal("Le préavis est d'un mois [1].")
