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

from ..core.diffmodel import FileStats, format_stats  # noqa: E402
from ..core.git_history import WORKING_COPY, Commit, Revision  # noqa: E402
from ..core.history_state import MODES, HistoryModel, revision_key as _key  # noqa: E402


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
.mdprev-pin {
  min-height: 0;
  min-width: 0;
  padding: 2px;
  opacity: 0.45;
}
.mdprev-pin-active {
  opacity: 1;
  color: #3584e4;
  color: @accent_color;
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
    def __init__(self, on_select: Callable[[Revision, Revision | None, str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        install_css()
        self._on_select = on_select
        self._model = HistoryModel()
        self._state = self._model.selection
        self._rows: dict[str, Gtk.ListBoxRow] = {}
        self._pin_buttons: dict[str, Gtk.Button] = {}
        self._stats_labels: dict[str, Gtk.Label] = {}
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

        self._mode_buttons: list[Gtk.ToggleButton] = []
        for mode, label in MODES:
            button = Gtk.ToggleButton(label=label)
            if self._mode_buttons:
                button.set_group(self._mode_buttons[0])
            button.set_active(mode == self._state.mode)
            button.connect("toggled", self._mode_toggled, mode)
            box.append(button)
            self._mode_buttons.append(button)
        return box

    def _mode_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        # Each group change toggles two buttons; only the newly active one counts.
        if not button.get_active() or not self._state.set_mode(mode):
            return
        self._emit()

    # -- loading ---------------------------------------------------------

    def load(self, repo, path: Path, limit: int) -> None:
        """Query history for path and rebuild the list."""

        self._model.load(repo, path, limit)
        self._rebuild()

    def _load_more(self) -> None:
        self._model.load_more()
        self._rebuild()

    def refresh_status(self) -> None:
        """Update the working-copy row's dot, label, stats, and pin."""

        if not self._model.has_repository:
            return
        self._model.refresh_status()
        self._apply_status(self._model.modified)
        working_stats = self._stats_labels.get("working")
        if working_stats is not None:
            self._set_stats(working_stats, self._model.working_stats())
        self._update_pins()

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
        self._rows = {}
        self._pin_buttons = {}
        self._stats_labels = {}

        for row in self._model.rows():
            if row.kind == "revision" and row.revision == WORKING_COPY:
                self._list.append(self._working_row())
            elif row.kind == "revision":
                self._list.append(self._commit_row(row.revision))
            elif row.kind == "message":
                self._list.append(self._message_row(row.text))
            else:
                self._list.append(self._action_row(row.text, self._load_more))

        self._list.select_row(
            self._rows.get(_key(self._state.selected), self._rows["working"])
        )
        self._suppress = False
        if self._model.has_repository:
            self.refresh_status()
        else:
            self._update_pins()

    def _working_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = WORKING_COPY
        row.action = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Working copy", xalign=0.0)
        title.add_css_class("heading")
        title.set_hexpand(True)
        top.append(title)
        top.append(self._pin_button(WORKING_COPY))

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._dot_label = Gtk.Label(label="●")
        self._dot_label.add_css_class("mdprev-dot")
        self._status_label = Gtk.Label(label="Unchanged", xalign=0.0)
        self._status_label.add_css_class("dim-label")
        status_box.append(self._dot_label)
        status_box.append(self._status_label)

        box.append(top)
        box.append(status_box)
        box.append(self._stats_label("working", None))
        row.set_child(box)
        self._rows["working"] = row
        return row

    def _commit_row(self, commit: Commit) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = commit
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
        top.append(self._pin_button(commit))

        summary = Gtk.Label(label=commit.summary or "(no message)", xalign=0.0)
        summary.set_ellipsize(Pango.EllipsizeMode.END)
        summary.set_tooltip_text(f"{commit.summary}\n{commit.author}")

        box.append(top)
        box.append(summary)
        box.append(self._stats_label(commit.sha, self._model.commit_stats(commit)))
        row.set_child(box)
        self._rows[commit.sha] = row
        return row

    def _pin_button(self, revision: Revision) -> Gtk.Button:
        button = Gtk.Button(icon_name="view-pin-symbolic")
        button.add_css_class("flat")
        button.add_css_class("mdprev-pin")
        button.set_valign(Gtk.Align.CENTER)
        # Hidden until _update_pins decides there is something to compare.
        button.set_visible(False)
        button.revision = revision
        button.connect("clicked", lambda _button: self._pin_clicked(revision))
        self._pin_buttons[_key(revision)] = button
        return button

    def _stats_label(self, key: str, stats: FileStats | None) -> Gtk.Label:
        label = Gtk.Label(xalign=0.0)
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        self._set_stats(label, stats)
        self._stats_labels[key] = label
        return label

    @staticmethod
    def _set_stats(label: Gtk.Label, stats: FileStats | None) -> None:
        # Binary or undecodable content has no meaningful counts; omit the line.
        label.set_visible(stats is not None)
        label.set_text(format_stats(stats) if stats is not None else "")

    def _message_row(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = None
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
        row.revision = None
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
        revision = getattr(row, "revision", None)
        if revision is None:
            return
        self._state.select(revision)
        self._emit()

    def _emit(self) -> None:
        self._on_select(*self._state.emit())

    def _pin_clicked(self, revision: Revision) -> None:
        self._state.toggle_pin(revision)
        self._update_pins()

    def _update_pins(self) -> None:
        """Show pins only where a comparison is possible; drop an invalid pin."""

        must_emit = self._model.update_pins()
        pinned = self._state.pinned
        pinned_key = _key(pinned) if pinned is not None else None
        for key, button in self._pin_buttons.items():
            button.set_visible(self._state.pin_visible(button.revision))
            active = key == pinned_key
            if active:
                button.add_css_class("mdprev-pin-active")
            else:
                button.remove_css_class("mdprev-pin-active")
            text = (
                "Stop comparing from this version" if active
                else "Compare from this version"
            )
            button.set_tooltip_text(text)
            button.update_property([Gtk.AccessibleProperty.LABEL], [text])
        if must_emit:
            self._emit()

    def clear_pin(self) -> bool:
        """Unpin the base, as Escape does; report whether there was one."""

        if not self._state.clear_pin():
            return False
        self._update_pins()
        return True

    def select_working_copy(self) -> None:
        """Return to the working copy, as Escape and sidebar-close do."""

        # No guard on the selected revision here: the caller (PreviewWindow)
        # is the authority on whether a historic revision is on screen, and it
        # only calls this when one is. Bailing out early based on the selection
        # alone would repeat the desync this method exists to correct: the
        # selection can legitimately be out of step with what the window is
        # displaying (see _rebuild), and skipping the callback in that case
        # would leave a historic revision on screen with nothing selected.
        self._state.select(WORKING_COPY)
        self._rebuild()
        self._emit()
