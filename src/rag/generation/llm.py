"""LLM protocol and the Mistral chat provider."""

from typing import Protocol

from mistralai.client import Mistral
from mistralai.client.models import (
    ChatCompletionRequestMessage,
    JSONSchema,
    ResponseFormat,
    SystemMessage,
    UserMessage,
)
from pydantic import BaseModel

from rag.config import Settings
from rag.indexing.embedder import RateLimiter, make_mistral_client


class LLMResponse(BaseModel):
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLM(Protocol):
    model: str

    def generate(
        self, system: str, user: str, schema: type[BaseModel] | None = None
    ) -> LLMResponse:
        """Free text, or a JSON object conforming to `schema` when one is given."""
        ...


class MistralLLM:
    def __init__(
        self,
        client: Mistral,
        model: str,
        temperature: float,
        max_tokens: int,
        random_seed: int,
        rate_limiter: RateLimiter,
    ) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.random_seed = random_seed
        self.rate_limiter = rate_limiter

    @classmethod
    def from_settings(cls, settings: Settings) -> "MistralLLM":
        return cls(
            client=make_mistral_client(settings),
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            random_seed=settings.llm_random_seed,
            rate_limiter=RateLimiter(settings.llm_requests_per_minute),
        )

    @classmethod
    def judge_from_settings(cls, settings: Settings) -> "MistralLLM":
        """The LLM judge: its own model, rate limit and token budget."""
        return cls(
            client=make_mistral_client(settings),
            model=settings.judge_model,
            temperature=settings.judge_temperature,
            max_tokens=settings.judge_max_tokens,
            random_seed=settings.llm_random_seed,
            rate_limiter=RateLimiter(settings.judge_requests_per_minute),
        )

    def generate(
        self, system: str, user: str, schema: type[BaseModel] | None = None
    ) -> LLMResponse:
        messages: list[ChatCompletionRequestMessage] = [
            SystemMessage(content=system),
            UserMessage(content=user),
        ]
        self.rate_limiter.wait()
        response = self.client.chat.complete(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            random_seed=self.random_seed,
            response_format=_response_format(schema),
        )
        message = response.choices[0].message if response.choices else None
        if message is None:
            raise RuntimeError("Mistral returned no message")
        return LLMResponse(
            text=_content_text(message.content),
            # The resolved model name returned by the API, logged for reproducibility.
            model=response.model or self.model,
            prompt_tokens=response.usage.prompt_tokens or 0,
            completion_tokens=response.usage.completion_tokens or 0,
        )


def _response_format(schema: type[BaseModel] | None) -> ResponseFormat | None:
    """Strict structured output: decoding is constrained to the JSON schema.

    Plain JSON mode ("json_object") was not enough: Mistral Large 3 returned truncated,
    invalid JSON for one answer, identically on retry at temperature 0 (2026-10-10).
    """
    if schema is None:
        return None
    return ResponseFormat(
        type="json_schema",
        json_schema=JSONSchema(
            name=schema.__name__, schema_definition=schema.model_json_schema(), strict=True
        ),
    )


def _content_text(content: object) -> str:
    """Message content is either a string or a list of typed chunks; keep the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(getattr(part, "text", "") or "" for part in content)
    return ""
