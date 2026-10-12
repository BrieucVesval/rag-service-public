import pytest

from rag.chunking.headers import HeaderChunker, parse_sections
from rag.models import Chunk, Document


def make_document(text: str) -> Document:
    return Document(doc_id="F1", source="test", title="T", text=text, url="https://example.org/F1")


def words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


def passages(document: Document, chunks: list[Chunk]) -> list[str]:
    return [document.text[chunk.start_char : chunk.end_char] for chunk in chunks]


def table(rows: int, caption: str = "**Tarifs**") -> str:
    lines = ["| Col A | Col B |", "| --- | --- |"]
    lines += [f"| ligne {i} a | ligne {i} b |" for i in range(rows)]
    return f"{caption}\n\n" + "\n".join(lines)


def test_document_that_fits_is_one_chunk_with_metadata() -> None:
    document = make_document("# T\n\nIntro.\n\n## A\n\nTexte A.")

    chunks = HeaderChunker(max_size=100, overlap=10).chunk(document)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == document.text
    assert chunk.chunk_id == "F1:headers:0000"
    assert (chunk.strategy, chunk.position, chunk.heading_path) == ("headers", 0, None)
    assert (chunk.doc_title, chunk.url) == ("T", "https://example.org/F1")


def test_sibling_sections_are_packed_and_chunks_start_at_headings() -> None:
    document = make_document("# T\n\nIntro.\n\n## A\n\nTexte A.\n\n## B\n\nTexte B.")

    chunks = HeaderChunker(max_size=30, overlap=5).chunk(document)

    assert passages(document, chunks) == ["# T\n\nIntro.\n\n## A\n\nTexte A.", "## B\n\nTexte B."]
    assert [chunk.heading_path for chunk in chunks] == [None, "T"]
    assert chunks[1].text == "T\n\n## B\n\nTexte B."


def test_nested_cases_keep_their_heading_path_and_a_short_lead_joins_the_next_case() -> None:
    document = make_document(
        "# T\n\n## A\n\nLes cas :\n\n### Cas : Paris\n\nRègle de Paris."
        "\n\n### Cas : Lyon\n\nRègle de Lyon."
    )

    chunks = HeaderChunker(max_size=55, overlap=5).chunk(document)

    # "# T" alone would be a heading-only chunk: it joins the start of section A.
    assert passages(document, chunks) == [
        "# T\n\n## A\n\nLes cas :\n\n### Cas : Paris\n\nRègle de Paris.",
        "### Cas : Lyon\n\nRègle de Lyon.",
    ]
    assert chunks[1].heading_path == "T > A"
    assert chunks[1].text == "T > A\n\n### Cas : Lyon\n\nRègle de Lyon."


def test_prefix_none_keeps_the_passage_alone_but_records_the_path() -> None:
    document = make_document("# T\n\nIntro.\n\n## A\n\nTexte A.\n\n## B\n\nTexte B.")

    chunks = HeaderChunker(max_size=30, overlap=5, prefix="none").chunk(document)

    assert [chunk.text for chunk in chunks] == passages(document, chunks)
    assert chunks[1].heading_path == "T"
    assert HeaderChunker(max_size=30, overlap=5, prefix="none").label == "headers-none"
    assert HeaderChunker(max_size=30, overlap=5).label == "headers-path"


def test_long_paragraph_falls_back_to_overlapping_windows() -> None:
    document = make_document(f"# T\n\n## A\n\n{words('mot', 80)}")

    chunks = HeaderChunker(max_size=100, overlap=20, prefix="none").chunk(document)

    assert len(chunks) > 3
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    # Known limit: the headings do not fit with a full window, so they stay alone.
    assert chunks[0].text == "# T\n\n## A"
    windows = chunks[1:]
    for previous, current in zip(windows, windows[1:], strict=False):
        assert current.start_char < previous.end_char  # overlap inside the paragraph
    covered = {word for chunk in chunks for word in chunk.text.split()}
    assert set(words("mot", 80).split()) <= covered


def test_long_table_is_split_by_rows_repeating_caption_and_header() -> None:
    document = make_document(f"# T\n\n## Tableau\n\n{table(rows=12)}")

    chunks = HeaderChunker(max_size=150, overlap=20, prefix="none").chunk(document)

    row_chunks = [chunk for chunk in chunks if "ligne" in chunk.text]
    assert len(row_chunks) > 2
    for chunk in row_chunks:
        assert len(chunk.text) <= 150
        assert chunk.text.startswith("**Tarifs**\n\n| Col A | Col B |\n| --- | --- |")
        # Rows are never cut: every row line is complete.
        rows = [line for line in chunk.text.splitlines() if "ligne" in line]
        assert all(line.startswith("| ligne") and line.endswith("b |") for line in rows)
    covered = {line for chunk in row_chunks for line in chunk.text.splitlines()}
    assert {f"| ligne {i} a | ligne {i} b |" for i in range(12)} <= covered


def test_table_row_longer_than_a_chunk_is_split_with_its_header() -> None:
    long_row = f"| {words('cellule', 40)} | court |"
    document = make_document(f"# T\n\n**Tarifs**\n\n| Col A | Col B |\n| --- | --- |\n{long_row}")

    chunks = HeaderChunker(max_size=150, overlap=20, prefix="none").chunk(document)

    row_chunks = [chunk for chunk in chunks if "cellule" in chunk.text]
    assert len(row_chunks) > 1
    for chunk in row_chunks:
        assert len(chunk.text) <= 150
        assert chunk.text.startswith("**Tarifs**\n\n| Col A | Col B |")
    covered = {word for chunk in row_chunks for word in chunk.text.split()}
    assert set(words("cellule", 40).split()) <= covered


def test_mixed_document_is_fully_covered_in_order_with_deterministic_ids() -> None:
    text = "\n\n".join(
        [
            "# T",
            "Intro de la fiche.",
            "## Logement vide",
            words("vide", 30),
            "### Cas : Paris",
            words("paris", 25),
            "#### Cas : Couple",
            words("couple", 10),
            "### Cas : Cas général",
            table(rows=8),
            "## Logement meublé",
            "> **Attention**\n>\n> " + words("attention", 12),
        ]
    )
    document = make_document(text)
    chunker = HeaderChunker(max_size=160, overlap=20)

    chunks = chunker.chunk(document)

    assert chunker.chunk(document) == chunks
    assert [chunk.chunk_id for chunk in chunks] == [
        f"F1:headers:{i:04d}" for i in range(len(chunks))
    ]
    assert [chunk.start_char for chunk in chunks] == sorted(chunk.start_char for chunk in chunks)
    assert all(chunk.end_char - chunk.start_char <= 160 for chunk in chunks)
    covered = {word for chunk in chunks for word in chunk.text.split()}
    assert set(text.split()) <= covered
    # Chunks under a case say which case they belong to.
    paris = [chunk for chunk in chunks if "paris3" in chunk.text.split()]
    assert paris
    assert all("Cas : Paris" in chunk.text for chunk in paris)


def test_heading_tree_handles_skipped_levels_and_ignores_non_headings() -> None:
    text = "# T\n\n### Sous-section\n\n#hashtag pas un titre\n\n## A\n\nTexte."

    root = parse_sections(text)

    (title,) = root.children
    assert [child.title for child in title.children] == ["Sous-section", "A"]
    assert title.children[0].end == text.index("## A")
    assert title.children[1].children == []


@pytest.mark.parametrize(("max_size", "overlap"), [(0, 0), (100, 100), (100, -1)])
def test_invalid_sizes_are_rejected(max_size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        HeaderChunker(max_size=max_size, overlap=overlap)
