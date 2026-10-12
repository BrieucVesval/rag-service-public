from rag.evaluation.sentences import split_sentences


def test_splits_paragraphs_lists_and_sentences_keeping_citations() -> None:
    answer = (
        "Le préavis est de 3 mois [1]. En zone tendue, il est de 1 mois [2].\n\n"
        "**Cas particuliers** :\n"
        "- Mutation professionnelle [3]\n"
        "1. Perte d'emploi [3][4]"
    )

    sentences = split_sentences(answer)

    assert [(s.id, s.text_without_citations, s.cited) for s in sentences] == [
        (1, "Le préavis est de 3 mois.", [1]),
        (2, "En zone tendue, il est de 1 mois.", [2]),
        (3, "**Cas particuliers** :", []),
        (4, "Mutation professionnelle", [3]),
        (5, "Perte d'emploi", [3, 4]),
    ]


def test_markers_alone_on_a_line_join_the_previous_sentence() -> None:
    sentences = split_sentences("Le dépôt est de 1 mois de loyer.\n[2][3]")

    assert len(sentences) == 1
    assert sentences[0].cited == [2, 3]


def test_separators_and_empty_lines_are_dropped() -> None:
    sentences = split_sentences("Première phrase [1].\n\n---\n\nSeconde phrase [2].")

    assert [s.text_without_citations for s in sentences] == ["Première phrase.", "Seconde phrase."]


def test_no_split_on_lowercase_after_period_or_on_citation() -> None:
    sentences = split_sentences("Voir l'art. 25 de la loi [1]. Le vote a lieu en AG [2].")

    assert [s.cited for s in sentences] == [[1], [2]]
