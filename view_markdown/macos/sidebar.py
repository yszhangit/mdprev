"""Git history sidebar for macOS.

The rows, selection, and pins come from core.history_state; this module only
turns them into AppKit views and forwards clicks.  Selections are reported
through a plain callback, as in the GTK front end.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from AppKit import (
    NSButton,
    NSColor,
    NSFont,
    NSImage,
    NSLayoutAttributeWidth,
    NSLineBreakByTruncatingTail,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSStackView,
    NSTableColumn,
    NSTableView,
    NSTableViewLastColumnOnlyAutoresizingStyle,
    NSTableViewStyleSourceList,
    NSTextAlignmentRight,
    NSTextField,
    NSUserInterfaceLayoutOrientationVertical,
    NSView,
    NSViewMinXMargin,
    NSViewWidthSizable,
)
from Foundation import NSIndexSet, NSMakeRect, NSObject

from ..core.diffmodel import FileStats, format_stats
from ..core.git_history import WORKING_COPY, Commit, Revision
from ..core.history_state import MODES, HistoryModel, Row, revision_key

_ROW_HEIGHTS = {"working": 78, "commit": 66, "message": 52, "more": 34}
_PIN_LABELS = ("Compare from this version", "Stop comparing from this version")


_PAD = 8.0
_PIN_SIZE = 20.0


def _label(text: str, *, secondary: bool = False, small: bool = False) -> NSTextField:
    label = NSTextField.labelWithString_(text)
    if secondary:
        label.setTextColor_(NSColor.secondaryLabelColor())
    if small:
        label.setFont_(NSFont.systemFontOfSize_(NSFont.smallSystemFontSize()))
    label.setLineBreakMode_(NSLineBreakByTruncatingTail)
    return label


class _RowView(NSView):
    """A top-down container; children are placed with fixed frames that
    follow the column width through their autoresizing masks."""

    def isFlipped(self):
        return True


def _place(parent: NSView, view: NSView, x: float, y: float, width: float, height: float,
           mask: int = 0) -> NSView:
    view.setFrame_(NSMakeRect(x, y, width, height))
    view.setAutoresizingMask_(mask)
    parent.addSubview_(view)
    return view


class HistorySidebar:
    def __init__(self, on_select: Callable[[Revision, Revision | None, str], None]):
        self._on_select = on_select
        self._model = HistoryModel()
        self._state = self._model.selection
        self._rows: list[Row] = []
        self._pin_buttons: dict[str, NSButton] = {}
        self._stats_labels: dict[str, NSTextField] = {}
        self._dot_label: NSTextField | None = None
        self._status_label: NSTextField | None = None
        # Reloading the table re-reports its selection; suppress the callback
        # so a refresh never looks like a user choosing a revision.
        self._suppress = False

        self._bridge = _SidebarBridge.alloc().init()
        self._bridge.owner = self

        self._table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 400))
        column = NSTableColumn.alloc().initWithIdentifier_("history")
        column.setResizingMask_(1)  # NSTableColumnAutoresizingMask
        self._table.addTableColumn_(column)
        self._table.setHeaderView_(None)
        self._table.setStyle_(NSTableViewStyleSourceList)
        self._table.setColumnAutoresizingStyle_(NSTableViewLastColumnOnlyAutoresizingStyle)
        self._table.setDataSource_(self._bridge)
        self._table.setDelegate_(self._bridge)

        scroller = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 400))
        scroller.setDocumentView_(self._table)
        scroller.setHasVerticalScroller_(True)
        scroller.setDrawsBackground_(False)

        self._mode_control = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            [label for _mode, label in MODES],
            NSSegmentSwitchTrackingSelectOne,
            self._bridge,
            "modeChanged:",
        )
        self._mode_control.setSelectedSegment_(
            [mode for mode, _label in MODES].index(self._state.mode)
        )

        self.view = NSStackView.stackViewWithViews_([scroller, self._mode_control])
        self.view.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        self.view.setSpacing_(6)
        self.view.setAlignment_(NSLayoutAttributeWidth)
        self.view.setEdgeInsets_((0, 0, 8, 0))
        self.view.setFrame_(NSMakeRect(0, 0, 280, 600))

    @property
    def has_pin(self) -> bool:
        return self._state.pinned is not None

    # -- loading -----------------------------------------------------------

    def load(self, repo, path: Path, limit: int) -> None:
        """Query history for path and rebuild the list."""

        self._model.load(repo, path, limit)
        self._rebuild()

    def load_more(self) -> None:
        self._model.load_more()
        self._rebuild()

    def refresh_status(self) -> None:
        """Update the working-copy row's dot, label, stats, and pin."""

        if not self._model.has_repository:
            return
        self._model.refresh_status()
        self._apply_status()
        label = self._stats_labels.get("working")
        if label is not None:
            self._set_stats(label, self._model.working_stats())
        self._update_pins()

    def _apply_status(self) -> None:
        if self._dot_label is None:
            return
        modified = self._model.modified
        self._dot_label.setTextColor_(
            NSColor.systemRedColor() if modified else NSColor.systemGreenColor()
        )
        text = "Modified" if modified else "Unchanged"
        self._status_label.setStringValue_(text)
        # The dot reinforces the label rather than carrying the state alone.
        self._dot_label.setAccessibilityLabel_(text)

    # -- rows --------------------------------------------------------------

    def _rebuild(self) -> None:
        self._suppress = True
        self._rows = self._model.rows()
        self._pin_buttons = {}
        self._stats_labels = {}
        self._dot_label = self._status_label = None
        self._table.sizeLastColumnToFit()
        self._table.reloadData()
        keys = [
            revision_key(row.revision) if row.kind == "revision" else None
            for row in self._rows
        ]
        selected = revision_key(self._state.selected)
        index = keys.index(selected) if selected in keys else 0
        self._table.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(index), False
        )
        self._suppress = False
        if self._model.has_repository:
            self.refresh_status()
        else:
            self._update_pins()

    def row_count(self) -> int:
        return len(self._rows)

    def row_height(self, index: int) -> float:
        row = self._rows[index]
        if row.kind == "revision":
            return _ROW_HEIGHTS["working" if row.revision == WORKING_COPY else "commit"]
        return _ROW_HEIGHTS[row.kind]

    def row_selectable(self, index: int) -> bool:
        return self._rows[index].kind == "revision"

    def row_view(self, index: int) -> NSView:
        row = self._rows[index]
        width = self._table.tableColumns()[0].width()
        view = _RowView.alloc().initWithFrame_(NSMakeRect(0, 0, width, self.row_height(index)))
        inner = width - 2 * _PAD
        if row.kind == "revision" and row.revision == WORKING_COPY:
            self._fill_working(view, width, inner)
        elif row.kind == "revision":
            self._fill_commit(view, row.revision, width, inner)
        elif row.kind == "message":
            label = NSTextField.wrappingLabelWithString_(row.text)
            label.setTextColor_(NSColor.secondaryLabelColor())
            _place(view, label, _PAD, 6, inner, view.frame().size.height - 12, NSViewWidthSizable)
        else:
            button = NSButton.buttonWithTitle_target_action_(row.text, self._bridge, "loadMore:")
            button.setBordered_(False)
            _place(view, button, _PAD, 6, inner, 22, NSViewWidthSizable)
        return view

    def _fill_working(self, view: NSView, width: float, inner: float) -> None:
        title = _label("Working copy")
        title.setFont_(NSFont.boldSystemFontOfSize_(NSFont.systemFontSize()))
        _place(view, title, _PAD, 8, inner - _PIN_SIZE - 4, 18, NSViewWidthSizable)
        _place(view, self._pin_button(WORKING_COPY), width - _PAD - _PIN_SIZE, 7,
               _PIN_SIZE, _PIN_SIZE, NSViewMinXMargin)
        self._dot_label = _place(view, _label("●", small=True), _PAD, 32, 14, 16)
        self._status_label = _place(view, _label("Unchanged", secondary=True, small=True),
                                    _PAD + 16, 32, inner - 16, 16, NSViewWidthSizable)
        stats = self._model.working_stats() if self._model.has_repository else None
        _place(view, self._stats_label("working", stats), _PAD, 52, inner, 16, NSViewWidthSizable)
        self._apply_status()

    def _fill_commit(self, view: NSView, commit: Commit, width: float, inner: float) -> None:
        sha = _label(commit.short_sha)
        sha.setFont_(NSFont.monospacedSystemFontOfSize_weight_(NSFont.systemFontSize(), 0))
        _place(view, sha, _PAD, 7, 76, 18)
        when = _label(commit.when.strftime("%b %-d, %Y"), secondary=True)
        when.setAlignment_(NSTextAlignmentRight)
        date_width = 110.0
        _place(view, when, width - _PAD - _PIN_SIZE - 4 - date_width, 7, date_width, 18,
               NSViewMinXMargin)
        _place(view, self._pin_button(commit), width - _PAD - _PIN_SIZE, 6,
               _PIN_SIZE, _PIN_SIZE, NSViewMinXMargin)
        summary = _label(commit.summary or "(no message)")
        summary.setToolTip_(f"{commit.summary}\n{commit.author}")
        _place(view, summary, _PAD, 27, inner, 18, NSViewWidthSizable)
        stats = self._stats_label(commit.sha, self._model.commit_stats(commit))
        _place(view, stats, _PAD, 46, inner, 16, NSViewWidthSizable)

    def _pin_button(self, revision: Revision) -> NSButton:
        button = NSButton.buttonWithImage_target_action_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_("pin", _PIN_LABELS[0]),
            self._bridge,
            "pinClicked:",
        )
        button.setBordered_(False)
        key = revision_key(revision)
        button.setIdentifier_(key)
        self._pin_buttons[key] = button
        self._style_pin(button, revision)
        return button

    def _style_pin(self, button: NSButton, revision: Revision) -> None:
        pinned = self._state.pinned
        active = pinned is not None and revision_key(pinned) == revision_key(revision)
        button.setHidden_(not self._state.pin_visible(revision))
        button.setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "pin.fill" if active else "pin", _PIN_LABELS[active]
        ))
        button.setContentTintColor_(
            NSColor.controlAccentColor() if active else NSColor.tertiaryLabelColor()
        )
        button.setToolTip_(_PIN_LABELS[active])

    def _stats_label(self, key: str, stats: FileStats | None) -> NSTextField:
        label = _label("", secondary=True, small=True)
        self._set_stats(label, stats)
        self._stats_labels[key] = label
        return label

    @staticmethod
    def _set_stats(label: NSTextField, stats: FileStats | None) -> None:
        # Binary or undecodable content has no meaningful counts; omit the line.
        label.setHidden_(stats is None)
        label.setStringValue_(format_stats(stats) if stats is not None else "")

    def _revision_for_key(self, key: str) -> Revision | None:
        for row in self._rows:
            if row.kind == "revision" and revision_key(row.revision) == key:
                return row.revision
        return None

    # -- selection ---------------------------------------------------------

    def selection_changed(self) -> None:
        index = self._table.selectedRow()
        if self._suppress or index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        if row.kind != "revision":
            return
        self._state.select(row.revision)
        self._emit()

    def mode_changed(self) -> None:
        mode = MODES[self._mode_control.selectedSegment()][0]
        if self._state.set_mode(mode):
            self._emit()

    def _emit(self) -> None:
        self._on_select(*self._state.emit())

    def pin_clicked(self, key: str) -> None:
        revision = self._revision_for_key(key)
        if revision is None:
            return
        self._state.toggle_pin(revision)
        self._update_pins()

    def _update_pins(self) -> None:
        """Show pins only where a comparison is possible; drop an invalid pin."""

        must_emit = self._model.update_pins()
        for key, button in self._pin_buttons.items():
            revision = self._revision_for_key(key)
            if revision is not None:
                self._style_pin(button, revision)
        if must_emit:
            self._emit()

    def clear_pin(self) -> bool:
        """Unpin the base, as Escape does; report whether there was one."""

        if not self._state.clear_pin():
            return False
        self._update_pins()
        return True

    def select_working_copy(self) -> None:
        """Return to the working copy, as Escape does."""

        # No guard on the current selection: the window is the authority on
        # whether a historic revision is on screen and only calls this when
        # one is (see the GTK sidebar for the desync this avoids).
        self._state.select(WORKING_COPY)
        self._rebuild()
        self._emit()


class _SidebarBridge(NSObject):
    """NSTableView data source and delegate, and target of the controls."""

    owner = None

    def numberOfRowsInTableView_(self, _table):
        return self.owner.row_count() if self.owner is not None else 0

    def tableView_viewForTableColumn_row_(self, _table, _column, index):
        return self.owner.row_view(index)

    def tableView_heightOfRow_(self, _table, index):
        return self.owner.row_height(index)

    def tableView_shouldSelectRow_(self, _table, index):
        return self.owner.row_selectable(index)

    def tableViewSelectionDidChange_(self, _notification):
        if self.owner is not None:
            self.owner.selection_changed()

    def modeChanged_(self, _sender):
        if self.owner is not None:
            self.owner.mode_changed()

    def pinClicked_(self, sender):
        if self.owner is not None:
            self.owner.pin_clicked(sender.identifier())

    def loadMore_(self, _sender):
        if self.owner is not None:
            self.owner.load_more()
