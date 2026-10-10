"""Validate the golden set against the processed corpus and print its composition.

Checks: schema (via pydantic), unique ids, expected fiches exist, every evidence
quote appears verbatim (whitespace/case-insensitive) in its fiche, and the corpus
snapshot matches the processed data.

Usage:
    uv run python scripts/validate_golden_set.py
"""

import argparse
import json
import sys
from pathlib import Path

from rag.config import get_settings
from rag.evaluation.golden_set import (
    Category,
    GoldenSet,
    Split,
    check_against_corpus,
    composition,
    load_golden_set,
    title_overlap,
)
from rag.ingestion.processed import MANIFEST_NAME, load_processed_documents
from rag.models import Document

DEFAULT_PATH = Path("data/golden_set/golden_set.yaml")
# Questions sharing more than this share of content words with a fiche title are listed.
HIGH_TITLE_OVERLAP = 0.5
SUBTHEME_LEVEL = 2  # breadcrumb: Accueil > Logement > sub-theme > ...


def print_bias_report(golden: GoldenSet, documents: dict[str, Document]) -> None:
    """Lexical overlap with fiche titles and sub-theme coverage (reported, not enforced)."""
    overlaps = {
        item.id: max(title_overlap(item.question, documents[d].title) for d in item.expected_docs)
        for item in golden.questions
        if item.expected_docs and all(d in documents for d in item.expected_docs)
    }
    if overlaps:
        mean = sum(overlaps.values()) / len(overlaps)
        high = sorted(qid for qid, value in overlaps.items() if value > HIGH_TITLE_OVERLAP)
        print(
            f"\nTitle overlap (answerable questions): mean {mean:.2f}, "
            f"max {max(overlaps.values()):.2f}"
        )
        print(f"Above {HIGH_TITLE_OVERLAP}: {high or 'none'}")

    subthemes = {
        documents[d].breadcrumb[SUBTHEME_LEVEL]
        for item in golden.questions
        for d in item.expected_docs
        if d in documents and len(documents[d].breadcrumb) > SUBTHEME_LEVEL + 1
    }
    all_subthemes = {
        doc.breadcrumb[SUBTHEME_LEVEL]
        for doc in documents.values()
        if len(doc.breadcrumb) > SUBTHEME_LEVEL + 1
    }
    print(f"Sub-themes covered: {len(subthemes)}/{len(all_subthemes)}")
    missing = sorted(all_subthemes - subthemes)
    if missing:
        print(f"Not covered: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    settings = get_settings()
    golden = load_golden_set(args.path)
    documents = {doc.doc_id: doc for doc in load_processed_documents(settings.processed_dir)}
    problems = check_against_corpus(golden, documents)

    manifest_path = settings.processed_dir / MANIFEST_NAME
    if manifest_path.exists():
        raw_snapshot = json.loads(manifest_path.read_text()).get("raw_downloaded_at")
        if raw_snapshot != golden.corpus_snapshot:
            problems.append(
                f"corpus_snapshot {golden.corpus_snapshot} differs from processed data "
                f"{raw_snapshot}: reference answers may be stale"
            )

    counts = composition(golden)
    print(f"{len(golden.questions)} questions ({args.path})")
    print(f"{'category':<14}{'dev':>5}{'test':>6}{'total':>7}")
    for category in Category:
        dev, test = counts[(category, Split.DEV)], counts[(category, Split.TEST)]
        print(f"{category.value:<14}{dev:>5}{test:>6}{dev + test:>7}")
    print_bias_report(golden, documents)

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
