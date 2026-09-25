"""State behind the git history sidebar.

HistoryModel loads a file's history and decides which rows the sidebar lists;
HistorySelection owns which revision is selected, which one is pinned as the
comparison base, and the view mode.  A front end only turns rows into widgets,
forwards user actions here, and reports HistorySelection.emit() to its window
whenever a method says the view must change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import git_history
from .diffmodel import FileStats, pins_available
from .git_history import WORKING_COPY, Commit, Revision, WorkingCopy

MODES = (("rendered", "Rendered"), ("diff", "Diff"), ("side-by-side", "Side by side"))

Selection = tuple[Revision, Revision | None, str]


class HistorySelection:
    def __init__(self) -> None:
        self.mode = "rendered"
        self.selected: Revision = WORKING_COPY
        # The pin is what the reader chose to compare from; the shown base is
        # what the window was last told, which lags while a new pin awaits a
        # selection (pinning alone never changes the view).
        self.pinned: Revision | None = None
        self.shown_base: Revision | None = None
        self.modified = False
        self.pins_available = False

    def emit(self) -> Selection:
        """Return (target, base, mode) for the window and record the base."""

        pinned = self.pinned
        base = pinned if pinned is not None and pinned != self.selected else None
        self.shown_base = base
        return self.selected, base, self.mode

    def select(self, revision: Revision) -> None:
        self.selected = revision

    def set_mode(self, mode: str) -> bool:
        """Switch the view mode; report whether it changed."""

        if mode == self.mode:
            return False
        self.mode = mode
        return True

    def toggle_pin(self, revision: Revision) -> None:
        """Pin revision, or unpin it if it already is; follow with update()."""

        self.pinned = None if self.pinned == revision else revision

    def clear_pin(self) -> bool:
        """Unpin the base, as Escape does; report whether there was one.

        Follow a True result with update().
        """

        if self.pinned is None:
            return False
        self.pinned = None
        return True

    def update(self, loaded_commits: int, has_more: bool, modified: bool) -> bool:
        """Recompute where pins apply and drop a pin that no longer can.

        Returns True when the window must be told (call emit()): a comparison
        on screen whose base was unpinned must not keep showing that base.
        """

        self.modified = modified
        self.pins_available = pins_available(loaded_commits, has_more, modified)
        pinned = self.pinned
        if pinned is not None and (
            not self.pins_available
            or (isinstance(pinned, WorkingCopy) and not modified)
        ):
            self.pinned = None
        return self.pinned is None and self.shown_base is not None

    def pin_visible(self, revision: Revision) -> bool:
        """Whether revision's pin button should be offered."""

        return self.pins_available and (
            not isinstance(revision, WorkingCopy) or self.modified
        )


def revision_key(revision: Revision) -> str:
    """A stable identifier for a revision's row."""

    return "working" if isinstance(revision, WorkingCopy) else revision.sha


@dataclass(frozen=True)
class Row:
    """One sidebar entry.

    kind is "revision" (revision is set), "message" (text is informational),
    or "more" (text labels the action that calls HistoryModel.load_more()).
    """

    kind: str
    revision: Revision | None = None
    text: str = ""


class HistoryModel:
    def __init__(self) -> None:
        self.selection = HistorySelection()
        self.repo = None
        self.path: Path | None = None
        self.limit = 10
        self.commits: list[Commit] = []
        self.cursor = None
        self.truncated = False
        self.message: str | None = None
        self.modified = False
        # Commits are immutable, so their stats never need recomputing.
        self._stats_cache: dict[tuple[str, str], FileStats | None] = {}

    @property
    def has_repository(self) -> bool:
        return self.repo is not None and self.path is not None

    def load(self, repo, path: Path, limit: int) -> None:
        """Query the first page of history for path."""

        self.repo = repo
        self.path = path
        self.limit = limit
        self.commits = []
        self.cursor = None
        self.truncated = False
        self.message = None
        if repo is None:
            self.message = "Not in a git repository"
        elif not git_history.is_tracked(repo, path):
            self.message = "Not tracked in this repository"
        else:
            self._fetch(after=None)

    def load_more(self) -> None:
        self._fetch(after=self.cursor)

    def _fetch(self, after) -> None:
        try:
            result = git_history.history(self.repo, self.path, limit=self.limit, after=after)
        except git_history.GitHistoryError as exc:
            self.message = str(exc)
            return
        self.commits.extend(result.commits)
        self.cursor = result.next_cursor
        self.truncated = result.truncated
        if not self.commits and self.message is None:
            if self.repo.head_is_unborn:
                self.message = "No commits yet"
            else:
                self.message = "No history for this file"

    def rows(self) -> list[Row]:
        rows = [Row("revision", WORKING_COPY)]
        # The selected commit can fall off the currently loaded page (e.g. a
        # deep "Show more" selection, refetched after the sidebar was hidden
        # and reshown). The window is still displaying it, so the list must
        # still visibly indicate it rather than silently falling back to
        # "Working copy" while a historic revision is on screen. A pinned
        # off-page commit is kept too, so its pin button stays reachable.
        loaded = {commit.sha for commit in self.commits}
        extras: list[Commit] = []
        for revision in (self.selection.selected, self.selection.pinned):
            if (
                isinstance(revision, Commit)
                and revision.sha not in loaded
                and revision not in extras
            ):
                extras.append(revision)
        rows.extend(Row("revision", commit) for commit in extras + self.commits)
        if self.message is not None:
            rows.append(Row("message", text=self.message))
        if self.truncated:
            rows.append(
                Row("message", text=f"History truncated after {git_history.MAX_SCAN} commits")
            )
        if self.cursor is not None:
            rows.append(Row("more", text="Show more"))
        return rows

    def refresh_status(self) -> None:
        """Re-read whether the working copy differs from HEAD."""

        if self.has_repository:
            self.modified = git_history.is_modified(self.repo, self.path)

    def update_pins(self) -> bool:
        """Revalidate pins; True when the window must be told (emit())."""

        return self.selection.update(len(self.commits), self.cursor is not None, self.modified)

    def working_stats(self) -> FileStats | None:
        try:
            return git_history.revision_stats(self.repo, self.path, WORKING_COPY)
        except git_history.GitHistoryError:
            # A transient read failure (e.g. the file vanished between the
            # save event and this refresh) hides the stats rather than
            # crashing; a later refresh can recover them.
            return None

    def commit_stats(self, commit: Commit) -> FileStats | None:
        key = (commit.sha, commit.path)
        if key not in self._stats_cache:
            try:
                stats = git_history.revision_stats(self.repo, self.path, commit)
            except git_history.GitHistoryError:
                # Not cached: an unknown revision or a transient read failure
                # may succeed on a later rebuild, unlike a genuine binary or
                # absent result (which revision_stats itself returns as None).
                return None
            self._stats_cache[key] = stats
        return self._stats_cache[key]
