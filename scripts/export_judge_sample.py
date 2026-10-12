"""Export a blind, stratified sample of judge verdicts for human labelling.

The output Markdown file lists sentences and reference facts grouped by question,
with the sources and answer folded, and an empty `- Label:` line per item. The
judge's verdicts are not included. Fill it in, then run scripts/judge_agreement.py.

No API call. The sample is deterministic for a given seed.

Usage:
    uv run python scripts/export_judge_sample.py experiments/<judge run>.json \
        --compare experiments/<other judge run on the same answers>.json
"""

import argparse
import json
import sys
from pathlib import Path

from rag.evaluation.generation_eval import QuestionGeneration
from rag.evaluation.judge_eval import QuestionJudgment
from rag.evaluation.judge_labels import (
    FACT_PREFIX,
    SENTENCE_PREFIX,
    render_label_file,
    select_sample,
)

LABELS_DIR = Path("data/judge_labels")
DEFAULT_RANDOM_SUPPORTED = 10
DEFAULT_RANDOM_PRESENT = 5
DEFAULT_SEED = 0


def load_judgments(path: Path) -> tuple[dict, list[QuestionJudgment]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["run"]["kind"] != "judge":
        raise SystemExit(f"{path} is a {data['run']['kind']} run, not a judge run")
    return data, [QuestionJudgment.model_validate(r) for r in data["results"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("judge_run", type=Path)
    parser.add_argument("--compare", type=Path, help="Another judge run on the same answers")
    parser.add_argument("--random-supported", type=int, default=DEFAULT_RANDOM_SUPPORTED)
    parser.add_argument("--random-present", type=int, default=DEFAULT_RANDOM_PRESENT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, help=f"Defaults to {LABELS_DIR}/<judge run id>.md")
    args = parser.parse_args()

    data, reference = load_judgments(args.judge_run)
    other = None
    if args.compare:
        other_data, other = load_judgments(args.compare)
        if other_data["generation_run"]["sha256"] != data["generation_run"]["sha256"]:
            print("The two judge runs scored different generation runs", file=sys.stderr)
            return 1
    generation_path = Path(data["generation_run"]["path"])
    generations = [
        QuestionGeneration.model_validate(r)
        for r in json.loads(generation_path.read_text(encoding="utf-8"))["results"]
    ]
    answers = {g.question_id: g.answer for g in generations if g.answer is not None}

    items = select_sample(reference, other, args.random_supported, args.random_present, args.seed)
    out = args.out or LABELS_DIR / f"{data['run']['run_id']}.md"
    if out.exists():
        print(f"{out} exists; labels are never overwritten", file=sys.stderr)
        return 1
    header = (
        f"# Judge validation labels\n\n"
        f"- Judge run: `{args.judge_run}`\n"
        f"- Compared run: `{args.compare or 'none'}`\n"
        f"- Generation run: `{generation_path}`\n"
        f"- Sample: seed {args.seed}, {args.random_supported} random supported sentences, "
        f"{args.random_present} random present facts"
    )
    judgments = {j.question_id: j for j in reference}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_label_file(items, judgments, answers, header), encoding="utf-8")

    n_sentences = sum(item.kind == SENTENCE_PREFIX for item in items)
    n_facts = sum(item.kind == FACT_PREFIX for item in items)
    n_questions = len({item.question_id for item in items})
    print(f"{n_sentences} sentences and {n_facts} facts from {n_questions} questions -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
