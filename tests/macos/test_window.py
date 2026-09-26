"""The macOS window, driven without the event loop."""

from pathlib import Path

import pytest
from Foundation import NSURL, NSIndexSet
from WebKit import WKNavigationTypeLinkActivated, WKNavigationTypeOther

from macos_helpers import spin, wait_for
from mdprev.core.git_history import WORKING_COPY
from mdprev.core.preferences import save_preferences
from mdprev.macos.window import PreviewWindow

pygit2 = pytest.importorskip("pygit2")


def evaluate(window, script):
    result = []
    window._webview.evaluateJavaScript_completionHandler_(
        script, lambda value, error: result.append(value)
    )
    wait_for(lambda: result)
    return result[0] if result else None


def page_ready(window) -> bool:
    url = window._webview.URL()
    return (
        not window._webview.isLoading()
        and url is not None
        and window._is_view_file(url)
    )


def loaded_text(window, selector="h1"):
    return evaluate(window, f"document.querySelector({selector!r})?.textContent")


class FakeAction:
    def __init__(self, uri, gesture):
        self._url = NSURL.URLWithString_(uri) if uri else None
        self._type = WKNavigationTypeLinkActivated if gesture else WKNavigationTypeOther

    def request(self):
        return self

    def URL(self):
        return self._url

    def navigationType(self):
        return self._type


@pytest.fixture
def open_window(isolated_prefs, fake_app):
    windows = []

    def make(path):
        window = PreviewWindow(fake_app, path)
        windows.append(window)
        assert wait_for(lambda: page_ready(window))
        return window

    yield make
    for window in windows:
        window.window.close()
    spin(0.1)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_renders_the_document_and_its_local_images(open_window, tmp_path):
    folder = tmp_path / "notes é"
    (folder / "img").mkdir(parents=True)
    (tmp_path / "shared").mkdir()
    (folder / "img" / "a.png").write_bytes(_PNG)
    (tmp_path / "shared" / "b.png").write_bytes(_PNG)
    doc = write(folder / "my doc.md", "# Hello\n\n![a](img/a.png) ![b](../shared/b.png)\n")

    window = open_window(doc)

    assert loaded_text(window) == "Hello"
    widths = "[...document.images].map(i => i.naturalWidth).join()"
    assert wait_for(lambda: evaluate(window, widths) == "1,1")
    assert window.window.title() == "my doc.md"


def test_page_javascript_stays_disabled(open_window, tmp_path):
    doc = write(tmp_path / "doc.md", "# T\n\n<script>document.title='pwned'</script>\n")

    window = open_window(doc)

    assert evaluate(window, "document.title") != "pwned"
    assert window._webview.configuration().defaultWebpagePreferences().allowsContentJavaScript() is False


def test_saves_reload_the_preview(open_window, tmp_path):
    doc = write(tmp_path / "doc.md", "# One\n")
    window = open_window(doc)

    write(doc, "# Two\n")

    assert wait_for(lambda: loaded_text(window) == "Two")

    replacement = write(tmp_path / ".doc.md.tmp", "# Three\n")
    replacement.replace(doc)

    assert wait_for(lambda: loaded_text(window) == "Three")


def test_reload_keeps_the_reading_position(open_window, tmp_path):
    body = "\n\n".join(f"Paragraph {n}" for n in range(200))
    doc = write(tmp_path / "doc.md", f"# Long\n\n{body}\n")
    window = open_window(doc)
    evaluate(window, "window.scrollTo(0, 1500)")
    assert wait_for(lambda: evaluate(window, "window.scrollY") == 1500)

    write(doc, f"# Longer\n\n{body}\n")

    assert wait_for(lambda: loaded_text(window) == "Longer")
    assert wait_for(lambda: evaluate(window, "window.scrollY") == 1500)


def test_navigation_policy(open_window, tmp_path):
    doc = write(tmp_path / "doc.md", "# T\n")
    other = write(tmp_path / "other.md", "# O\n")
    window = open_window(doc)
    opened = []
    window.app.open_path = opened.append

    assert window.decide_navigation(FakeAction(window._view_file.as_uri(), False)) is True
    assert window.decide_navigation(FakeAction(other.as_uri(), True)) is False
    assert opened == [other.resolve()]
    assert window.decide_navigation(FakeAction("javascript:alert(1)", True)) is False
    # In-document anchors scroll in place rather than navigating away.
    assert window.decide_navigation(FakeAction(tmp_path.as_uri() + "/#t", True)) is False


def test_zoom_font_and_theme_persist(open_window, tmp_path):
    from mdprev.core.preferences import load_preferences

    window = open_window(write(tmp_path / "doc.md", "# T\n"))

    window.zoom_in()
    window.set_font("serif")
    window.set_theme("sepia")

    prefs = load_preferences()
    assert prefs["zoom_level"] == pytest.approx(1.1)
    assert (prefs["font"], prefs["theme"]) == ("serif", "sepia")
    assert wait_for(lambda: evaluate(window, "document.documentElement.dataset.theme") == "sepia")


def _repo(tmp_path, versions):
    repo = pygit2.init_repository(str(tmp_path))
    doc = tmp_path / "doc.md"
    for n, text in enumerate(versions):
        write(doc, text)
        repo.index.add("doc.md")
        repo.index.write()
        tree = repo.index.write_tree()
        sig = pygit2.Signature("A", "a@example.com", 1700000000 + n, 0)
        parents = [] if repo.head_is_unborn else [repo.head.target]
        repo.create_commit("HEAD", sig, sig, f"v{n}", tree, parents)
    return doc


def test_history_sidebar_selects_compares_and_escapes(open_window, tmp_path):
    save_preferences(sidebar_visible=True)
    doc = _repo(tmp_path, ["# First\n", "# Second\n"])
    window = open_window(doc)
    sidebar = window.sidebar

    assert window.sidebar_visible
    assert sidebar.row_count() == 3

    sidebar._table.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(2), False)
    assert wait_for(lambda: loaded_text(window) == "First")
    assert window.window.subtitle().startswith(window.target.short_sha)

    sidebar._mode_control.setSelectedSegment_(1)
    sidebar.mode_changed()
    assert wait_for(lambda: evaluate(window, "document.querySelectorAll('.compare').length") == 1)

    window.show_working_copy()
    assert window.target == WORKING_COPY
    assert wait_for(lambda: window.window.subtitle() == "")


def test_closing_saves_the_window_size_and_cleans_up(open_window, tmp_path, fake_app):
    from mdprev.core.preferences import load_preferences

    window = open_window(write(tmp_path / "doc.md", "# T\n"))
    window.window.setContentSize_((800, 500))
    scratch = window._scratch

    window.window.close()

    prefs = load_preferences()
    assert (prefs["window_width"], prefs["window_height"]) == (800, 500)
    assert not scratch.exists()
    assert fake_app.closed == [window]


# A 1x1 PNG.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201"
    "e2b1c1a00000000049454e44ae426082"
)
