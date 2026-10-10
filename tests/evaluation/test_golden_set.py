from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rag.evaluation.golden_set import (
    GoldenItem,
    GoldenSet,
    Split,
    check_against_corpus,
    composition,
    content_words,
    load_golden_set,
    title_overlap,
)
from rag.models import Document


def lookup_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "q001",
        "question": "Combien de temps de préavis pour un logement vide ?",
        "category": "lookup",
        "split": "dev",
        "expected_answer": "3 mois.",
        "key_facts": ["3 mois"],
        "expected_docs": ["F1"],
        "evidence": [{"doc_id": "F1", "quote": "le délai de préavis est de 3 mois"}],
        "origin": "drafted_reviewed",
    }
    item.update(overrides)
    return item


def unanswerable_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "q002",
        "question": "Combien coûte un passeport ?",
        "category": "unanswerable",
        "split": "test",
        "expected_answer": "Refus : hors du corpus.",
        "origin": "drafted_reviewed",
    }
    item.update(overrides)
    return item


CORPUS = {
    "F1": Document(
        doc_id="F1",
        source="test",
        title="Préavis",
        text="# Préavis\n\nEn principe, le  délai de\npréavis est de 3 mois’ici.",
    )
}


def test_valid_items_are_accepted() -> None:
    golden = GoldenSet(corpus_snapshot="2026-10-07", questions=[lookup_item(), unanswerable_item()])

    assert [q.category for q in golden.questions] == ["lookup", "unanswerable"]
    assert [q.id for q in golden.by_split(Split.TEST)] == ["q002"]
    assert composition(golden)[("lookup", "dev")] == 1


@pytest.mark.parametrize("missing", ["key_facts", "expected_docs", "evidence"])
def test_answerable_question_requires_facts_docs_and_evidence(missing: str) -> None:
    with pytest.raises(ValidationError, match="required"):
        GoldenItem.model_validate(lookup_item(**{missing: []}))


def test_unanswerable_question_has_no_docs() -> None:
    with pytest.raises(ValidationError, match="no docs or evidence"):
        GoldenItem.model_validate(unanswerable_item(expected_docs=["F1"]))


def test_evidence_must_come_from_expected_docs() -> None:
    with pytest.raises(ValidationError, match="not in expected_docs"):
        GoldenItem.model_validate(lookup_item(evidence=[{"doc_id": "F9", "quote": "x"}]))


def test_unknown_field_and_category_are_rejected() -> None:
    with pytest.raises(ValidationError):
        GoldenItem.model_validate(lookup_item(typo_field="x"))
    with pytest.raises(ValidationError):
        GoldenItem.model_validate(lookup_item(category="easy"))


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate"):
        GoldenSet(corpus_snapshot="x", questions=[lookup_item(), lookup_item()])


def test_quotes_match_ignoring_whitespace_case_and_apostrophes() -> None:
    golden = GoldenSet(
        corpus_snapshot="x",
        questions=[
            lookup_item(
                evidence=[{"doc_id": "F1", "quote": "Le délai de préavis est de 3 mois'ici"}]
            )
        ],
    )

    assert check_against_corpus(golden, CORPUS) == []


def test_missing_doc_and_invented_quote_are_reported() -> None:
    golden = GoldenSet(
        corpus_snapshot="x",
        questions=[
            lookup_item(
                expected_docs=["F1", "F404"],
                evidence=[{"doc_id": "F1", "quote": "le délai de préavis est de 2 mois"}],
            )
        ],
    )

    problems = check_against_corpus(golden, CORPUS)

    assert problems == [
        "q001: expected doc F404 not in corpus",
        "q001: quote not found in F1: 'le délai de préavis est de 2 mois'",
    ]


def test_load_golden_set_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "golden.yaml"
    path.write_text(
        """
corpus_snapshot: "2026-10-07T16:35:15+00:00"
questions:
  - id: q001
    question: "Combien coûte un passeport ?"
    category: unanswerable
    split: dev
    expected_answer: "Refus."
    origin: handwritten
""",
        encoding="utf-8",
    )

    golden = load_golden_set(path)

    assert golden.corpus_snapshot == "2026-10-07T16:35:15+00:00"
    assert golden.questions[0].origin == "handwritten"


def test_content_words_ignore_short_and_function_words() -> None:
    assert content_words("Combien de temps pour le préavis d'un Logement ?") == {
        "temps",
        "préavis",
        "logement",
    }


def test_title_overlap_is_share_of_question_words_in_title() -> None:
    title = "Préavis et formalités du congé donné par le locataire"

    assert title_overlap("Quel préavis pour un locataire ?", title) == 1.0
    assert title_overlap("Je veux partir de mon appart, je préviens quand ?", title) == 0.0
    assert title_overlap("?", title) == 0.0
