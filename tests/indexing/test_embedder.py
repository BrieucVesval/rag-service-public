from types import SimpleNamespace
from typing import Any

import pytest

from rag.config import Settings
from rag.indexing.embedder import MistralEmbedder, RateLimiter, make_mistral_client


class FakeEmbeddingsAPI:
    """Mimics `client.embeddings`: one vector [len(text), position] per input."""

    def __init__(self, reverse_order: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.reverse_order = reverse_order

    def create(self, *, model: str, inputs: list[str]) -> Any:
        self.calls.append(inputs)
        data = [
            SimpleNamespace(index=i, embedding=[float(len(text)), float(i)])
            for i, text in enumerate(inputs)
        ]
        if self.reverse_order:
            data.reverse()
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=10 * len(inputs)))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_embedder(api: FakeEmbeddingsAPI, batch_size: int = 2) -> MistralEmbedder:
    clock = FakeClock()
    limiter = RateLimiter(60_000, clock=clock.time, sleep=clock.sleep)
    client: Any = SimpleNamespace(embeddings=api)
    return MistralEmbedder(
        client, model="mistral-embed", batch_size=batch_size, rate_limiter=limiter
    )


def test_embed_documents_batches_and_keeps_order() -> None:
    api = FakeEmbeddingsAPI()
    embedder = make_embedder(api, batch_size=2)

    vectors = embedder.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])

    assert api.calls == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert [vector[0] for vector in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert embedder.tokens_used == 50


def test_vectors_are_reordered_by_returned_index() -> None:
    embedder = make_embedder(FakeEmbeddingsAPI(reverse_order=True), batch_size=3)

    vectors = embedder.embed_documents(["a", "bb", "ccc"])

    assert vectors == [[1.0, 0.0], [2.0, 1.0], [3.0, 2.0]]


def test_embed_query_returns_one_vector() -> None:
    embedder = make_embedder(FakeEmbeddingsAPI())

    assert embedder.embed_query("abc") == [3.0, 0.0]


def test_incomplete_response_raises() -> None:
    api = FakeEmbeddingsAPI()
    api.create = lambda *, model, inputs: SimpleNamespace(  # type: ignore[method-assign]
        data=[], usage=SimpleNamespace(prompt_tokens=0)
    )

    with pytest.raises(RuntimeError, match="Expected 1 embeddings, got 0"):
        make_embedder(api).embed_query("abc")


def test_rate_limiter_spaces_calls() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=30, clock=clock.time, sleep=clock.sleep)

    limiter.wait()
    clock.now += 0.5
    limiter.wait()
    limiter.wait()

    assert clock.sleeps == [1.5, 2.0]


def test_rate_limiter_does_not_sleep_when_calls_are_slow() -> None:
    clock = FakeClock()
    limiter = RateLimiter(requests_per_minute=60, clock=clock.time, sleep=clock.sleep)

    limiter.wait()
    clock.now += 5
    limiter.wait()

    assert clock.sleeps == []


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        make_mistral_client(Settings(_env_file=None))  # type: ignore[call-arg]
