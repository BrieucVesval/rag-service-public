"""Experiment run records: one JSON file per run in experiments/, never overwritten.

A run file holds everything needed to trust and reproduce a number: the code
version (git commit, uncommitted changes), the full pipeline config (secrets
excluded), the index it queried (collection name and build metadata) and the
exact golden set file (SHA-256), next to the summary and per-question results.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from rag.config import Settings
from rag.evaluation.golden_set import GoldenSet
from rag.provenance import file_sha256, git_commit, git_is_dirty

SECRET_SETTINGS = frozenset({"mistral_api_key"})
RUN_ID_TIME_FORMAT = "%Y%m%dT%H%M%SZ"


class GoldenSetRef(BaseModel):
    path: str
    sha256: str
    corpus_snapshot: str
    split: str
    n_questions: int


class RunInfo(BaseModel):
    run_id: str
    kind: str
    started_at: datetime
    duration_s: float
    git_commit: str
    git_dirty: bool | None
    settings: dict[str, Any]
    index: dict[str, Any]
    golden_set: GoldenSetRef


def make_run_id(kind: str, label: str, started_at: datetime) -> str:
    """Sortable, readable ID, e.g. "20261010T142501Z-retrieval-fixed-2000-200-mistral-embed"."""
    return f"{started_at.astimezone(UTC).strftime(RUN_ID_TIME_FORMAT)}-{kind}-{label}"


def public_settings(settings: Settings) -> dict[str, Any]:
    return settings.model_dump(mode="json", exclude=set(SECRET_SETTINGS))


def make_run_info(
    *,
    kind: str,
    label: str,
    started_at: datetime,
    duration_s: float,
    settings: Settings,
    index: dict[str, Any],
    golden: GoldenSet,
    golden_path: Path,
    split: str,
    n_questions: int,
) -> RunInfo:
    return RunInfo(
        run_id=make_run_id(kind, label, started_at),
        kind=kind,
        started_at=started_at,
        duration_s=duration_s,
        git_commit=git_commit(),
        git_dirty=git_is_dirty(),
        settings=public_settings(settings),
        index=index,
        golden_set=GoldenSetRef(
            path=str(golden_path),
            sha256=file_sha256(golden_path),
            corpus_snapshot=golden.corpus_snapshot,
            split=split,
            n_questions=n_questions,
        ),
    )


def write_run(directory: Path, info: RunInfo, payload: dict[str, Any]) -> Path:
    """Write {"run": info, **payload} to <directory>/<run_id>.json; refuses to overwrite."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{info.run_id}.json"
    data = to_jsonable_python({"run": info, **payload})
    with path.open("x", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return path
