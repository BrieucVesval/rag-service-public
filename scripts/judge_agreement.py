"""Agreement between human labels and one or more judge runs (no API call).

Reports, for sentences and for reference facts: raw agreement, Cohen's kappa and the
confusion matrix, on all labels and on the binary decision used by the metric
(supported vs. not for faithfulness, present vs. not for correctness).

Usage:
    uv run python scripts/judge_agreement.py data/judge_labels/<file>.md \
        experiments/<judge run>.json [experiments/<other judge run>.json ...]
"""

import argparse
import json
import sys
from pathlib import Path

from rag.evaluation.judge import FactVerdict, SupportVerdict
from rag.evaluation.judge_eval import QuestionJudgment
from rag.evaluation.judge_labels import (
    FACT_PREFIX,
    SENTENCE_PREFIX,
    Agreement,
    agreement,
    binarize,
    judge_verdicts,
    parse_labels,
)


def load_verdicts(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return judge_verdicts(QuestionJudgment.model_validate(r) for r in data["results"])


def print_agreement(title: str, result: Agreement) -> None:
    kappa = "–" if result.kappa is None else f"{result.kappa:.2f}"
    print(f"  {title:<34} n={result.n:<3} agreement {result.agreement:.2f}  kappa {kappa}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("labels", type=Path)
    parser.add_argument("judge_runs", type=Path, nargs="+")
    args = parser.parse_args()

    human, problems = parse_labels(args.labels.read_text(encoding="utf-8"))
    if problems:
        print(f"{len(problems)} item(s) not usable:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
    if not human:
        return 1

    for run in args.judge_runs:
        judge = load_verdicts(run)
        print(f"\n{run.name}")
        for kind, positive, title in (
            (SENTENCE_PREFIX, SupportVerdict.SUPPORTED.value, "sentences"),
            (FACT_PREFIX, FactVerdict.PRESENT.value, "reference facts"),
        ):
            pairs = [(h, judge[k]) for k, h in human.items() if k.startswith(kind) and k in judge]
            if not pairs:
                continue
            all_labels = agreement(pairs)
            print_agreement(f"{title}, all labels", all_labels)
            print_agreement(f"{title}, {positive} vs. not", agreement(binarize(pairs, positive)))
            print(f"    confusion (human -> judge): {all_labels.confusion}")
            disagreements = [
                k for k, h in human.items() if k.startswith(kind) and k in judge and judge[k] != h
            ]
            print(f"    disagreements: {disagreements}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
