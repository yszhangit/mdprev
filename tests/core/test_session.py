"""Window state decisions shared by every front end."""

from datetime import datetime, timezone

from mdprev.core import session
from mdprev.core.git_history import WORKING_COPY, Commit


def _commit(sha="a1b2c3d" + "0" * 33):
    return Commit(sha=sha, short_sha=sha[:7], summary="Notes", author="A",
                  when=datetime(2026, 9, 2, tzinfo=timezone.utc), path="doc.md")


def test_window_titles_for_the_working_copy():
    assert session.window_titles("doc.md", WORKING_COPY, None, "rendered") == ("doc.md", None)


def test_window_titles_for_a_commit():
    assert session.window_titles("doc.md", _commit(), None, "diff") == (
        "doc.md — a1b2c3d", "a1b2c3d · Sep 2, 2026",
    )


def test_window_titles_for_a_comparison():
    base = _commit("9f8e7d6" + "0" * 33)

    assert session.window_titles("doc.md", WORKING_COPY, base, "side-by-side") == (
        "doc.md — 9f8e7d6 → Working copy", "9f8e7d6 → Working copy",
    )


def test_window_titles_ignore_the_base_in_rendered_mode():
    assert session.window_titles("doc.md", WORKING_COPY, _commit(), "rendered") == (
        "doc.md", None,
    )


def test_view_changed_ignores_base_in_rendered_mode():
    commit = _commit()
    assert session.view_changed(WORKING_COPY, None, WORKING_COPY, commit, "rendered") is False


def test_view_changed_honors_base_outside_rendered_mode():
    commit = _commit()
    assert session.view_changed(WORKING_COPY, None, WORKING_COPY, commit, "diff") is True


def test_view_changed_when_target_differs():
    commit = _commit()
    assert session.view_changed(WORKING_COPY, None, commit, None, "rendered") is True
    assert session.view_changed(WORKING_COPY, None, commit, None, "diff") is True


def test_view_changed_false_for_the_same_target_and_base():
    commit = _commit()
    assert session.view_changed(WORKING_COPY, commit, WORKING_COPY, commit, "diff") is False


def test_reloads_on_save_when_working_copy_is_the_target():
    for mode in ("rendered", "diff", "side-by-side"):
        assert session.reloads_on_save(WORKING_COPY, None, mode) is True
        assert session.reloads_on_save(WORKING_COPY, _commit(), mode) is True


def test_reloads_on_save_ignores_a_working_copy_base_in_rendered_mode():
    commit = _commit()
    assert session.reloads_on_save(commit, WORKING_COPY, "rendered") is False
    assert session.reloads_on_save(commit, WORKING_COPY, "diff") is True
    assert session.reloads_on_save(commit, WORKING_COPY, "side-by-side") is True


def test_reloads_on_save_false_without_a_working_copy_on_screen():
    commit = _commit()
    other = _commit("9f8e7d6" + "0" * 33)
    assert session.reloads_on_save(commit, other, "diff") is False
    assert session.reloads_on_save(commit, None, "diff") is False


def test_zoom_steps_are_clamped():
    assert session.zoom_in(1.0) == 1.1
    assert session.zoom_in(3.0) == 3.0
    assert session.zoom_out(0.5) == 0.5
    assert round(session.zoom_out(1.0), 2) == 0.9


def test_build_html_renders_the_working_copy(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello\n", encoding="utf-8")

    html = session.build_html(doc, None, WORKING_COPY, None, "rendered", "system", "system")

    assert "Hello</h1>" in html


def test_build_html_turns_read_failures_into_an_error_document(tmp_path):
    html = session.build_html(
        tmp_path / "missing.md", None, WORKING_COPY, None, "rendered", "system", "system"
    )

    assert "Unable to preview file" in html
    assert "missing.md" in html


def test_build_html_without_a_repository_ignores_diff_mode(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("plain\n", encoding="utf-8")

    html = session.build_html(doc, None, WORKING_COPY, None, "diff", "system", "system")

    assert "<p>plain</p>" in html


def test_base_uri_is_the_document_directory_with_a_trailing_slash(tmp_path):
    uri = session.base_uri(tmp_path / "doc.md")

    assert uri == tmp_path.as_uri() + "/"
