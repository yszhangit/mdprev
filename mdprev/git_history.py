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


def _entry(tree, relpath: str) -> pygit2.Blob | None:
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


def _rename_patch(repo, parent, commit, tracked: str) -> pygit2.Patch | None:
    """Return the Patch that renamed tracked into commit, or None.

    Only called when the path exists in the commit and is absent from the
    parent, because computing a rename-detecting diff is far more expensive
    than the tree lookups that drive the walk. Returning the Patch itself
    (rather than just the old path) lets callers reuse its rendered text: a
    rename with unchanged content has identical old and new blobs, and a
    patch built directly from those two blobs would come back empty, losing
    the "renamed from" header that only a whole-diff rename detection can
    produce.
    """

    diff = repo.diff(parent.tree, commit.tree)
    diff.find_similar()
    for patch in diff:
        delta = patch.delta
        if delta.new_file.path == tracked and delta.status == DeltaStatus.RENAMED:
            return patch
    return None


def _rename_source(repo, parent, commit, tracked: str) -> str | None:
    """Return the file's previous name when this commit renamed it.

    See _rename_patch for the calling convention this shares (only called
    when the path exists in the commit and is absent from the parent).
    """

    patch = _rename_patch(repo, parent, commit, tracked)
    return patch.delta.old_file.path if patch is not None else None


def history(repo, path: Path, limit: int = 10, after: Cursor | None = None) -> History:
    """Return commits touching path, newest first.

    A commit touches the file when the blob recorded at the tracked path
    differs from the one recorded in its first parent.  Merge commits are
    compared against their first parent only, so history follows a single
    line of descent through a merge rather than every side.  When the
    tracked path exists in a commit but is absent from that parent, a
    rename-detecting diff is run to check whether the file was renamed; if
    so, older revisions are looked up under the previous name, matching
    git log --follow.
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

        renamed_from = None
        if entry is not None and parent_entry is None and parent is not None:
            renamed_from = _rename_source(repo, parent, commit, tracked)

        commits.append(_commit_record(commit, tracked))
        if renamed_from is not None:
            # Older revisions carry the file under its previous name.
            tracked = renamed_from
        if len(commits) >= limit:
            next_cursor = Cursor(sha=str(commit.id), path=tracked)
            break

    return History(commits=commits, truncated=truncated, next_cursor=next_cursor)


def _lookup_commit(repo, sha: str):
    try:
        commit = repo.revparse_single(sha)
    except (KeyError, ValueError, pygit2.GitError) as exc:
        raise GitHistoryError(f"Unknown revision {sha[:7]}") from exc
    if not isinstance(commit, pygit2.Commit):
        raise GitHistoryError(f"{sha[:7]} is not a commit")
    return commit


def file_at(repo, sha: str, path: str) -> str:
    """Return the UTF-8 text of path as recorded at sha."""

    commit = _lookup_commit(repo, sha)
    blob = _entry(commit.tree, path)
    if blob is None:
        raise GitHistoryError(f"{path} does not exist at {sha[:7]}")
    if blob.is_binary:
        raise GitHistoryError(f"Unable to read {path} at {sha[:7]}: the file is binary")
    try:
        return blob.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHistoryError(
            f"Unable to read {path} at {sha[:7]}: the file is not valid UTF-8"
        ) from exc


def patch_for(repo, sha: str, path: str) -> str:
    """Return the unified diff of path at sha against its first parent."""

    commit = _lookup_commit(repo, sha)
    new_blob = _entry(commit.tree, path)
    parent = commit.parents[0] if commit.parents else None
    old_blob = None
    if parent is not None:
        old_blob = _entry(parent.tree, path)
        if new_blob is not None and old_blob is None:
            renamed = _rename_patch(repo, parent, commit, path)
            if renamed is not None:
                # A content-preserving rename has identical old and new
                # blobs; a patch built from those two blobs would come back
                # empty and lose the "renamed from" header, so the whole-diff
                # rename detection's own patch is returned directly instead.
                return renamed.text or ""
    if old_blob is None and new_blob is None:
        return ""
    patch = pygit2.Patch.create_from(
        old_blob,
        new_blob,
        old_as_path=path,
        new_as_path=path,
    )
    return patch.text or ""


def working_patch(repo, path: Path) -> str:
    """Return the unified diff of the file on disk against HEAD.

    Unlike is_modified(), a path outside the repository is left to raise
    GitHistoryError here rather than being swallowed: the caller renders that
    error as visible text, and reporting an empty diff for a genuinely
    invalid path would be misleading.
    """

    relative = _relative_path(repo, path)
    old_blob = None
    if not repo.head_is_unborn:
        old_blob = _entry(repo[repo.head.target].tree, relative)
    try:
        new_data = Path(path).read_bytes()
    except OSError as exc:
        raise GitHistoryError(
            f"Unable to read {Path(path).name}: {exc.strerror or exc}"
        ) from exc
    if old_blob is None and not new_data:
        return ""
    patch = pygit2.Patch.create_from(
        old_blob,
        new_data,
        old_as_path=relative,
        new_as_path=relative,
    )
    return patch.text or ""


def is_modified(repo, path: Path) -> bool:
    """Report whether the file differs from HEAD, staged or unstaged.

    Local status only: no remote, upstream, or ahead/behind information is
    consulted.
    """

    try:
        relative = _relative_path(repo, path)
    except GitHistoryError:
        return False
    try:
        status = repo.status_file(relative)
    except KeyError:
        return False
    if status & FileStatus.IGNORED:
        return False
    return status != FileStatus.CURRENT
