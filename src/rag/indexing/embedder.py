"""Embedders turn texts into vectors; similar meanings give nearby vectors."""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from mistralai.client import Mistral
from mistralai.client.utils import BackoffStrategy, RetryConfig

from rag.config import Settings

logger = logging.getLogger(__name__)

RETRY_INITIAL_INTERVAL_MS = 1_000
RETRY_MAX_INTERVAL_MS = 30_000
RETRY_EXPONENT = 2.0
MS_PER_SECOND = 1_000
SECONDS_PER_MINUTE = 60.0


class Embedder(Protocol):
    model: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class RateLimiter:
    """Spaces calls so that at most `requests_per_minute` start in any minute."""

    def __init__(
        self,
        requests_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = SECONDS_PER_MINUTE / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_call is not None:
            delay = self._last_call + self.min_interval - now
            if delay > 0:
                self._sleep(delay)
                now += delay
        self._last_call = now


def make_mistral_client(settings: Settings) -> Mistral:
    """Mistral client retrying 429 and 5xx with exponential backoff (honors Retry-After)."""
    if settings.mistral_api_key is None:
        raise RuntimeError("MISTRAL_API_KEY is not set (see .env.example)")
    retry = RetryConfig(
        strategy="backoff",
        backoff=BackoffStrategy(
            initial_interval=RETRY_INITIAL_INTERVAL_MS,
            max_interval=RETRY_MAX_INTERVAL_MS,
            exponent=RETRY_EXPONENT,
            max_elapsed_time=int(settings.mistral_max_retry_s * MS_PER_SECOND),
        ),
        retry_connection_errors=True,
    )
    return Mistral(
        api_key=settings.mistral_api_key.get_secret_value(),
        retry_config=retry,
        timeout_ms=int(settings.mistral_timeout_s * MS_PER_SECOND),
    )


class MistralEmbedder:
    """Embeds texts with the Mistral API, in batches, under the rate limit."""

    def __init__(
        self, client: Mistral, model: str, batch_size: int, rate_limiter: RateLimiter
    ) -> None:
        self.client = client
        self.model = model
        self.batch_size = batch_size
        self.rate_limiter = rate_limiter
        self.tokens_used = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> "MistralEmbedder":
        return cls(
            client=make_mistral_client(settings),
            model=settings.embedding_model,
            batch_size=settings.embedding_batch_size,
            rate_limiter=RateLimiter(settings.mistral_requests_per_minute),
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            vectors.extend(self._embed_batch(batch))
            logger.info("Embedded %d/%d texts", len(vectors), len(texts))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.rate_limiter.wait()
        response = self.client.embeddings.create(model=self.model, inputs=texts)
        self.tokens_used += response.usage.prompt_tokens or 0
        # Order by the returned index rather than trusting the response order.
        items = sorted(response.data, key=lambda item: item.index or 0)
        vectors = [item.embedding for item in items if item.embedding is not None]
        if len(vectors) != len(texts):
            raise RuntimeError(f"Expected {len(texts)} embeddings, got {len(vectors)}")
        return vectors
