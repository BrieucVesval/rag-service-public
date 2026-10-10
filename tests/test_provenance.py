import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from rag import provenance


def test_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_bytes(b"golden")

    assert provenance.file_sha256(path) == hashlib.sha256(b"golden").hexdigest()


def test_git_outputs_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = {"rev-parse": "abc1234\n", "status": " M src/rag/config.py\n"}

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=outputs[args[1]])

    monkeypatch.setattr(provenance.subprocess, "run", fake_run)

    assert provenance.git_commit() == "abc1234"
    assert provenance.git_is_dirty() is True


def test_git_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: Any, **__: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("git not found")

    monkeypatch.setattr(provenance.subprocess, "run", fake_run)

    assert provenance.git_commit() == provenance.UNKNOWN
    assert provenance.git_is_dirty() is None
