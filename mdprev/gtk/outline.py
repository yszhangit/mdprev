"""Heading outline panel.

The tree and its expand/collapse state come from core.outline; this widget
only turns rows into GTK widgets.  Choosing a heading reports its anchor
through a plain callback.
"""

from __future__ import annotations

from collections.abc import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ..core.outline import Heading, OutlineModel  # noqa: E402

_INDENT = 14
# Width of the expander button, kept as blank space on leaf rows so the
# heading texts of one level line up.
_EXPANDER_WIDTH = 24


class OutlinePanel(Gtk.Box):
    def __init__(self, expand_level: int, on_jump: Callable[[str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_jump = on_jump
        self._model = OutlineModel(expand_level)

        self._list = Gtk.ListBox()
        self._list.add_css_class("navigation-sidebar")
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.set_activate_on_single_click(True)
        self._list.connect("row-activated", self._row_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self._list)

        self._message = Gtk.Label(xalign=0.0)
        self._message.set_wrap(True)
        self._message.add_css_class("dim-label")
        self._message.set_margin_top(12)
        self._message.set_margin_start(12)
        self._message.set_margin_end(12)

        self.append(self._message)
        self.append(scroller)
        self._rebuild()

    def show(self, headings: list[Heading] | None) -> None:
        """Display headings; None when the current view has no outline."""

        self._model.set_headings(headings)
        self._rebuild()

    def _rebuild(self) -> None:
        while (child := self._list.get_first_child()) is not None:
            self._list.remove(child)
        for row in self._model.rows():
            self._list.append(self._row(row))
        message = self._model.message
        self._message.set_text(message or "")
        self._message.set_visible(message is not None)

    def _row(self, row) -> Gtk.ListBoxRow:
        widget = Gtk.ListBoxRow()
        widget.anchor = row.heading.anchor
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        box.set_margin_start(row.depth * _INDENT)
        if row.has_children:
            expander = Gtk.Button(
                icon_name="pan-down-symbolic" if row.expanded else "pan-end-symbolic"
            )
            expander.add_css_class("flat")
            expander.set_size_request(_EXPANDER_WIDTH, -1)
            expander.set_tooltip_text("Collapse" if row.expanded else "Expand")
            expander.connect("clicked", lambda _b, anchor=row.heading.anchor: self._toggle(anchor))
            box.append(expander)
        else:
            spacer = Gtk.Box()
            spacer.set_size_request(_EXPANDER_WIDTH, -1)
            box.append(spacer)
        label = Gtk.Label(label=row.heading.text, xalign=0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
        label.set_tooltip_text(row.heading.text)
        if row.heading.level == 1:
            label.add_css_class("heading")
        box.append(label)
        widget.set_child(box)
        return widget

    def _toggle(self, anchor: str) -> None:
        self._model.toggle(anchor)
        self._rebuild()

    def _row_activated(self, _list, row) -> None:
        anchor = getattr(row, "anchor", None)
        if anchor is not None:
            self._on_jump(anchor)
