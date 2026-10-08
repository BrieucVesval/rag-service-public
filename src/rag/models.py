"""Data models shared across the pipeline."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Document(BaseModel):
    """A source document after ingestion: normalized Markdown text plus metadata."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    source: str
    title: str
    text: str
    url: str | None = None
    doc_type: str | None = None
    modified_at: date | None = None
    breadcrumb: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    description: str | None = None


class Chunk(BaseModel):
    """A passage of a Document: the unit that is embedded, indexed and cited."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    doc_id: str
    text: str
    strategy: str
    position: int
    start_char: int
    end_char: int
    doc_title: str
    url: str | None = None
