"""Golden set: the fixed exam every pipeline version is evaluated on.

Each question has a reference answer split into atomic `key_facts`, the fiches
that contain the answer (`expected_docs`, used for retrieval metrics without any
LLM) and verbatim `evidence` quotes. `check_against_corpus` verifies that every
quote really exists in the corpus, so reference answers cannot be invented.
"""

import re
from collections import Counter
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from rag.models import Document

_WHITESPACE = re.compile(r"\s+")


class Category(StrEnum):
    LOOKUP = "lookup"
    MULTI_HOP = "multi_hop"
    UNANSWERABLE = "unanswerable"
    AMBIGUOUS = "ambiguous"


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"


class Origin(StrEnum):
    HANDWRITTEN = "handwritten"
    DRAFTED_REVIEWED = "drafted_reviewed"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    quote: str


class GoldenItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    question: str
    category: Category
    split: Split
    expected_answer: str
    key_facts: list[str] = []
    expected_docs: list[str] = []
    evidence: list[Evidence] = []
    origin: Origin
    notes: str = ""

    @model_validator(mode="after")
    def _consistent_with_category(self) -> "GoldenItem":
        if self.category == Category.UNANSWERABLE:
            if self.expected_docs or self.evidence:
                raise ValueError(f"{self.id}: unanswerable questions have no docs or evidence")
            return self
        if not (self.key_facts and self.expected_docs and self.evidence):
            raise ValueError(f"{self.id}: key_facts, expected_docs and evidence are required")
        unknown = {item.doc_id for item in self.evidence} - set(self.expected_docs)
        if unknown:
            raise ValueError(f"{self.id}: evidence from docs not in expected_docs: {unknown}")
        return self


class GoldenSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_snapshot: str
    questions: list[GoldenItem]

    @model_validator(mode="after")
    def _unique_ids(self) -> "GoldenSet":
        duplicates = [i for i, n in Counter(q.id for q in self.questions).items() if n > 1]
        if duplicates:
            raise ValueError(f"Duplicate question ids: {duplicates}")
        return self

    def by_split(self, split: Split) -> list[GoldenItem]:
        return [question for question in self.questions if question.split == split]


def load_golden_set(path: Path) -> GoldenSet:
    return GoldenSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def check_against_corpus(golden: GoldenSet, documents: Mapping[str, Document]) -> list[str]:
    """Problems found: unknown fiches, or evidence quotes absent from the fiche text."""
    problems: list[str] = []
    for item in golden.questions:
        for doc_id in item.expected_docs:
            if doc_id not in documents:
                problems.append(f"{item.id}: expected doc {doc_id} not in corpus")
        for evidence in item.evidence:
            document = documents.get(evidence.doc_id)
            if document is not None and not quote_in_text(evidence.quote, document.text):
                problems.append(
                    f"{item.id}: quote not found in {evidence.doc_id}: {evidence.quote!r}"
                )
    return problems


def composition(golden: GoldenSet) -> Counter[tuple[str, str]]:
    """Number of questions per (category, split)."""
    return Counter((item.category.value, item.split.value) for item in golden.questions)


def normalize_text(text: str) -> str:
    """Whitespace-insensitive and case-insensitive matching, typographic apostrophes unified."""
    return _WHITESPACE.sub(" ", text.replace("’", "'")).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    """True if the quote appears in the text, ignoring whitespace, case and apostrophe style."""
    return normalize_text(quote) in normalize_text(text)


# French function words of 4+ letters, ignored when measuring lexical overlap.
_STOPWORDS = frozenset(
    {
        "alors",
        "aussi",
        "avant",
        "avec",
        "avoir",
        "cela",
        "cette",
        "chez",
        "combien",
        "comment",
        "dans",
        "depuis",
        "dois",
        "doit",
        "elle",
        "entre",
        "être",
        "faire",
        "faut",
        "leur",
        "leurs",
        "mais",
        "moins",
        "nous",
        "peut",
        "peux",
        "plus",
        "pour",
        "quand",
        "quel",
        "quelle",
        "quelles",
        "quels",
        "sans",
        "sont",
        "tous",
        "tout",
        "très",
        "votre",
        "vous",
    }
)
_MIN_WORD_LENGTH = 4
_WORD = re.compile(r"\w+")


def content_words(text: str) -> set[str]:
    """Lower-cased words of 4+ letters that are not French function words."""
    return {
        word
        for word in _WORD.findall(normalize_text(text))
        if len(word) >= _MIN_WORD_LENGTH and word not in _STOPWORDS
    }


def title_overlap(question: str, title: str) -> float:
    """Share of the question's content words that also appear in a fiche title.

    A high value means the question reuses the corpus wording, which makes retrieval
    artificially easy compared with real users' phrasing.
    """
    words = content_words(question)
    return len(words & content_words(title)) / len(words) if words else 0.0
