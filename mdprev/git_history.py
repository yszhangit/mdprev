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
from datetime import datetime, timedelta, timezone
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


def _entry(tree, relpath: str):
    """Return the blob at relpath within tree, or None when absent.

    Path segments are walked explicitly so that nested paths behave the same
    way across pygit2 versions.
    """

    node = tree
    for part in relpath.split("/"):
        if not isinstance(node, pygit2.Tree):
            return None
        try:
            node = node[part]
        except KeyError:
            return None
    return node if isinstance(node, pygit2.Blob) else None


def _commit_record(commit, path: str) -> Commit:
    author = commit.author
    when = datetime.fromtimestamp(
        author.time, tz=timezone(timedelta(minutes=author.offset))
    )
    message = commit.message.strip()
    summary = message.splitlines()[0] if message else ""
    sha = str(commit.id)
    return Commit(
        sha=sha,
        short_sha=sha[:7],
        summary=summary,
        author=author.name,
        when=when,
        path=path,
    )


def history(repo, path: Path, limit: int = 10, after: Cursor | None = None) -> History:
    """Return commits touching path, newest first.

    A commit touches the file when the blob recorded at the tracked path
    differs from the one recorded in its first parent.  Merge commits are
    compared against their first parent only, matching git log --follow.
    """

    if repo.head_is_unborn:
        return History(commits=[], truncated=False, next_cursor=None)
    tracked = after.path if after is not None else _relative_path(repo, path)
    skipping = after.sha if after is not None else None

    commits: list[Commit] = []
    scanned = 0
    truncated = False
    next_cursor: Cursor | None = None
    last_seen: str | None = None

    for commit in repo.walk(repo.head.target, SortMode.TOPOLOGICAL | SortMode.TIME):
        if skipping is not None:
            # Revisions above the cursor were reported by an earlier call.
            if str(commit.id) == skipping:
                skipping = None
            continue
        if scanned >= MAX_SCAN:
            # Resume below the last revision actually examined, so that the
            # revision which tripped the ceiling is not skipped.
            truncated = True
            if last_seen is not None:
                next_cursor = Cursor(sha=last_seen, path=tracked)
            break
        scanned += 1
        last_seen = str(commit.id)

        entry = _entry(commit.tree, tracked)
        parent = commit.parents[0] if commit.parents else None
        parent_entry = _entry(parent.tree, tracked) if parent is not None else None
        current_id = str(entry.id) if entry is not None else None
        parent_id = str(parent_entry.id) if parent_entry is not None else None
        if current_id == parent_id:
            continue

        commits.append(_commit_record(commit, tracked))
        if len(commits) >= limit:
            next_cursor = Cursor(sha=str(commit.id), path=tracked)
            break

    return History(commits=commits, truncated=truncated, next_cursor=next_cursor)
