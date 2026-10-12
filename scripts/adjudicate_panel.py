"""Adjudicate judge validation items with a panel of annotators (no API call).

Inputs:
- the first annotator's labels on the whole sample (e.g. `….claude.md`);
- the reference judge run;
- one label file per panel annotator, on the adjudication items (disagreements between
  the first annotator and the judge, plus audited agreements).

Reports: panel agreement (Fleiss' kappa), majority label per item, judge ↔ panel and
first annotator ↔ panel agreement, the audit of agreements, the judge's agreement with
the final label set (panel majority where adjudicated, shared label elsewhere), and the
judge metrics recomputed with the final labels (citation metrics as lower/upper bounds,
since labels carry no supporting blocks).

Usage:
    uv run python scripts/adjudicate_panel.py data/judge_labels/<sample>.claude.md \\
        experiments/<judge run>.json data/judge_labels/<sample>.panel-*.md
"""

import argparse
import json
import sys
from pathlib import Path

from rag.evaluation.judge import FactVerdict, SupportVerdict
from rag.evaluation.judge_eval import QuestionJudgment, summarize
from rag.evaluation.judge_labels import (
    FACT_PREFIX,
    SENTENCE_PREFIX,
    agreement,
    binarize,
    fleiss_kappa,
    judge_verdicts,
    majority_label,
    parse_labels,
    relabel,
)

POSITIVE = {SENTENCE_PREFIX: SupportVerdict.SUPPORTED.value, FACT_PREFIX: FactVerdict.PRESENT.value}
TITLES = {SENTENCE_PREFIX: "sentences", FACT_PREFIX: "facts"}


def load_labels(path: Path) -> dict[str, str]:
    labels, problems = parse_labels(path.read_text(encoding="utf-8"))
    for problem in problems:
        print(f"{path.name}: {problem}", file=sys.stderr)
    return labels


def report(title: str, pairs: list[tuple[str, str]], kind: str) -> None:
    if not pairs:
        return
    full = agreement(pairs)
    binary = agreement(binarize(pairs, POSITIVE[kind]))

    def kappa(value: float | None) -> str:
        return "–" if value is None else f"{value:.2f}"

    print(
        f"  {title:<44} n={full.n:<3} all labels {full.agreement:.2f} (κ {kappa(full.kappa)})"
        f"   {POSITIVE[kind]} vs. not {binary.agreement:.2f} (κ {kappa(binary.kappa)})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("first_labels", type=Path)
    parser.add_argument("judge_run", type=Path)
    parser.add_argument("panel", type=Path, nargs="+")
    args = parser.parse_args()

    first = load_labels(args.first_labels)
    data = json.loads(args.judge_run.read_text(encoding="utf-8"))
    judgments = [QuestionJudgment.model_validate(r) for r in data["results"]]
    judge = judge_verdicts(judgments)
    panel = [load_labels(path) for path in args.panel]

    items = [k for k in panel[0] if all(k in p for p in panel) and k in first and k in judge]
    disagreements = [k for k in items if first[k] != judge[k]]
    audited = [k for k in items if first[k] == judge[k]]
    majority = {k: majority_label([p[k] for p in panel]) for k in items}
    decided = {k: m for k, m in majority.items() if m is not None}

    print(f"Panel: {len(panel)} annotators, {len(items)} items")
    print(f"  Fleiss κ, all items: {fleiss_kappa([[p[k] for p in panel] for k in items]):.2f}")
    for kind in (SENTENCE_PREFIX, FACT_PREFIX):
        group = [[p[k] for p in panel] for k in items if k.startswith(kind)]
        unanimous = sum(len(set(r)) == 1 for r in group)
        value = fleiss_kappa(group)
        print(
            f"  {TITLES[kind]}: Fleiss κ {'–' if value is None else f'{value:.2f}'}, "
            f"unanimous {unanimous}/{len(group)}"
        )
    print(f"  no majority: {[k for k, m in majority.items() if m is None]}")

    print("\nPer item (first annotator | judge | panel → majority)")
    for k in items:
        tag = "disagreement" if k in disagreements else "audit"
        votes = ", ".join(p[k] for p in panel)
        print(f"  {k:<12} {tag:<12} {first[k]:<12} | {judge[k]:<12} | {votes} → {majority[k]}")

    sides = {"judge": 0, "first annotator": 0, "neither": 0, "no majority": 0}
    for k in disagreements:
        m = majority[k]
        side = (
            "no majority"
            if m is None
            else "judge"
            if m == judge[k]
            else "first annotator"
            if m == first[k]
            else "neither"
        )
        sides[side] += 1
    print(f"\nDisagreements ({len(disagreements)}): panel majority sides with {sides}")
    overturned = [k for k in audited if majority[k] is not None and majority[k] != judge[k]]
    print(f"Audit ({len(audited)} agreements): panel majority overturns {overturned or 'none'}")

    print("\nAgreement with the panel majority, adjudicated items")
    for kind in (SENTENCE_PREFIX, FACT_PREFIX):
        keys = [k for k in decided if k.startswith(kind)]
        report(f"judge, {TITLES[kind]}", [(decided[k], judge[k]) for k in keys], kind)
        report(f"first annotator, {TITLES[kind]}", [(decided[k], first[k]) for k in keys], kind)

    final = {k: v for k, v in first.items() if k in judge and v == judge[k]} | decided
    print(f"\nJudge vs. final label set ({len(final)} items; undecided items dropped)")
    for kind in (SENTENCE_PREFIX, FACT_PREFIX):
        keys = [k for k in final if k.startswith(kind)]
        report(f"judge, {TITLES[kind]}", [(final[k], judge[k]) for k in keys], kind)

    print("\nJudge metrics, all questions of the run (verdicts outside the sample unchanged)")
    rows = {
        "judge": summarize(judgments),
        "final labels, lower bound": summarize(
            relabel(judgments, final, newly_supported_cite_correctly=False)
        ),
        "final labels, upper bound": summarize(
            relabel(judgments, final, newly_supported_cite_correctly=True)
        ),
    }
    for name, s in rows.items():
        print(
            f"  {name:<28} faithfulness {s.faithfulness:.3f}  citation accuracy "
            f"{s.citation_accuracy:.3f}  citation precision {s.citation_precision:.3f}  "
            f"correctness {s.correctness:.3f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
