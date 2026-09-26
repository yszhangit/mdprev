"""Outline panel widget behavior."""

import pytest

from mdprev.core.outline import UNAVAILABLE_MESSAGE, Heading
from mdprev.gtk.outline import OutlinePanel

HEADINGS = [
    Heading(1, "Guide", "guide"),
    Heading(2, "Install", "install"),
    Heading(3, "From apt", "from-apt"),
    Heading(2, "Use", "use"),
]


def rows(panel):
    found = []
    row = panel._list.get_first_child()
    while row is not None:
        found.append(row)
        row = row.get_next_sibling()
    return found


def label_texts(panel):
    texts = []
    for row in rows(panel):
        child = row.get_child().get_last_child()
        texts.append(child.get_label())
    return texts


@pytest.fixture
def panel(gtk_display):
    jumps = []
    panel = OutlinePanel(2, jumps.append)
    panel.jumps = jumps
    panel.show(HEADINGS)
    return panel


def test_shows_levels_one_and_two_by_default(panel):
    assert label_texts(panel) == ["Guide", "Install", "Use"]


def test_expander_reveals_children(panel):
    install = rows(panel)[1]
    expander = install.get_child().get_first_child()

    expander.emit("clicked")

    assert label_texts(panel) == ["Guide", "Install", "From apt", "Use"]


def test_activating_a_row_reports_its_anchor(panel):
    panel._list.emit("row-activated", rows(panel)[2])

    assert panel.jumps == ["use"]


def test_diff_views_show_a_message_instead(panel):
    panel.show(None)

    assert rows(panel) == []
    assert panel._message.get_visible()
    assert panel._message.get_text() == UNAVAILABLE_MESSAGE
