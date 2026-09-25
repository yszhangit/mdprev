"""Selection and pin rules for the git history sidebar.

The sidebar widget owns the rows; this object owns which revision is
selected, which one is pinned as the comparison base, and the view mode.  A
front end forwards user actions here and reports emit() to its window whenever
a method says the view must change.
"""

from __future__ import annotations

from .diffmodel import pins_available
from .git_history import WORKING_COPY, Revision, WorkingCopy

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
