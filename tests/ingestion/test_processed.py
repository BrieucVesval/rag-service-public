from pathlib import Path

from rag.ingestion.processed import load_processed_documents
from rag.models import Document


def test_loads_documents_sorted_and_skips_manifest(tmp_path: Path) -> None:
    for doc_id in ("F2", "F1"):
        document = Document(doc_id=doc_id, source="test", title=doc_id, text="texte")
        (tmp_path / f"{doc_id}.json").write_text(document.model_dump_json())
    (tmp_path / "manifest.json").write_text('{"document_count": 2}')

    documents = load_processed_documents(tmp_path)

    assert [document.doc_id for document in documents] == ["F1", "F2"]


def test_empty_directory_gives_no_document(tmp_path: Path) -> None:
    assert load_processed_documents(tmp_path) == []
