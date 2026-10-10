"""Evaluate retrieval on the golden set (Recall@k, MRR, evidence recall) and save the run.

Only the question embeddings are API calls (one per question, free plan: ~1 min for
50 questions). The run is written to experiments/<run_id>.json with its config,
git commit, index metadata and golden set hash.

The test split is held out: tune on dev, run test only to report final numbers.

Usage:
    uv run python scripts/eval_retrieval.py                 # dev split
    uv run python scripts/eval_retrieval.py --split test
    uv run python scripts/eval_retrieval.py --split all
"""

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

from rag.chunking.fixed import FixedSizeChunker
from rag.config import get_settings
from rag.evaluation.experiment import make_run_info, write_run
from rag.evaluation.golden_set import Split, load_golden_set
from rag.evaluation.retrieval_eval import (
    OVERALL,
    RetrievalSummary,
    evaluate_retrieval,
    summarize_by_group,
)
from rag.indexing.chroma_store import ChromaStore, collection_name
from rag.indexing.embedder import MistralEmbedder
from rag.retrieval.dense import DenseRetriever

ALL_SPLITS = "all"
RUN_KIND = "retrieval"


def format_row(name: str, summary: RetrievalSummary, k_values: list[int], headline_k: int) -> str:
    recalls = " ".join(f"{summary.recall_at.get(k, float('nan')):>6.2f}" for k in k_values)
    all_found = summary.all_found_at.get(headline_k, float("nan"))
    evidence = summary.evidence_recall_at.get(headline_k, float("nan"))
    mrr = summary.mrr if summary.mrr is not None else float("nan")
    top = summary.mean_top_score if summary.mean_top_score is not None else float("nan")
    return (
        f"{name:<24}{summary.n_questions:>4}{summary.n_answerable:>4} {recalls} "
        f"{all_found:>7.2f}{evidence:>8.2f}{mrr:>7.2f}{top:>8.3f}"
    )


def print_report(
    summaries: dict[str, RetrievalSummary], k_values: list[int], headline_k: int
) -> None:
    recall_headers = " ".join(f"{'R@' + str(k):>6}" for k in k_values)
    print(
        f"\n{'group':<24}{'n':>4}{'ans':>4} {recall_headers} "
        f"{'All@' + str(headline_k):>7}{'Evid@' + str(headline_k):>8}{'MRR':>7}{'top_sim':>8}"
    )
    ordered = [OVERALL] + sorted(name for name in summaries if name != OVERALL)
    for name in ordered:
        print(format_row(name, summaries[name], k_values, headline_k))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=[*(s.value for s in Split), ALL_SPLITS], default="dev")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    settings = get_settings()
    golden = load_golden_set(settings.golden_set_path)
    items = golden.questions if args.split == ALL_SPLITS else golden.by_split(Split(args.split))

    name = collection_name(
        FixedSizeChunker.name, settings.chunk_size, settings.chunk_overlap, settings.embedding_model
    )
    store = ChromaStore(settings.chroma_dir, name)
    if store.count() == 0:
        print(f"Collection {name} is empty; run scripts/build_index.py", file=sys.stderr)
        return 1
    retriever = DenseRetriever(MistralEmbedder.from_settings(settings), store)

    started_at = datetime.now(UTC)
    started = time.perf_counter()
    results = evaluate_retrieval(retriever, items, settings.eval_k_values)
    duration_s = time.perf_counter() - started

    summaries = summarize_by_group(results)
    info = make_run_info(
        kind=RUN_KIND,
        label=f"{retriever.name}-{name}-{args.split}",
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
        {"retriever": retriever.name, "summary": summaries, "results": results},
    )

    print_report(summaries, settings.eval_k_values, settings.retrieval_top_k)
    print(f"\n{len(items)} questions ({args.split}), {duration_s:.0f} s, commit {info.git_commit}")
    if info.git_dirty:
        print("⚠ Uncommitted changes: the commit hash does not fully describe the code.")
    print(f"Run saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
