"""Score a saved generation run with the LLM judge and save the judge run.

Metrics: faithfulness, citation accuracy, citation precision, correctness (see
src/rag/evaluation/judge_eval.py). The judge reads the answers and contexts stored
in the generation run, so nothing is regenerated.

Cost (paid plan, Mistral Large 3 as judge): about $0.10-0.15 for the 30 dev
questions; the exact cost is computed from the measured token usage and printed.

Usage:
    uv run python scripts/judge_generation.py experiments/<generation run>.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from rag.config import get_settings
from rag.costs import cost_usd
from rag.evaluation.experiment import make_run_info, write_run
from rag.evaluation.generation_eval import QuestionGeneration
from rag.evaluation.golden_set import load_golden_set
from rag.evaluation.grouping import OVERALL
from rag.evaluation.judge import Judge
from rag.evaluation.judge_eval import JudgeSummary, judge_run, summarize_by_group
from rag.generation.llm import MistralLLM
from rag.provenance import file_sha256

RUN_KIND = "judge"
COLUMNS = ("n", "err", "faithful", "cit_acc", "cit_prec", "correct")


def _fmt(value: float | None, width: int = 10) -> str:
    return f"{'–':>{width}}" if value is None else f"{value:>{width}.2f}"


def print_report(summaries: dict[str, JudgeSummary]) -> None:
    print(f"\n{'group':<24}" + "".join(f"{column:>10}" for column in COLUMNS))
    ordered = [OVERALL] + sorted(name for name in summaries if name != OVERALL)
    for name in ordered:
        s = summaries[name]
        print(
            f"{name:<24}{s.n_questions:>10}{s.n_errors:>10}{_fmt(s.faithfulness)}"
            f"{_fmt(s.citation_accuracy)}{_fmt(s.citation_precision)}{_fmt(s.correctness)}"
        )
    overall = summaries[OVERALL]
    print(f"\nSentence verdicts: {overall.sentence_verdicts}")
    print(f"Key-fact verdicts: {overall.fact_verdicts}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("generation_run", type=Path, help="A generation run file in experiments/")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    settings = get_settings()
    generation_run = json.loads(args.generation_run.read_text(encoding="utf-8"))
    run = generation_run["run"]
    if run["kind"] != "generation":
        print(
            f"{args.generation_run} is a {run['kind']} run, not a generation run", file=sys.stderr
        )
        return 1
    golden = load_golden_set(settings.golden_set_path)
    if file_sha256(settings.golden_set_path) != run["golden_set"]["sha256"]:
        print(
            "The golden set changed since this generation run: key facts may not match the "
            "answers. Re-run scripts/eval_generation.py first.",
            file=sys.stderr,
        )
        return 1
    generations = [QuestionGeneration.model_validate(r) for r in generation_run["results"]]
    items = {item.id: item for item in golden.questions}

    judge = Judge(MistralLLM.judge_from_settings(settings))
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    results = judge_run(judge, generations, items)
    duration_s = time.perf_counter() - started

    summaries = summarize_by_group(results)
    overall = summaries[OVERALL]
    cost = cost_usd(
        overall.prompt_tokens,
        overall.completion_tokens,
        settings.judge_input_usd_per_mtok,
        settings.judge_output_usd_per_mtok,
    )
    info = make_run_info(
        kind=RUN_KIND,
        label=f"{settings.judge_model}-on-{run['run_id'].split('-')[0]}",
        started_at=started_at,
        duration_s=duration_s,
        settings=settings,
        index=run["index"],
        golden=golden,
        golden_path=settings.golden_set_path,
        split=run["golden_set"]["split"],
        n_questions=len(generations),
    )
    path = write_run(
        settings.experiments_dir,
        info,
        {
            "generation_run": {
                "run_id": run["run_id"],
                "path": str(args.generation_run),
                "sha256": file_sha256(args.generation_run),
                "llm_model": generation_run.get("llm_model"),
            },
            "judge_model": settings.judge_model,
            "judge_cost_usd": cost,
            "summary": summaries,
            "results": results,
        },
    )

    print_report(summaries)
    print(
        f"\n{len(generations)} answers judged, {duration_s:.0f} s, {overall.judge_calls} judge "
        f"calls, {overall.prompt_tokens} prompt + {overall.completion_tokens} completion tokens, "
        f"judge cost ${cost:.4f}, commit {info.git_commit}"
    )
    if overall.n_errors:
        print(f"⚠ {overall.n_errors} question(s) not scored; see the run file.")
    if info.git_dirty:
        print("⚠ Uncommitted changes: the commit hash does not fully describe the code.")
    print(f"Run saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
