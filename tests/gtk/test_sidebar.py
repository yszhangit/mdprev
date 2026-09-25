"""History sidebar behavior, against real temporary repositories."""

import pytest

pygit2 = pytest.importorskip("pygit2")

from mdprev.core.git_history import WORKING_COPY  # noqa: E402
from mdprev.gtk.sidebar import HistorySidebar  # noqa: E402


def visible_pins(sidebar):
    return {key for key, button in sidebar._pin_buttons.items() if button.get_visible()}


def commit_doc(repo, workdir, content, message, when):
    (workdir / "doc.md").write_text(content, encoding="utf-8")
    repo.index.add("doc.md")
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return str(repo.create_commit("HEAD", signature, signature, message, tree, parents))


@pytest.fixture
def repo(tmp_path, gtk_display):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    return pygit2.init_repository(str(workdir)), workdir


def load_sidebar(repo, workdir):
    calls = []
    sidebar = HistorySidebar(lambda target, base, mode: calls.append((target, base, mode)))
    sidebar.load(repo, workdir / "doc.md", 10)
    return sidebar, calls


def test_loading_reports_nothing(repo):
    commit_doc(*repo, "one\n", "First", 1700000000)

    _sidebar, calls = load_sidebar(*repo)

    assert calls == []


def test_mode_switch_offers_three_modes(repo):
    commit_doc(*repo, "one\n", "First", 1700000000)
    sidebar, calls = load_sidebar(*repo)

    assert [button.get_label() for button in sidebar._mode_buttons] == [
        "Rendered", "Diff", "Side by side",
    ]
    sidebar._mode_buttons[2].set_active(True)

    assert calls[-1] == (WORKING_COPY, None, "side-by-side")


def test_selecting_a_commit_reports_its_record(repo):
    sha = commit_doc(*repo, "one\n", "First", 1700000000)
    sidebar, calls = load_sidebar(*repo)

    sidebar._list.select_row(sidebar._rows[sha])

    target, base, mode = calls[-1]
    assert target.sha == sha
    assert (base, mode) == (None, "rendered")


def test_select_working_copy_reports_the_marker(repo):
    sha = commit_doc(*repo, "one\n", "First", 1700000000)
    sidebar, calls = load_sidebar(*repo)
    sidebar._list.select_row(sidebar._rows[sha])

    sidebar.select_working_copy()

    assert calls[-1] == (WORKING_COPY, None, "rendered")


def test_no_pins_for_one_commit_and_a_clean_copy(repo):
    commit_doc(*repo, "one\n", "First", 1700000000)

    sidebar, _calls = load_sidebar(*repo)

    assert visible_pins(sidebar) == set()


def test_uncommitted_changes_make_both_rows_pinnable(repo):
    repo_obj, workdir = repo
    sha = commit_doc(repo_obj, workdir, "one\n", "First", 1700000000)
    (workdir / "doc.md").write_text("changed\n", encoding="utf-8")

    sidebar, _calls = load_sidebar(repo_obj, workdir)

    assert visible_pins(sidebar) == {"working", sha}


def test_clean_copy_row_is_not_pinnable_among_commits(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)

    sidebar, _calls = load_sidebar(*repo)

    assert visible_pins(sidebar) == {first, second}


def test_pinning_alone_reports_nothing(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)

    sidebar._pin_buttons[first].emit("clicked")

    assert calls == []
    assert sidebar._pin_buttons[first].has_css_class("mdprev-pin-active")
    assert sidebar._state.pinned.sha == first


def test_selecting_another_row_compares_against_the_pin(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)
    sidebar._pin_buttons[first].emit("clicked")

    sidebar._list.select_row(sidebar._rows[second])

    target, base, _mode = calls[-1]
    assert (target.sha, base.sha) == (second, first)


def test_selecting_the_pinned_row_uses_the_implicit_base(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)
    sidebar._pin_buttons[first].emit("clicked")

    sidebar._list.select_row(sidebar._rows[first])

    target, base, _mode = calls[-1]
    assert (target.sha, base) == (first, None)


def test_moving_the_pin_keeps_one_pin(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, _calls = load_sidebar(*repo)

    sidebar._pin_buttons[first].emit("clicked")
    sidebar._pin_buttons[second].emit("clicked")

    active = {k for k, b in sidebar._pin_buttons.items() if b.has_css_class("mdprev-pin-active")}
    assert active == {second}


def test_unpinning_the_base_on_screen_rerenders_without_it(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)
    sidebar._pin_buttons[first].emit("clicked")
    sidebar._list.select_row(sidebar._rows[second])

    sidebar._pin_buttons[first].emit("clicked")

    target, base, _mode = calls[-1]
    assert (target.sha, base) == (second, None)
    assert sidebar._state.pinned is None


def test_unpinning_an_unused_pin_reports_nothing(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)

    sidebar._pin_buttons[first].emit("clicked")
    sidebar._pin_buttons[first].emit("clicked")

    assert calls == []


def test_clear_pin(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)

    assert sidebar.clear_pin() is False

    sidebar._pin_buttons[first].emit("clicked")
    sidebar._list.select_row(sidebar._rows[second])
    assert sidebar.clear_pin() is True
    assert calls[-1][1] is None
    assert sidebar._state.pinned is None


def test_working_copy_pin_clears_when_the_file_matches_head_again(repo):
    repo_obj, workdir = repo
    sha = commit_doc(repo_obj, workdir, "one\n", "First", 1700000000)
    (workdir / "doc.md").write_text("changed\n", encoding="utf-8")
    sidebar, calls = load_sidebar(repo_obj, workdir)
    sidebar._pin_buttons["working"].emit("clicked")
    sidebar._list.select_row(sidebar._rows[sha])
    assert calls[-1][1] == WORKING_COPY

    (workdir / "doc.md").write_text("one\n", encoding="utf-8")
    sidebar.refresh_status()

    assert sidebar._state.pinned is None
    assert calls[-1][1] is None
    assert visible_pins(sidebar) == set()


def test_rows_show_stats(repo):
    repo_obj, workdir = repo
    sha = commit_doc(repo_obj, workdir, "one two\n", "First", 1700000000)
    (workdir / "doc.md").write_text("one two three\n", encoding="utf-8")

    sidebar, _calls = load_sidebar(repo_obj, workdir)

    assert sidebar._stats_labels[sha].get_text() == "8 B · 1 line · 2 words"
    assert sidebar._stats_labels["working"].get_text() == "14 B · 1 line · 3 words"


def test_stats_label_hidden_for_binary_content(repo):
    repo_obj, workdir = repo
    (workdir / "doc.md").write_bytes(b"\x00binary")
    repo_obj.index.add("doc.md")
    repo_obj.index.write()
    tree = repo_obj.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000000, 0)
    sha = str(repo_obj.create_commit("HEAD", signature, signature, "Bin", tree, []))

    sidebar, _calls = load_sidebar(repo_obj, workdir)

    assert sidebar._stats_labels[sha].get_visible() is False


def test_refresh_status_survives_a_missing_working_copy_file(repo):
    repo_obj, workdir = repo
    commit_doc(repo_obj, workdir, "one\n", "First", 1700000000)
    sidebar, _calls = load_sidebar(repo_obj, workdir)

    (workdir / "doc.md").unlink()

    sidebar.refresh_status()

    assert sidebar._stats_labels["working"].get_visible() is False
