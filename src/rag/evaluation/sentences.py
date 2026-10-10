"""Split a generated answer into sentences, the unit the LLM judge scores.

Deterministic and free: every line (paragraph, list item, heading) is split at
sentence-ending punctuation followed by a capital letter. Each sentence keeps the
citation numbers it carries, since the generation prompt asks for a citation after
each factual sentence. A line holding only citation markers is attached to the
previous sentence; lines without any word (Markdown separators like "---") are
dropped. Limit: a sentence stating two facts gets a single verdict.
"""

import re

from pydantic import BaseModel

from rag.generation.citations import cited_numbers, strip_citations

_LIST_OR_HEADING_PREFIX = re.compile(r"^\s*(?:#+|[-*•]|\d+[.)])\s+")
# End of sentence: . ! ? (optionally followed by closing bold or quote), then a capital or opener.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])(?:\*\*|»|\")?\s+(?=[A-ZÀ-ÖØ-Þ«\"(*])")
_WORD = re.compile(r"\w")


class AnswerSentence(BaseModel):
    """One sentence of an answer: 1-based id, text with markers, and its cited numbers."""

    id: int
    text: str
    cited: list[int]

    @property
    def text_without_citations(self) -> str:
        return strip_citations(self.text)


def split_sentences(answer: str) -> list[AnswerSentence]:
    pieces: list[tuple[str, list[int]]] = []
    for line in answer.splitlines():
        content = _LIST_OR_HEADING_PREFIX.sub("", line).strip()
        for sentence in _SENTENCE_BOUNDARY.split(content):
            sentence = sentence.strip()
            cited = cited_numbers(sentence)
            if _WORD.search(strip_citations(sentence)):
                pieces.append((sentence, cited))
            elif cited and pieces:  # markers alone on their line belong to the previous sentence
                text, previous = pieces[-1]
                pieces[-1] = (
                    f"{text} {sentence}",
                    previous + [n for n in cited if n not in previous],
                )
    return [
        AnswerSentence(id=index, text=text, cited=cited)
        for index, (text, cited) in enumerate(pieces, start=1)
    ]
