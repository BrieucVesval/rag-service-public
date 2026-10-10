from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from rag.generation.llm import MistralLLM
from rag.indexing.embedder import RateLimiter


class FakeChatAPI:
    def __init__(self, content: Any, choices: bool = True) -> None:
        self.content = content
        self.choices = choices
        self.kwargs: dict[str, Any] = {}

    def complete(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        choices = [SimpleNamespace(message=SimpleNamespace(content=self.content))]
        return SimpleNamespace(
            model="mistral-small-2603",
            choices=choices if self.choices else [],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
        )


def make_llm(chat: FakeChatAPI) -> MistralLLM:
    client: Any = SimpleNamespace(chat=chat)
    limiter = RateLimiter(60_000, clock=lambda: 0.0, sleep=lambda _: None)
    return MistralLLM(
        client,
        model="mistral-small-2603",
        temperature=0.0,
        max_tokens=256,
        random_seed=7,
        rate_limiter=limiter,
    )


def test_generate_sends_system_and_user_messages_with_settings() -> None:
    chat = FakeChatAPI("Réponse [1].")

    response = make_llm(chat).generate("règles", "question")

    assert [m.role for m in chat.kwargs["messages"]] == ["system", "user"]
    assert [m.content for m in chat.kwargs["messages"]] == ["règles", "question"]
    assert (chat.kwargs["temperature"], chat.kwargs["max_tokens"]) == (0.0, 256)
    assert chat.kwargs["random_seed"] == 7
    assert response.text == "Réponse [1]."
    assert (response.prompt_tokens, response.completion_tokens) == (120, 30)
    assert response.model == "mistral-small-2603"


def test_generate_joins_chunked_content() -> None:
    chat = FakeChatAPI([SimpleNamespace(text="Bonjour "), SimpleNamespace(text="[1]")])

    assert make_llm(chat).generate("s", "u").text == "Bonjour [1]"


def test_generate_without_choice_raises() -> None:
    with pytest.raises(RuntimeError, match="no message"):
        make_llm(FakeChatAPI("x", choices=False)).generate("s", "u")


def test_text_by_default_strict_json_schema_on_request() -> None:
    class Reply(BaseModel):
        answer: str

    chat = FakeChatAPI('{"answer": "oui"}')
    llm = make_llm(chat)

    llm.generate("s", "u")
    assert chat.kwargs["response_format"] is None

    llm.generate("s", "u", Reply)
    response_format = chat.kwargs["response_format"]
    assert response_format.type == "json_schema"
    assert response_format.json_schema.name == "Reply"
    assert response_format.json_schema.strict is True
    assert response_format.json_schema.schema_definition["required"] == ["answer"]
