"""History sidebar behavior, against real temporary repositories."""

import pytest

pygit2 = pytest.importorskip("pygit2")

from mdprev.git_history import WORKING_COPY  # noqa: E402
from mdprev.sidebar import HistorySidebar  # noqa: E402


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
