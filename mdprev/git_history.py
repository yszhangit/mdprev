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
