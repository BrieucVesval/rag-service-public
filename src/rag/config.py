"""Centralized configuration, loaded from environment variables and `.env`.

Every tunable parameter lives here so experiments differ only by config.
Pipeline settings use the `RAG_` prefix (e.g. `RAG_CHUNK_SIZE=1500`);
API keys use their provider's usual variable name.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mistral_api_key: SecretStr | None = Field(default=None, validation_alias="MISTRAL_API_KEY")

    processed_dir: Path = Path("data/processed/service_public")
    chroma_dir: Path = Path("data/indexes/chroma")

    # Chunking: "fixed" (baseline windows) or "headers" (Markdown heading tree).
    chunk_strategy: Literal["fixed", "headers"] = "fixed"
    # Sizes in characters (~3 characters per token in French Markdown, measured).
    # Fixed: window size and overlap. Headers: maximum passage size (heading path not
    # counted) and the overlap used only when a single paragraph exceeds it.
    chunk_size: int = Field(default=2000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    # Headers: "path" prepends the heading path to the chunk text, "none" does not.
    header_prefix: Literal["path", "none"] = "path"

    # Embeddings. A batch of 32 chunks of 2,000 characters is ~21k tokens; 128 chunks
    # exceeded Mistral's per-request token limit when measured on 2026-10-08.
    embedding_model: str = "mistral-embed"
    embedding_batch_size: int = Field(default=32, gt=0)
    # Embedding requests; the free plan allows 60/minute for mistral-embed.
    mistral_requests_per_minute: int = Field(default=50, gt=0)
    mistral_timeout_s: float = Field(default=60.0, gt=0)
    mistral_max_retry_s: float = Field(default=120.0, gt=0)

    # Retrieval
    retrieval_top_k: int = Field(default=5, gt=0)

    # Generation. A dated model version, not "-latest", so runs stay comparable.
    # Ministral 14B: the largest chat model with a non-zero rate limit on the free plan
    # (measured 2026-10-09: mistral-small / mistral-medium had a limit of 0 requests/minute).
    llm_model: str = "ministral-14b-2512"
    llm_requests_per_minute: int = Field(default=25, gt=0)  # plan limit: 30
    llm_temperature: float = Field(default=0.0, ge=0)
    llm_max_tokens: int = Field(default=1024, gt=0)
    llm_random_seed: int = 0
    # List prices in USD per million tokens (docs.mistral.ai/inference/pricing, 2026-10-10),
    # used to report the cost of each run from its measured token usage.
    llm_input_usd_per_mtok: float = Field(default=0.20, ge=0)
    llm_output_usd_per_mtok: float = Field(default=0.20, ge=0)

    # LLM judge for evaluation: a model stronger than the generator, to limit
    # self-preference bias (Mistral Large 3; paid plan limit: 15 requests/minute).
    judge_model: str = "mistral-large-2512"
    judge_requests_per_minute: int = Field(default=12, gt=0)
    judge_temperature: float = Field(default=0.0, ge=0)
    judge_max_tokens: int = Field(default=4096, gt=0)
    judge_input_usd_per_mtok: float = Field(default=0.50, ge=0)
    judge_output_usd_per_mtok: float = Field(default=1.50, ge=0)

    # Evaluation. Retrieval metrics are reported at several cut-offs from a single query
    # per question (the deepest k is retrieved once); retrieval_top_k is always included.
    golden_set_path: Path = Path("data/golden_set/golden_set.yaml")
    experiments_dir: Path = Path("experiments")
    eval_k_values: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

    @model_validator(mode="after")
    def _valid_k_values(self) -> "Settings":
        if not self.eval_k_values or min(self.eval_k_values) <= 0:
            raise ValueError("eval_k_values must be a non-empty list of positive integers")
        self.eval_k_values = sorted({*self.eval_k_values, self.retrieval_top_k})
        return self


def get_settings() -> Settings:
    return Settings()
