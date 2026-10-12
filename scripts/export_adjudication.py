"""Export the items a human must adjudicate after an LLM annotator labelled a sample.

Hybrid validation: an independent LLM (fresh, blind to the judge) labels the whole
sample; the human then labels, blind, every item where it disagrees with the judge
plus a random audit of agreements. Neither rater's label is shown. No API call.

Usage:
    uv run python scripts/export_adjudication.py data/judge_labels/<sample>.claude.md \
        experiments/<judge run>.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

from rag.evaluation.generation_eval import QuestionGeneration
from rag.evaluation.judge_eval import QuestionJudgment
from rag.evaluation.judge_labels import (
    LabelItem,
    adjudication_sample,
    judge_verdicts,
    parse_labels,
    render_label_file,
)

DEFAULT_AGREEMENT_AUDIT = 8
DEFAULT_SEED = 0
_KEY = re.compile(r"^### ([SF])-(q\d+)-(\d+)\s*$", re.MULTILINE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("llm_labels", type=Path, help="Sample labelled by the LLM annotator")
    parser.add_argument("judge_run", type=Path)
    parser.add_argument("--audit", type=int, default=DEFAULT_AGREEMENT_AUDIT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, help="Defaults to <sample>.human.md next to it")
    args = parser.parse_args()

    text = args.llm_labels.read_text(encoding="utf-8")
    llm, problems = parse_labels(text)
    if problems:
        print(f"LLM labels incomplete: {problems}", file=sys.stderr)
        return 1
    items = [
        LabelItem(kind=kind, question_id=question_id, item_id=int(item_id))
        for kind, question_id, item_id in _KEY.findall(text)
    ]
    data = json.loads(args.judge_run.read_text(encoding="utf-8"))
    judgments = [QuestionJudgment.model_validate(r) for r in data["results"]]
    judge = judge_verdicts(judgments)
    generations = json.loads(Path(data["generation_run"]["path"]).read_text(encoding="utf-8"))
    answers = {
        g.question_id: g.answer
        for g in (QuestionGeneration.model_validate(r) for r in generations["results"])
        if g.answer is not None
    }

    selected = adjudication_sample(items, llm, judge, args.audit, args.seed)
    n_disagreements = sum(llm[i.key] != judge[i.key] for i in selected)
    out = args.out or args.llm_labels.with_name(
        args.llm_labels.name.replace(".claude.md", ".human.md")
    )
    if out.exists():
        print(f"{out} exists; labels are never overwritten", file=sys.stderr)
        return 1
    header = (
        f"# Judge validation: human adjudication\n\n"
        f"- LLM annotator labels: `{args.llm_labels}`\n"
        f"- Judge run: `{args.judge_run}`\n"
        f"- Items: {len(selected)} ({n_disagreements} disagreements and "
        f"{len(selected) - n_disagreements} random agreements, seed {args.seed}), in question "
        f"order, not marked: neither rater's label is shown"
    )
    out.write_text(
        render_label_file(selected, {j.question_id: j for j in judgments}, answers, header),
        encoding="utf-8",
    )
    print(f"{len(selected)} items ({n_disagreements} disagreements) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
