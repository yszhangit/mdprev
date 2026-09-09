"""Repository history queries, tested against real temporary repositories."""

import dataclasses
import shutil
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


def test_find_repository_rejects_a_bare_repository(tmp_path):
    bare = tmp_path / "bare.git"
    pygit2.init_repository(str(bare), bare=True)

    assert git_history.find_repository(bare / "doc.md") is None


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


def test_history_returns_commits_newest_first(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "two\n", "Second", when=1700000100)

    result = git_history.history(repo, workdir / "doc.md")

    assert [c.summary for c in result.commits] == ["Second", "First"]
    assert result.truncated is False
    assert result.next_cursor is None


def test_history_records_commit_metadata(repo_factory):
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", "one\n", "Subject line\n\nBody\n")

    commit = git_history.history(repo, workdir / "doc.md").commits[0]

    assert commit.sha == sha
    assert commit.short_sha == sha[:7]
    assert commit.summary == "Subject line"
    assert commit.author == "Test Author"
    assert commit.path == "doc.md"
    assert commit.when.year == 2023


def test_history_skips_commits_that_do_not_touch_the_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Touches doc")
    commit_file(repo, workdir, "other.md", "x\n", "Touches other")

    result = git_history.history(repo, workdir / "doc.md")

    assert [c.summary for c in result.commits] == ["Touches doc"]


def test_history_includes_the_commit_that_deletes_the_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Add doc")
    (workdir / "doc.md").unlink()
    repo.index.remove("doc.md")
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000200, 0)
    repo.create_commit("HEAD", signature, signature, "Delete doc", tree, [repo.head.target])

    result = git_history.history(repo, workdir / "doc.md")

    assert [c.summary for c in result.commits] == ["Delete doc", "Add doc"]


def test_history_is_empty_for_an_unborn_head(repo_factory):
    repo, workdir = repo_factory()
    (workdir / "doc.md").write_text("# Title\n", encoding="utf-8")

    result = git_history.history(repo, workdir / "doc.md")

    assert result.commits == []
    assert result.next_cursor is None


def test_history_is_empty_for_an_untracked_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Add doc")
    (workdir / "scratch.md").write_text("# Scratch\n", encoding="utf-8")

    assert git_history.history(repo, workdir / "scratch.md").commits == []


def test_history_honors_the_limit_and_reports_a_cursor(repo_factory):
    repo, workdir = repo_factory()
    for index in range(5):
        commit_file(repo, workdir, "doc.md", f"line {index}\n", f"Commit {index}",
                    when=1700000000 + index)

    result = git_history.history(repo, workdir / "doc.md", limit=2)

    assert [c.summary for c in result.commits] == ["Commit 4", "Commit 3"]
    assert result.next_cursor is not None
    assert result.next_cursor.sha == result.commits[-1].sha
    assert result.next_cursor.path == "doc.md"


def test_history_resumes_after_a_cursor_without_gaps_or_repeats(repo_factory):
    repo, workdir = repo_factory()
    for index in range(5):
        commit_file(repo, workdir, "doc.md", f"line {index}\n", f"Commit {index}",
                    when=1700000000 + index)

    first = git_history.history(repo, workdir / "doc.md", limit=2)
    second = git_history.history(repo, workdir / "doc.md", limit=2, after=first.next_cursor)

    assert [c.summary for c in second.commits] == ["Commit 2", "Commit 1"]
    assert second.next_cursor is not None


