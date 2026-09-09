"""Read-only git history queries for the open document.

The module is deliberately free of GTK so that it can be unit tested without a
display server, matching the arrangement already used by render.py.  Nothing
here writes to the repository or to the filesystem.

pygit2 is an optional dependency.  When it is missing the application must
behave exactly as it did before the history sidebar existed, so every entry
point is guarded by AVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import pygit2
    from pygit2.enums import DeltaStatus, FileStatus, SortMode

    AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where pygit2 is absent
    pygit2 = None
    DeltaStatus = FileStatus = SortMode = None
    AVAILABLE = False


# A walk is bounded by work rather than by a clock: running in-process there is
# no subprocess timeout to fall back on, and a scanned-revision ceiling is
# deterministic and testable.
MAX_SCAN = 2000


class GitHistoryError(RuntimeError):
    """An expected error while reading repository history."""


@dataclass(frozen=True)
class Commit:
    sha: str
    short_sha: str
    summary: str
    author: str
    when: datetime
    path: str


@dataclass(frozen=True)
class Cursor:
    """Where to resume a walk.

    The tracked path travels with the sha because a resumed walk continues
    below a rename, where older revisions carry a different name.
    """

    sha: str
    path: str


@dataclass(frozen=True)
class History:
    commits: list[Commit]
    truncated: bool
    next_cursor: Cursor | None


def find_repository(path: Path) -> "pygit2.Repository | None":
    """Return the repository containing path, or None when there is none."""

    if not AVAILABLE:
        return None
    try:
        discovered = pygit2.discover_repository(str(Path(path).parent))
    except pygit2.GitError:
        return None
    if discovered is None:
        return None
    try:
        repo = pygit2.Repository(discovered)
    except pygit2.GitError:
        return None
    # A bare repository has no working tree, so no document can live inside it.
    if repo.is_bare or repo.workdir is None:
        return None
    return repo


def _relative_path(repo, path: Path) -> str:
    """Return path as a repo-relative POSIX string."""

    workdir = Path(repo.workdir).resolve()
    try:
        relative = Path(path).resolve().relative_to(workdir)
    except ValueError as exc:
        raise GitHistoryError(
            f"{Path(path).name} is outside this repository"
        ) from exc
    return relative.as_posix()


def is_tracked(repo, path: Path) -> bool:
    """Report whether the file is in the index at all."""

    try:
        relative = _relative_path(repo, path)
    except GitHistoryError:
        return False
    return relative in repo.index
