"""API cost from measured token usage and list prices (USD per million tokens)."""

TOKENS_PER_MILLION = 1_000_000


def cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    input_usd_per_mtok: float,
    output_usd_per_mtok: float,
) -> float:
    return (
        prompt_tokens * input_usd_per_mtok + completion_tokens * output_usd_per_mtok
    ) / TOKENS_PER_MILLION
