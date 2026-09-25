"""Navigation policy for links clicked (or loaded) in the preview."""

from pathlib import Path

from mdprev.core.navigation import (
    Allow,
    Block,
    OpenDocument,
    OpenExternal,
    classify_link,
)


def test_web_links_open_externally_only_on_a_user_gesture(tmp_path):
    for uri in ("https://example.com/", "http://example.com/", "mailto:a@example.com"):
        assert classify_link(uri, tmp_path, True) == OpenExternal(uri)
        assert classify_link(uri, tmp_path, False) == Block()


def test_scheme_matching_is_case_insensitive(tmp_path):
    assert classify_link("HTTPS://example.com/", tmp_path, True) == OpenExternal(
        "HTTPS://example.com/"
    )
    assert classify_link("JavaScript:alert(1)", tmp_path, True) == Block()


def test_the_document_base_load_is_allowed(tmp_path):
    assert classify_link(tmp_path.as_uri() + "/", tmp_path, False) == Allow()


def test_fragment_links_within_the_document_are_allowed(tmp_path):
    assert classify_link(tmp_path.as_uri() + "/#section", tmp_path, True) == Allow()


def test_clicking_the_base_directory_itself_is_blocked(tmp_path):
    assert classify_link(tmp_path.as_uri() + "/", tmp_path, True) == Block()


def test_markdown_links_open_in_mdprev_on_a_user_gesture(tmp_path):
    other = tmp_path / "other doc é.md"
    uri = other.as_uri()

    assert classify_link(uri, tmp_path, True) == OpenDocument(other.resolve())
    assert classify_link(uri, tmp_path, False) == Block()
    upper = tmp_path / "README.MARKDOWN"
    assert classify_link(upper.as_uri(), tmp_path, True) == OpenDocument(upper.resolve())


def test_other_local_files_are_blocked(tmp_path):
    assert classify_link((tmp_path / "image.png").as_uri(), tmp_path, True) == Block()
    assert classify_link(Path("/etc/passwd").as_uri(), tmp_path, True) == Block()


def test_script_and_data_urls_are_blocked(tmp_path):
    assert classify_link("javascript:alert(1)", tmp_path, True) == Block()
    assert classify_link("data:text/html,<b>x</b>", tmp_path, False) == Block()


def test_other_schemes_are_left_to_the_web_view(tmp_path):
    assert classify_link("about:blank", tmp_path, False) == Allow()
    assert classify_link("", tmp_path, False) == Allow()
