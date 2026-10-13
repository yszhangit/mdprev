"""Heading outline panel for macOS.

The tree and its expand/collapse state come from core.outline; this module
only turns rows into AppKit views.  Choosing a heading reports its anchor
through a plain callback.
"""

from __future__ import annotations

from collections.abc import Callable

from AppKit import (
    NSButton,
    NSColor,
    NSFont,
    NSImage,
    NSLineBreakByTruncatingTail,
    NSScrollView,
    NSTableColumn,
    NSTableView,
    NSTableViewLastColumnOnlyAutoresizingStyle,
    NSTableViewStyleSourceList,
    NSTextField,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
)
from Foundation import NSMakeRect, NSObject

from ..core.outline import Heading, OutlineModel, OutlineRow

_ROW_HEIGHT = 24.0
_INDENT = 14.0
_CHEVRON = 16.0


class _OutlineRowView(NSView):
    def isFlipped(self):
        return True


class OutlinePanel:
    def __init__(self, expand_level: int, on_jump: Callable[[str], None]):
        self._on_jump = on_jump
        self._model = OutlineModel(expand_level)
        self._rows: list[OutlineRow] = []
        self._bridge = _OutlineBridge.alloc().init()
        self._bridge.owner = self

        self._table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 240, 400))
        column = NSTableColumn.alloc().initWithIdentifier_("outline")
        column.setResizingMask_(1)  # NSTableColumnAutoresizingMask
        self._table.addTableColumn_(column)
        self._table.setHeaderView_(None)
        self._table.setStyle_(NSTableViewStyleSourceList)
        self._table.setColumnAutoresizingStyle_(NSTableViewLastColumnOnlyAutoresizingStyle)
        self._table.setRowHeight_(_ROW_HEIGHT)
        self._table.setDataSource_(self._bridge)
        self._table.setDelegate_(self._bridge)
        # A click action rather than a selection callback, so choosing the
        # same heading again (after scrolling away) still jumps to it.
        self._table.setTarget_(self._bridge)
        self._table.setAction_("rowClicked:")

        scroller = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 240, 400))
        scroller.setDocumentView_(self._table)
        scroller.setHasVerticalScroller_(True)
        scroller.setDrawsBackground_(False)
        scroller.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        self._message = NSTextField.wrappingLabelWithString_("")
        self._message.setTextColor_(NSColor.secondaryLabelColor())
        self._message.setFrame_(NSMakeRect(12, 12, 216, 40))
        self._message.setAutoresizingMask_(NSViewWidthSizable)

        self.view = _OutlineRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 240, 400))
        self.view.addSubview_(scroller)
        self.view.addSubview_(self._message)
        self._show_message()

    def show(self, headings: list[Heading] | None) -> None:
        """Display headings; None when the current view has no outline."""

        self._model.set_headings(headings)
        self._reload()

    def _show_message(self) -> None:
        message = self._model.message
        self._message.setHidden_(message is None)
        self._message.setStringValue_(message or "")

    def _reload(self) -> None:
        self._rows = self._model.rows()
        self._table.sizeLastColumnToFit()
        self._table.reloadData()
        self._show_message()

    # -- table -------------------------------------------------------------

    def row_count(self) -> int:
        return len(self._rows)

    def row_view(self, index: int) -> NSView:
        row = self._rows[index]
        width = self._table.tableColumns()[0].width()
        view = _OutlineRowView.alloc().initWithFrame_(NSMakeRect(0, 0, width, _ROW_HEIGHT))
        x = 4 + row.depth * _INDENT
        if row.has_children:
            symbol = "chevron.down" if row.expanded else "chevron.right"
            label = "Collapse" if row.expanded else "Expand"
            chevron = NSButton.buttonWithImage_target_action_(
                NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, label),
                self._bridge,
                "toggle:",
            )
            chevron.setBordered_(False)
            chevron.setIdentifier_(row.heading.anchor)
            chevron.setContentTintColor_(NSColor.secondaryLabelColor())
            chevron.setToolTip_(label)
            chevron.setFrame_(NSMakeRect(x, (_ROW_HEIGHT - _CHEVRON) / 2, _CHEVRON, _CHEVRON))
            view.addSubview_(chevron)
        x += _CHEVRON + 2
        text = NSTextField.labelWithString_(row.heading.text)
        text.setLineBreakMode_(NSLineBreakByTruncatingTail)
        text.setToolTip_(row.heading.text)
        if row.heading.level == 1:
            text.setFont_(NSFont.boldSystemFontOfSize_(NSFont.systemFontSize()))
        text.setFrame_(NSMakeRect(x, 3, max(width - x - 4, 10), _ROW_HEIGHT - 6))
        text.setAutoresizingMask_(NSViewWidthSizable)
        view.addSubview_(text)
        return view

    def row_clicked(self) -> None:
        index = self._table.clickedRow()
        if 0 <= index < len(self._rows):
            self._on_jump(self._rows[index].heading.anchor)

    def toggle(self, anchor: str) -> None:
        self._model.toggle(anchor)
        self._reload()


class _OutlineBridge(NSObject):
    """NSTableView data source and delegate, and target of the chevrons."""

    owner = None

    def numberOfRowsInTableView_(self, _table):
        return self.owner.row_count() if self.owner is not None else 0

    def tableView_viewForTableColumn_row_(self, _table, _column, index):
        return self.owner.row_view(index)

    def rowClicked_(self, _sender):
        if self.owner is not None:
            self.owner.row_clicked()

    def toggle_(self, sender):
        if self.owner is not None:
            self.owner.toggle(sender.identifier())
