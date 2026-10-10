from rag.generation.citations import cited_numbers, resolve_citations
from rag.models import RetrievedChunk


def test_cited_numbers_handles_single_grouped_and_repeated_markers() -> None:
    text = "Le préavis est d'un mois [2]. En zone tendue [1, 3][2]. Voir aussi [1,3]."

    assert cited_numbers(text) == [2, 1, 3]


def test_cited_numbers_ignores_non_numeric_brackets() -> None:
    assert cited_numbers("Voir [ici] et [a1] ou [ 1 ]") == []


def test_resolve_citations_maps_numbers_to_chunks(retrieved: list[RetrievedChunk]) -> None:
    citations, invalid = resolve_citations("Réponse [3] puis [1].", retrieved)

    assert [(c.number, c.chunk_id, c.doc_id) for c in citations] == [
        (3, "F2:fixed:0002", "F2"),
        (1, "F1:fixed:0000", "F1"),
    ]
    assert citations[0].url == "https://example.org/F2"
    assert invalid == []


def test_resolve_citations_flags_numbers_outside_context(
    retrieved: list[RetrievedChunk],
) -> None:
    citations, invalid = resolve_citations("Réponse [0], [2] et [7].", retrieved)

    assert [c.number for c in citations] == [2]
    assert invalid == [0, 7]


def test_strip_citations_keeps_french_spacing() -> None:
    from rag.generation.citations import strip_citations

    assert strip_citations("Trois mois [1][2], sauf exception [3] : voir [4, 5].") == (
        "Trois mois, sauf exception : voir."
    )