def test_history_cursor_is_none_at_the_end_of_history(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Only")

    result = git_history.history(repo, workdir / "doc.md", limit=10)

    assert result.next_cursor is None


def test_history_truncates_at_the_scan_ceiling(repo_factory, monkeypatch):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Touches doc")
    for index in range(4):
        commit_file(repo, workdir, "other.md", f"{index}\n", f"Noise {index}")
    monkeypatch.setattr(git_history, "MAX_SCAN", 3)

    result = git_history.history(repo, workdir / "doc.md")

    assert result.truncated is True
    assert result.commits == []
    # A truncated walk must stay resumable, or "Show more" dead-ends.
    assert result.next_cursor is not None


def test_history_resumes_after_a_truncated_walk(repo_factory, monkeypatch):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Touches doc", when=1700000000)
    for index in range(4):
        commit_file(repo, workdir, "other.md", f"{index}\n", f"Noise {index}",
                    when=1700000100 + index)
    monkeypatch.setattr(git_history, "MAX_SCAN", 3)

    first = git_history.history(repo, workdir / "doc.md")
    second = git_history.history(repo, workdir / "doc.md", after=first.next_cursor)

    assert [c.summary for c in second.commits] == ["Touches doc"]


def rename_file(repo, workdir, old_relpath, new_relpath, message, when=1700000300):
    """Rename a tracked file and commit the rename."""
    (workdir / old_relpath).rename(workdir / new_relpath)
    repo.index.remove(old_relpath)
    repo.index.add(new_relpath)
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    oid = repo.create_commit("HEAD", signature, signature, message, tree, [repo.head.target])
    return str(oid)


def rename_and_edit_file(repo, workdir, old_relpath, new_relpath, content, message,
                          when=1700000300):
    """Rename a tracked file and change its content in the same commit."""
    (workdir / old_relpath).rename(workdir / new_relpath)
    (workdir / new_relpath).write_bytes(
        content if isinstance(content, bytes) else content.encode("utf-8")
    )
    repo.index.remove(old_relpath)
    repo.index.add(new_relpath)
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    oid = repo.create_commit("HEAD", signature, signature, message, tree, [repo.head.target])
    return str(oid)


def test_history_follows_a_rename(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)
    commit_file(repo, workdir, "new.md", "shared content\n" * 20 + "more\n", "Edit new",
                when=1700000200)

    result = git_history.history(repo, workdir / "new.md")

    assert [c.summary for c in result.commits] == ["Edit new", "Rename to new", "Add old"]


def test_history_reports_the_path_in_force_at_each_commit(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)

    result = git_history.history(repo, workdir / "new.md")

    by_summary = {c.summary: c.path for c in result.commits}
    assert by_summary["Rename to new"] == "new.md"
    assert by_summary["Add old"] == "old.md"


def test_history_cursor_carries_the_path_across_a_rename(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)

    first = git_history.history(repo, workdir / "new.md", limit=1)

    assert first.next_cursor.path == "old.md"
    second = git_history.history(repo, workdir / "new.md", limit=1, after=first.next_cursor)
    assert [c.summary for c in second.commits] == ["Add old"]


def test_history_follows_a_nested_path(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "docs/guide/doc.md", "one\n", "First", when=1700000000)
    commit_file(repo, workdir, "docs/guide/doc.md", "two\n", "Second", when=1700000100)
    commit_file(repo, workdir, "docs/other.md", "x\n", "Unrelated", when=1700000200)

    result = git_history.history(repo, workdir / "docs" / "guide" / "doc.md")

    assert [c.summary for c in result.commits] == ["Second", "First"]
    assert result.commits[0].path == "docs/guide/doc.md"


def test_file_at_returns_the_content_of_that_revision(repo_factory):
    repo, workdir = repo_factory()
    first = commit_file(repo, workdir, "doc.md", "# One\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "# Two\n", "Second", when=1700000100)

    assert git_history.file_at(repo, first, "doc.md") == "# One\n"


def test_file_at_reads_under_the_historic_name(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)

    oldest = git_history.history(repo, workdir / "new.md").commits[-1]

    assert git_history.file_at(repo, oldest.sha, oldest.path).startswith("shared content")


def test_file_at_rejects_a_revision_that_lacks_the_file(repo_factory):
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", "# One\n", "First")

    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(repo, sha, "absent.md")


def test_file_at_rejects_an_unparseable_revision(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "# One\n", "First")

    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(repo, "not-a-sha", "doc.md")


def test_file_at_rejects_content_that_is_not_utf8(repo_factory):
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", b"\xff\xfe invalid\n", "Binary")

    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(repo, sha, "doc.md")


def test_patch_for_shows_added_and_removed_lines(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    second = commit_file(repo, workdir, "doc.md", "two\n", "Second", when=1700000100)

    patch = git_history.patch_for(repo, second, "doc.md")

    assert "@@" in patch
    assert "-one" in patch
    assert "+two" in patch


def test_patch_for_a_root_commit_shows_the_whole_file_as_added(repo_factory):
    repo, workdir = repo_factory()
    first = commit_file(repo, workdir, "doc.md", "one\ntwo\n", "First")

    patch = git_history.patch_for(repo, first, "doc.md")

    assert "+one" in patch
    assert "+two" in patch
    assert "-one" not in patch


def test_patch_for_a_rename_diffs_against_the_old_name(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_sha = rename_file(repo, workdir, "old.md", "new.md", "Rename", when=1700000100)

    patch = git_history.patch_for(repo, rename_sha, "new.md")

    assert "old.md" in patch


def test_patch_for_a_rename_with_a_content_edit_shows_both(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_sha = rename_and_edit_file(
        repo, workdir, "old.md", "new.md", "shared content\n" * 20 + "extra line\n",
        "Rename and edit", when=1700000100,
    )

    patch = git_history.patch_for(repo, rename_sha, "new.md")

    assert "old.md" in patch
    assert "@@" in patch
    assert "+extra line" in patch


def test_patch_for_a_merge_uses_the_first_parent(repo_factory):
    repo, workdir = repo_factory()
    base = commit_file(repo, workdir, "doc.md", "base\n", "Base", when=1700000000)
    repo.branches.local.create("side", repo[base])
    commit_file(repo, workdir, "doc.md", "main\n", "Main edit", when=1700000100)
    main_tip = repo.head.target
    side_tip = repo.branches.local["side"].target
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000200, 0)
    merge_sha = str(repo.create_commit(
        "HEAD", signature, signature, "Merge", repo[main_tip].tree_id,
        [main_tip, side_tip],
    ))

    patch = git_history.patch_for(repo, merge_sha, "doc.md")

    assert patch == ""


def test_working_patch_shows_uncommitted_changes(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").write_text("edited\n", encoding="utf-8")

    patch = git_history.working_patch(repo, workdir / "doc.md")

    assert "-committed" in patch
    assert "+edited" in patch


def test_working_patch_is_empty_for_a_clean_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")

    assert git_history.working_patch(repo, workdir / "doc.md") == ""


def test_working_patch_reports_an_unreadable_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").unlink()

    with pytest.raises(git_history.GitHistoryError):
        git_history.working_patch(repo, workdir / "doc.md")


def test_is_modified_is_false_on_a_clean_checkout(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")

    assert git_history.is_modified(repo, workdir / "doc.md") is False


def test_is_modified_is_true_for_an_unstaged_edit(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").write_text("edited\n", encoding="utf-8")

    assert git_history.is_modified(repo, workdir / "doc.md") is True


def test_is_modified_is_true_for_a_staged_but_uncommitted_edit(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").write_text("staged\n", encoding="utf-8")
    repo.index.add("doc.md")
    repo.index.write()

    assert git_history.is_modified(repo, workdir / "doc.md") is True


def test_is_modified_is_false_for_an_untracked_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "scratch.md").write_text("# Scratch\n", encoding="utf-8")

    assert git_history.is_modified(repo, workdir / "scratch.md") is False


def test_is_modified_is_false_for_a_path_outside_the_repository(repo_factory, tmp_path):
    repo, _workdir = repo_factory()
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# Title\n", encoding="utf-8")

    assert git_history.is_modified(repo, outside) is False


def test_expected_libgit2_failures_convert_to_git_history_error(repo_factory):
    """A repository that vanishes mid-session must not leak raw libgit2
    errors (GitError/KeyError) out of these four entry points. Design §5.5
    promises GitHistoryError from every one of them; both consumers
    (sidebar._fetch, app.load_document) catch only that type. A fresh
    Repository handle is opened before deletion so libgit2's in-process
    object cache from the writes above cannot mask the failure.
    """
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", "one\n", "First")
    fresh = pygit2.Repository(str(workdir))
    shutil.rmtree(workdir)

    with pytest.raises(git_history.GitHistoryError):
        git_history.history(fresh, workdir / "doc.md")
    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(fresh, sha, "doc.md")
    with pytest.raises(git_history.GitHistoryError):
        git_history.patch_for(fresh, sha, "doc.md")
    with pytest.raises(git_history.GitHistoryError):
        git_history.working_patch(fresh, workdir / "doc.md")
