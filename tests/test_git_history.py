"""Repository history queries, tested against real temporary repositories."""

import dataclasses
from pathlib import Path

import pytest

pygit2 = pytest.importorskip("pygit2")

from mdprev import git_history  # noqa: E402


def test_module_reports_pygit2_available():
    assert git_history.AVAILABLE is True


def test_git_history_error_is_a_runtime_error():
    assert issubclass(git_history.GitHistoryError, RuntimeError)


def test_commit_record_is_frozen():
    commit = git_history.Commit(
        sha="0" * 40,
        short_sha="0" * 7,
        summary="Subject",
        author="Test Author",
        when=None,
        path="doc.md",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        commit.sha = "1" * 40


def test_history_defaults_to_no_cursor():
    history = git_history.History(commits=[], truncated=False, next_cursor=None)
    assert history.commits == []
    assert history.truncated is False
    assert history.next_cursor is None


def test_max_scan_is_bounded():
    assert git_history.MAX_SCAN == 2000


@pytest.fixture
def repo_factory(tmp_path):
    """Build real temporary repositories; libgit2 behavior is what we test."""

    def make(name="repo"):
        workdir = tmp_path / name
        workdir.mkdir()
        repo = pygit2.init_repository(str(workdir))
        return repo, workdir

    return make


def commit_file(repo, workdir, relpath, content, message, when=1700000000):
    """Write, stage, and commit one file. Returns the new commit's sha."""
    file_path = workdir / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    repo.index.add(relpath)
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    oid = repo.create_commit("HEAD", signature, signature, message, tree, parents)
    return str(oid)


def test_find_repository_locates_the_enclosing_repository(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "# Title\n", "Add doc")

    found = git_history.find_repository(workdir / "doc.md")

    assert found is not None
    assert Path(found.workdir).resolve() == workdir.resolve()


def test_find_repository_locates_from_a_subdirectory(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "docs/doc.md", "# Title\n", "Add doc")

    found = git_history.find_repository(workdir / "docs" / "doc.md")

    assert found is not None


def test_find_repository_returns_none_outside_a_repository(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "doc.md").write_text("# Title\n", encoding="utf-8")

    assert git_history.find_repository(loose / "doc.md") is None


def test_relative_path_is_repo_relative_and_posix(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "docs/doc.md", "# Title\n", "Add doc")

    assert git_history._relative_path(repo, workdir / "docs" / "doc.md") == "docs/doc.md"


def test_relative_path_rejects_a_path_outside_the_repository(repo_factory, tmp_path):
    repo, _workdir = repo_factory()
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# Title\n", encoding="utf-8")

    with pytest.raises(git_history.GitHistoryError):
        git_history._relative_path(repo, outside)


def test_is_tracked_distinguishes_tracked_from_untracked(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "# Title\n", "Add doc")
    (workdir / "scratch.md").write_text("# Scratch\n", encoding="utf-8")

    assert git_history.is_tracked(repo, workdir / "doc.md") is True
    assert git_history.is_tracked(repo, workdir / "scratch.md") is False
