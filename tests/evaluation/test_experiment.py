import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

from rag.config import Settings
from rag.evaluation import experiment
from rag.evaluation.experiment import RunInfo, make_run_id, make_run_info, write_run
from rag.evaluation.golden_set import GoldenItem, GoldenSet
from tests.evaluation.test_golden_set import lookup_item

STARTED_AT = datetime(2026, 10, 10, 14, 25, 1, tzinfo=UTC)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, mistral_api_key=SecretStr("secret-key"))  # type: ignore[call-arg]


@pytest.fixture
def golden_path(tmp_path: Path) -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text("corpus_snapshot: '2026-10-07'\nquestions: []\n", encoding="utf-8")
    return path


def make_info(settings: Settings, golden_path: Path, monkeypatch: pytest.MonkeyPatch) -> RunInfo:
    monkeypatch.setattr(experiment, "git_commit", lambda: "abc1234")
    monkeypatch.setattr(experiment, "git_is_dirty", lambda: False)
    golden = GoldenSet(
        corpus_snapshot="2026-10-07", questions=[GoldenItem.model_validate(lookup_item())]
    )
    return make_run_info(
        kind="retrieval",
        label="dense-test",
        started_at=STARTED_AT,
        duration_s=1.5,
        settings=settings,
        index={"collection": "test", "embedding_model": "fake"},
        golden=golden,
        golden_path=golden_path,
        split="dev",
        n_questions=1,
    )


def test_run_id_is_sortable_and_readable() -> None:
    assert make_run_id("retrieval", "dense-x", STARTED_AT) == "20261010T142501Z-retrieval-dense-x"


def test_run_info_records_provenance_without_secrets(
    settings: Settings, golden_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = make_info(settings, golden_path, monkeypatch)

    assert info.git_commit == "abc1234"
    assert info.git_dirty is False
    assert info.settings["chunk_size"] == 2000
    assert "mistral_api_key" not in info.settings
    assert len(info.golden_set.sha256) == 64
    assert info.golden_set.corpus_snapshot == "2026-10-07"


def test_write_run_saves_json_and_never_overwrites(
    settings: Settings, golden_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    info = make_info(settings, golden_path, monkeypatch)
    directory = tmp_path / "experiments"

    path = write_run(directory, info, {"summary": {"all": {"mrr": 0.5}}})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == f"{info.run_id}.json"
    assert data["run"]["git_commit"] == "abc1234"
    assert data["summary"]["all"]["mrr"] == 0.5
    assert "secret-key" not in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_run(directory, info, {})
