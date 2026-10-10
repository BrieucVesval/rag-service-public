import pytest

from rag.costs import cost_usd


def test_cost_from_tokens_and_prices_per_million() -> None:
    # 300k input tokens at $0.50/M + 40k output tokens at $1.50/M (Mistral Large 3 list price).
    assert cost_usd(300_000, 40_000, 0.50, 1.50) == pytest.approx(0.21)


def test_zero_tokens_cost_nothing() -> None:
    assert cost_usd(0, 0, 0.50, 1.50) == 0.0
