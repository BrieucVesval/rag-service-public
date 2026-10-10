"""Provenance of a build or an experiment run: code version and input fingerprints.

A result is only reproducible if we know which code produced it (git commit, and
whether uncommitted changes were present) and which inputs it read (file hashes).
"""

import hashlib
import subprocess
from pathlib import Path

UNKNOWN = "unknown"


def git_commit() -> str:
    """Short hash of HEAD, or "unknown" outside a git checkout."""
    output = _git("rev-parse", "--short", "HEAD")
    return output.strip() if output is not None else UNKNOWN


def git_is_dirty() -> bool | None:
    """True if tracked files have uncommitted changes, None if git is unavailable."""
    output = _git("status", "--porcelain", "--untracked-files=no")
    return bool(output.strip()) if output is not None else None


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout
