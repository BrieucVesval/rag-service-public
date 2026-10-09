"""Centralized configuration, loaded from environment variables and `.env`.

Every tunable parameter lives here so experiments differ only by config.
Pipeline settings use the `RAG_` prefix (e.g. `RAG_CHUNK_SIZE=1500`);
API keys use their provider's usual variable name.
"""

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mistral_api_key: SecretStr | None = Field(default=None, validation_alias="MISTRAL_API_KEY")

    processed_dir: Path = Path("data/processed/service_public")
    chroma_dir: Path = Path("data/indexes/chroma")

    # Fixed-size chunking, in characters (~3-4 characters per token in French Markdown).
    chunk_size: int = Field(default=2000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)

    # Embeddings. A batch of 32 chunks of 2,000 characters is ~21k tokens; 128 chunks
    # exceeded Mistral's per-request token limit when measured on 2026-10-08.
    embedding_model: str = "mistral-embed"
    embedding_batch_size: int = Field(default=32, gt=0)
    # Free tier allows 60 requests/minute; stay slightly below.
    mistral_requests_per_minute: int = Field(default=50, gt=0)
    mistral_timeout_s: float = Field(default=60.0, gt=0)
    mistral_max_retry_s: float = Field(default=120.0, gt=0)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


def get_settings() -> Settings:
    return Settings()
