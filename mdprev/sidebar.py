"""Git history sidebar.

The widget owns the commit list and the view toggle and reports selections
through a plain callback.  The window reacts to the callback and does not
reach into the widget's internals.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from . import git_history  # noqa: E402
from .git_history import Commit  # noqa: E402


# The application has no other GTK-level styling; all document styling lives
# inside the WebKit document.  The palette fallbacks come first so that a theme
# without the named colors still renders a colored dot.
_CSS = b"""
.mdprev-dot {
  font-size: 12px;
}
.mdprev-dot-modified {
  color: #e01b24;
  color: @error_color;
}
.mdprev-dot-clean {
  color: #2ec27e;
  color: @success_color;
}
.mdprev-sidebar-message {
  padding: 12px;
}
"""

_CSS_INSTALLED = False


def install_css() -> None:
    """Register the sidebar's style classes once on the default display."""

    global _CSS_INSTALLED
    if _CSS_INSTALLED:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _CSS_INSTALLED = True


class HistorySidebar(Gtk.Box):
    def __init__(self, on_select: Callable[[Commit | None, str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        install_css()
        self._on_select = on_select
        self._repo = None
        self._path: Path | None = None
        self._limit = 10
        self._commits: list[Commit] = []
        self._cursor = None
        self._truncated = False
        self._message: str | None = None
        self._mode = "rendered"
        self._selected: Commit | None = None
        # Rebuilding the list re-emits row selection; suppress the callback so
        # a refresh never looks like a user choosing a revision.
        self._suppress = False

        self._list = Gtk.ListBox()
        self._list.add_css_class("navigation-sidebar")
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._row_selected)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self._list)
        self.append(scroller)
        self.append(self._build_mode_switch())

    def _build_mode_switch(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("linked")
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_homogeneous(True)

        self._rendered_button = Gtk.ToggleButton(label="Rendered")
        self._rendered_button.set_active(True)
        self._diff_button = Gtk.ToggleButton(label="Diff")
        self._diff_button.set_group(self._rendered_button)
        self._rendered_button.connect("toggled", self._mode_toggled)

        box.append(self._rendered_button)
        box.append(self._diff_button)
        return box

    def _mode_toggled(self, button: Gtk.ToggleButton) -> None:
        mode = "rendered" if button.get_active() else "diff"
        if mode == self._mode:
            return
        self._mode = mode
        self._on_select(self._selected, self._mode)

    # -- loading ---------------------------------------------------------

    def load(self, repo, path: Path, limit: int) -> None:
        """Query history for path and rebuild the list."""

        self._repo = repo
        self._path = path
        self._limit = limit
        self._commits = []
        self._cursor = None
        self._truncated = False
        self._message = None
        if repo is None:
            self._message = "Not in a git repository"
        elif not git_history.is_tracked(repo, path):
            self._message = "Not tracked in this repository"
        else:
            self._fetch(after=None)
        self._rebuild()

    def _fetch(self, after) -> None:
        try:
            result = git_history.history(
                self._repo, self._path, limit=self._limit, after=after
            )
        except git_history.GitHistoryError as exc:
            self._message = str(exc)
            return
        self._commits.extend(result.commits)
        self._cursor = result.next_cursor
        self._truncated = result.truncated
        if not self._commits and self._message is None:
            if self._repo.head_is_unborn:
                self._message = "No commits yet"
            else:
                self._message = "No history for this file"

    def _load_more(self) -> None:
        self._fetch(after=self._cursor)
        self._rebuild()

    def refresh_status(self) -> None:
        """Update only the working-copy row's dot and label."""

        if self._repo is None or self._path is None:
            return
        modified = git_history.is_modified(self._repo, self._path)
        self._apply_status(modified)

    def _apply_status(self, modified: bool) -> None:
        if not hasattr(self, "_dot_label"):
            return
        self._dot_label.remove_css_class("mdprev-dot-modified")
        self._dot_label.remove_css_class("mdprev-dot-clean")
        self._dot_label.add_css_class(
            "mdprev-dot-modified" if modified else "mdprev-dot-clean"
        )
        text = "Modified" if modified else "Unchanged"
        self._status_label.set_text(text)
        # The dot reinforces the label rather than carrying the state alone.
        self._dot_label.update_property([Gtk.AccessibleProperty.LABEL], [text])

    # -- rows ------------------------------------------------------------

    def _rebuild(self) -> None:
        self._suppress = True
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)

        working = self._working_row()
        self._list.append(working)
        for commit in self._commits:
            self._list.append(self._commit_row(commit))
        if self._message is not None:
            self._list.append(self._message_row(self._message))
        if self._truncated:
            self._list.append(
                self._message_row(f"History truncated after {git_history.MAX_SCAN} commits")
            )
        if self._cursor is not None:
            self._list.append(self._action_row("Show more", self._load_more))

        selected_row = working
        if self._selected is not None:
            for row in self._iter_rows():
                if getattr(row, "commit", None) is not None and row.commit.sha == self._selected.sha:
                    selected_row = row
                    break
        self._list.select_row(selected_row)
        self._suppress = False
        if self._repo is not None and self._path is not None:
            self.refresh_status()

    def _iter_rows(self):
        row = self._list.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

    def _working_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = None
        row.action = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        title = Gtk.Label(label="Working copy", xalign=0.0)
        title.add_css_class("heading")

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._dot_label = Gtk.Label(label="●")
        self._dot_label.add_css_class("mdprev-dot")
        self._status_label = Gtk.Label(label="Unchanged", xalign=0.0)
        self._status_label.add_css_class("dim-label")
        status_box.append(self._dot_label)
        status_box.append(self._status_label)

        box.append(title)
        box.append(status_box)
        row.set_child(box)
        return row

    def _commit_row(self, commit: Commit) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = commit
        row.action = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sha = Gtk.Label(label=commit.short_sha, xalign=0.0)
        sha.add_css_class("monospace")
        when = Gtk.Label(label=commit.when.strftime("%b %-d, %Y"), xalign=1.0)
        when.add_css_class("dim-label")
        when.set_hexpand(True)
        top.append(sha)
        top.append(when)

        summary = Gtk.Label(label=commit.summary or "(no message)", xalign=0.0)
        summary.set_ellipsize(Pango.EllipsizeMode.END)
        summary.set_tooltip_text(f"{commit.summary}\n{commit.author}")

        box.append(top)
        box.append(summary)
        row.set_child(box)
        return row

    def _message_row(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = None
        row.action = None
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(label=text, xalign=0.0)
        label.set_wrap(True)
        label.add_css_class("dim-label")
        label.add_css_class("mdprev-sidebar-message")
        row.set_child(label)
        return row

    def _action_row(self, text: str, callback) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = None
        row.action = callback
        row.set_selectable(False)
        button = Gtk.Button(label=text)
        button.add_css_class("flat")
        button.connect("clicked", lambda _button: callback())
        row.set_child(button)
        return row

    # -- selection -------------------------------------------------------

    def _row_selected(self, _list, row) -> None:
        if self._suppress or row is None:
            return
        if getattr(row, "action", None) is not None:
            return
        self._selected = getattr(row, "commit", None)
        self._on_select(self._selected, self._mode)

    def select_working_copy(self) -> None:
        """Return to the working copy, as Escape and sidebar-close do."""

        if self._selected is None:
            return
        self._selected = None
        self._rebuild()
        self._on_select(None, self._mode)
