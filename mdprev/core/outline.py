"""Heading outline of the displayed document.

Headings are read from the sanitized HTML the window shows, so every anchor
names an element the web view can scroll to.  OutlineModel arranges them as a
collapsible tree and lists the rows a front end should show.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

from .preferences import DEFAULT_OUTLINE_EXPAND_LEVEL

UNAVAILABLE_MESSAGE = "The outline is shown in the Rendered view"
EMPTY_MESSAGE = "No headings"

_HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    anchor: str


@dataclass(frozen=True)
class OutlineRow:
    heading: Heading
    depth: int
    has_children: bool
    expanded: bool


class _HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[Heading] = []
        self._open: tuple[int, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        level = _HEADING_TAGS.get(tag)
        if level is None or self._open is not None:
            return
        anchor = dict(attrs).get("id")
        # Only application-generated anchors are navigable; the error page's
        # heading has none.
        if anchor:
            self._open = (level, anchor)
            self._text = []

    def handle_endtag(self, tag):
        if self._open is not None and _HEADING_TAGS.get(tag) == self._open[0]:
            level, anchor = self._open
            text = " ".join("".join(self._text).split())
            self.headings.append(Heading(level, text or anchor, anchor))
            self._open = None

    def handle_data(self, data):
        if self._open is not None:
            self._text.append(data)


def headings_from_html(html: str) -> list[Heading]:
    parser = _HeadingParser()
    parser.feed(html)
    parser.close()
    return parser.headings


def headings_for_view(html: str, mode: str) -> list[Heading] | None:
    """The outline of what the window shows; None outside the Rendered view,
    whose diff pages have no document headings to jump to."""

    return headings_from_html(html) if mode == "rendered" else None


class OutlineModel:
    def __init__(self, expand_level: int = DEFAULT_OUTLINE_EXPAND_LEVEL) -> None:
        # Headings above this level start expanded, so levels up to and
        # including it are visible (the default 2 shows H1 and H2).
        self.expand_level = expand_level
        self.message: str | None = EMPTY_MESSAGE
        self._headings: list[Heading] = []
        self._depths: list[int] = []
        self._parents: list[int | None] = []
        self._has_children: list[bool] = []
        # The reader's own expand/collapse choices, by anchor, kept across
        # reloads of the same document.
        self._choices: dict[str, bool] = {}

    def set_headings(self, headings: list[Heading] | None) -> None:
        """Show headings; None means the current view has no outline."""

        if headings is None:
            self.message = UNAVAILABLE_MESSAGE
            headings = []
        else:
            self.message = None if headings else EMPTY_MESSAGE
        self._headings = headings
        self._depths = []
        self._parents = []
        stack: list[int] = []  # indexes of the open ancestors
        for index, heading in enumerate(headings):
            while stack and headings[stack[-1]].level >= heading.level:
                stack.pop()
            self._parents.append(stack[-1] if stack else None)
            self._depths.append(len(stack))
            stack.append(index)
        self._has_children = [False] * len(headings)
        for parent in self._parents:
            if parent is not None:
                self._has_children[parent] = True
        anchors = {heading.anchor for heading in headings}
        self._choices = {a: v for a, v in self._choices.items() if a in anchors}

    def _expanded(self, index: int) -> bool:
        heading = self._headings[index]
        return self._choices.get(heading.anchor, heading.level < self.expand_level)

    def rows(self) -> list[OutlineRow]:
        rows = []
        visible: list[bool] = []
        for index, heading in enumerate(self._headings):
            parent = self._parents[index]
            shown = parent is None or (visible[parent] and self._expanded(parent))
            visible.append(shown)
            if shown:
                rows.append(OutlineRow(
                    heading,
                    self._depths[index],
                    self._has_children[index],
                    self._has_children[index] and self._expanded(index),
                ))
        return rows

    def toggle(self, anchor: str) -> None:
        """Expand a collapsed heading or collapse an expanded one."""

        for index, heading in enumerate(self._headings):
            if heading.anchor == anchor and self._has_children[index]:
                self._choices[anchor] = not self._expanded(index)
                return
