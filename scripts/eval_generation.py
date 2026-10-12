"""Generate answers for the golden set with the RAG pipeline and save the run.

Reports LLM-free metrics (refusals, citation structure, tokens, cost). The saved run
contains every full answer and its context, to be scored later by the LLM judge.

Cost: one embedding and one generation call per question (paid plan: about $0.02
for the 30 dev questions with ministral-14b, ~3k prompt tokens each; the exact cost
is computed from the measured token usage and printed).

The test split is held out: tune on dev, run test only to report final numbers.

Usage:
    uv run python scripts/eval_generation.py                 # dev split
    uv run python scripts/eval_generation.py --split test
"""

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

from rag.chunking.factory import index_collection_name
from rag.config import get_settings
from rag.costs import cost_usd
from rag.evaluation.experiment import make_run_info, write_run
from rag.evaluation.generation_eval import (
    GenerationSummary,
    evaluate_generation,
    summarize_by_group,
)
from rag.evaluation.golden_set import Split, load_golden_set
from rag.evaluation.grouping import OVERALL
from rag.generation.llm import MistralLLM
from rag.indexing.chroma_store import ChromaStore
from rag.indexing.embedder import MistralEmbedder
from rag.pipeline import RAGPipeline
from rag.retrieval.dense import DenseRetriever

ALL_SPLITS = "all"
RUN_KIND = "generation"
COLUMNS = ("n", "err", "ref_acc", "ref_ok", "false_ref", "uncited", "invalid", "cites", "lat_ms")


def _fmt(value: float | None, width: int = 10, digits: int = 2) -> str:
    return f"{'–':>{width}}" if value is None else f"{value:>{width}.{digits}f}"


def print_report(summaries: dict[str, GenerationSummary]) -> None:
    print(f"\n{'group':<24}" + "".join(f"{column:>10}" for column in COLUMNS))
    ordered = [OVERALL] + sorted(name for name in summaries if name != OVERALL)
    for name in ordered:
        s = summaries[name]
        print(
            f"{name:<24}{s.n_questions:>10}{s.n_errors:>10}"
            f"{_fmt(s.refusal_accuracy)}{_fmt(s.correct_refusal_rate)}{_fmt(s.false_refusal_rate)}"
            f"{_fmt(s.uncited_answer_rate)}{_fmt(s.invalid_citation_rate)}{_fmt(s.mean_citations)}"
            f"{_fmt(s.mean_latency_ms, digits=0)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=[*(s.value for s in Split), ALL_SPLITS], default="dev")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    # One JSON line per query is useful in production, too verbose for a batch report.
    logging.getLogger("rag.pipeline").setLevel(logging.WARNING)

    settings = get_settings()
    golden = load_golden_set(settings.golden_set_path)
    items = golden.questions if args.split == ALL_SPLITS else golden.by_split(Split(args.split))

    name = index_collection_name(settings)
    store = ChromaStore(settings.chroma_dir, name)
    if store.count() == 0:
        print(f"Collection {name} is empty; run scripts/build_index.py", file=sys.stderr)
        return 1
    retriever = DenseRetriever(MistralEmbedder.from_settings(settings), store)
    pipeline = RAGPipeline(retriever, MistralLLM.from_settings(settings), settings.retrieval_top_k)

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    results = evaluate_generation(pipeline, items)
    duration_s = time.perf_counter() - started

    summaries = summarize_by_group(results)
    overall = summaries[OVERALL]
    cost = cost_usd(
        overall.prompt_tokens,
        overall.completion_tokens,
        settings.llm_input_usd_per_mtok,
        settings.llm_output_usd_per_mtok,
    )
    info = make_run_info(
        kind=RUN_KIND,
        label=f"{settings.llm_model}-{retriever.name}-{name}-{args.split}",
        started_at=started_at,
        duration_s=duration_s,
        settings=settings,
        index={"collection": name, "chunks": store.count(), **store.metadata},
        golden=golden,
        golden_path=settings.golden_set_path,
        split=args.split,
        n_questions=len(items),
    )
    path = write_run(
        settings.experiments_dir,
        info,
        {
            "retriever": retriever.name,
            "llm_model": settings.llm_model,
            "generation_cost_usd": cost,
            "summary": summaries,
            "results": results,
        },
    )

    print_report(summaries)
    print(
        f"\n{len(items)} questions ({args.split}), {duration_s:.0f} s, "
        f"{overall.prompt_tokens} prompt + {overall.completion_tokens} completion tokens, "
        f"generation cost ${cost:.4f}, commit {info.git_commit}"
    )
    if overall.n_errors:
        print(f"⚠ {overall.n_errors} question(s) failed; see the run file.")
    if info.git_dirty:
        print("⚠ Uncommitted changes: the commit hash does not fully describe the code.")
    print(f"Run saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
