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
