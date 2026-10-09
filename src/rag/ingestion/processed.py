"""Read the normalized Documents written by scripts/ingest.py."""

from pathlib import Path

from rag.models import Document

MANIFEST_NAME = "manifest.json"


def load_processed_documents(directory: Path) -> list[Document]:
    """Load every Document JSON of a processed directory, sorted by file name."""
    paths = sorted(path for path in directory.glob("*.json") if path.name != MANIFEST_NAME)
    return [Document.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]
