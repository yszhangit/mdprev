"""Heading outline shared by both front ends."""

from mdprev.core import session
from mdprev.core.git_history import WORKING_COPY
from mdprev.core.outline import (
    EMPTY_MESSAGE,
    UNAVAILABLE_MESSAGE,
    Heading,
    OutlineModel,
    headings_for_view,
    headings_from_html,
)

DOC = """# Guide

Intro

## Install *now*

### From apt

### From source

## Use &amp; enjoy

#### Deep

# Appendix
"""


def _headings(tmp_path, text=DOC):
    doc = tmp_path / "doc.md"
    doc.write_text(text, encoding="utf-8")
    html = session.build_html(doc, None, WORKING_COPY, None, "rendered", "system", "system")
    return headings_from_html(html)


def _shown(model):
    return [("  " * row.depth) + row.heading.text for row in model.rows()]


def test_headings_come_from_the_rendered_page_with_its_anchors(tmp_path):
    headings = _headings(tmp_path)

    assert [(h.level, h.text, h.anchor) for h in headings] == [
        (1, "Guide", "guide"),
        (2, "Install now", "install-now"),
        (3, "From apt", "from-apt"),
        (3, "From source", "from-source"),
        (2, "Use & enjoy", "use-enjoy"),
        (4, "Deep", "deep"),
        (1, "Appendix", "appendix"),
    ]


def test_headings_in_code_blocks_and_error_pages_are_not_listed(tmp_path):
    assert _headings(tmp_path, "```\n# not a heading\n```\n") == []
    assert headings_from_html(session.build_html(
        tmp_path / "missing.md", None, WORKING_COPY, None, "rendered", "system", "system"
    )) == []


def test_default_shows_levels_one_and_two(tmp_path):
    model = OutlineModel()
    model.set_headings(_headings(tmp_path))

    assert _shown(model) == ["Guide", "  Install now", "  Use & enjoy", "Appendix"]
    rows = model.rows()
    assert (rows[0].has_children, rows[0].expanded) == (True, True)
    assert (rows[1].has_children, rows[1].expanded) == (True, False)
    assert (rows[3].has_children, rows[3].expanded) == (False, False)


def test_expand_level_is_configurable(tmp_path):
    model = OutlineModel(expand_level=1)
    model.set_headings(_headings(tmp_path))
    assert _shown(model) == ["Guide", "Appendix"]

    model = OutlineModel(expand_level=6)
    model.set_headings(_headings(tmp_path))
    assert len(model.rows()) == 7


def test_toggle_expands_and_collapses_a_branch(tmp_path):
    model = OutlineModel()
    model.set_headings(_headings(tmp_path))

    model.toggle("install-now")
    assert _shown(model)[:4] == ["Guide", "  Install now", "    From apt", "    From source"]

    model.toggle("guide")
    assert _shown(model) == ["Guide", "Appendix"]

    model.toggle("appendix")  # no children: nothing to toggle
    assert _shown(model) == ["Guide", "Appendix"]


def test_choices_survive_a_reload(tmp_path):
    model = OutlineModel()
    model.set_headings(_headings(tmp_path))
    model.toggle("install-now")

    model.set_headings(_headings(tmp_path, DOC + "\n## Added\n"))

    assert "    From apt" in _shown(model)
    assert "  Added" in _shown(model)


def test_headings_for_view_only_in_rendered_mode(tmp_path):
    html = session.build_html(
        tmp_path / "missing.md", None, WORKING_COPY, None, "rendered", "system", "system"
    )
    assert headings_for_view(html, "rendered") == []
    assert headings_for_view(html, "diff") is None


def test_scroll_script_quotes_the_anchor():
    assert session.scroll_to_anchor_script('a"b</script>') == (
        'document.getElementById("a\\"b</script>")?.scrollIntoView()'
    )


def test_skipped_levels_nest_under_the_nearest_higher_heading():
    model = OutlineModel(expand_level=6)
    model.set_headings([Heading(3, "c", "c"), Heading(1, "a", "a"), Heading(4, "d", "d")])

    assert _shown(model) == ["c", "a", "  d"]


def test_messages_for_empty_and_unavailable_outlines():
    model = OutlineModel()
    assert model.message == EMPTY_MESSAGE
    model.set_headings(None)
    assert (model.message, model.rows()) == (UNAVAILABLE_MESSAGE, [])
    model.set_headings([Heading(1, "a", "a")])
    assert model.message is None
