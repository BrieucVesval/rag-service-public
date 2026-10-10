"""LLM protocol and the Mistral chat provider."""

from typing import Protocol

from mistralai.client import Mistral
from mistralai.client.models import (
    ChatCompletionRequestMessage,
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

    def generate(self, system: str, user: str) -> LLMResponse: ...


class MistralLLM:
    def __init__(
        self,
        client: Mistral,
        model: str,
        temperature: float,
        max_tokens: int,
        random_seed: int,
        rate_limiter: RateLimiter,
        json_output: bool = False,
    ) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.random_seed = random_seed
        self.rate_limiter = rate_limiter
        # JSON mode: the API guarantees a syntactically valid JSON object (not its schema).
        self.response_format = ResponseFormat(type="json_object") if json_output else None

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
        """The LLM judge: its own model, rate limit and token budget, JSON output."""
        return cls(
            client=make_mistral_client(settings),
            model=settings.judge_model,
            temperature=settings.judge_temperature,
            max_tokens=settings.judge_max_tokens,
            random_seed=settings.llm_random_seed,
            rate_limiter=RateLimiter(settings.judge_requests_per_minute),
            json_output=True,
        )

    def generate(self, system: str, user: str) -> LLMResponse:
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
            response_format=self.response_format,
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


def _content_text(content: object) -> str:
    """Message content is either a string or a list of typed chunks; keep the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(getattr(part, "text", "") or "" for part in content)
    return ""
