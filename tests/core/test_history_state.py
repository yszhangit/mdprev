"""Selection and pin rules behind the git history sidebar."""

from datetime import datetime, timezone

from mdprev.core.git_history import WORKING_COPY, Commit
from mdprev.core.history_state import HistorySelection


def _commit(sha):
    return Commit(sha=sha * 40, short_sha=sha * 7, summary="s", author="A",
                  when=datetime(2026, 9, 2, tzinfo=timezone.utc), path="doc.md")


A, B = _commit("a"), _commit("b")


def _state(loaded=2, has_more=False, modified=False):
    state = HistorySelection()
    state.update(loaded, has_more, modified)
    return state


def test_starts_on_the_working_copy_in_rendered_mode():
    assert HistorySelection().emit() == (WORKING_COPY, None, "rendered")


def test_selecting_a_revision_reports_it_without_a_base():
    state = _state()
    state.select(A)

    assert state.emit() == (A, None, "rendered")


def test_a_pin_becomes_the_base_of_other_selections():
    state = _state()
    state.toggle_pin(A)
    assert state.update(2, False, False) is False  # pinning alone changes nothing
    state.select(B)

    assert state.emit() == (B, A, "rendered")


def test_selecting_the_pinned_revision_uses_the_implicit_base():
    state = _state()
    state.toggle_pin(A)
    state.select(A)

    assert state.emit() == (A, None, "rendered")


def test_toggling_the_same_pin_unpins_and_asks_to_emit_if_it_was_shown():
    state = _state()
    state.toggle_pin(A)
    state.select(B)
    state.emit()

    state.toggle_pin(A)

    assert state.pinned is None
    assert state.update(2, False, False) is True
    assert state.emit() == (B, None, "rendered")
    assert state.update(2, False, False) is False


def test_set_mode_reports_only_real_changes():
    state = _state()

    assert state.set_mode("rendered") is False
    assert state.set_mode("diff") is True
    assert state.emit() == (WORKING_COPY, None, "diff")


def test_clear_pin_reports_whether_there_was_one():
    state = _state()
    assert state.clear_pin() is False
    state.toggle_pin(A)

    assert state.clear_pin() is True
    assert state.pinned is None


def test_pins_need_two_versions_to_compare():
    single = _state(loaded=1)
    assert single.pins_available is False
    assert single.pin_visible(A) is False

    assert _state(loaded=1, modified=True).pins_available is True
    assert _state(loaded=1, has_more=True).pins_available is True


def test_the_working_copy_pin_needs_uncommitted_changes():
    assert _state(modified=False).pin_visible(WORKING_COPY) is False
    assert _state(modified=True).pin_visible(WORKING_COPY) is True
    assert _state(modified=False).pin_visible(A) is True


def test_a_working_copy_pin_is_dropped_once_the_file_matches_head():
    state = _state(modified=True)
    state.toggle_pin(WORKING_COPY)
    state.select(A)
    state.emit()

    assert state.update(2, False, False) is True
    assert state.pinned is None
    assert state.emit() == (A, None, "rendered")


def test_a_pin_is_dropped_when_comparison_becomes_impossible():
    state = _state(loaded=2)
    state.toggle_pin(A)

    state.update(1, False, False)

    assert state.pinned is None


# -- HistoryModel, against real temporary repositories --------------------

import pytest  # noqa: E402

from mdprev.core.history_state import HistoryModel, Row, revision_key  # noqa: E402

pygit2 = pytest.importorskip("pygit2")


def _repo_with_commits(tmp_path, count):
    repo = pygit2.init_repository(str(tmp_path))
    doc = tmp_path / "doc.md"
    for n in range(count):
        doc.write_text(f"version {n}\n", encoding="utf-8")
        repo.index.add("doc.md")
        repo.index.write()
        tree = repo.index.write_tree()
        signature = pygit2.Signature("Test Author", "t@example.com", 1700000000 + n, 0)
        parents = [] if repo.head_is_unborn else [repo.head.target]
        repo.create_commit("HEAD", signature, signature, f"v{n}", tree, parents)
    return repo, doc


def test_revision_key_names_rows():
    assert revision_key(WORKING_COPY) == "working"
    assert revision_key(A) == A.sha


def test_model_outside_a_repository_says_so(tmp_path):
    model = HistoryModel()
    model.load(None, tmp_path / "doc.md", 10)

    assert model.has_repository is False
    assert model.rows() == [Row("revision", WORKING_COPY), Row("message", text="Not in a git repository")]


def test_model_for_an_untracked_file_says_so(tmp_path):
    repo, _doc = _repo_with_commits(tmp_path, 1)
    other = tmp_path / "other.md"
    other.write_text("x\n", encoding="utf-8")

    model = HistoryModel()
    model.load(repo, other, 10)

    assert model.rows()[-1] == Row("message", text="Not tracked in this repository")


def test_model_pages_history_with_show_more(tmp_path):
    repo, doc = _repo_with_commits(tmp_path, 3)
    model = HistoryModel()
    model.load(repo, doc, 2)

    rows = model.rows()
    assert [row.kind for row in rows] == ["revision", "revision", "revision", "more"]
    assert [row.revision.summary for row in rows[1:3]] == ["v2", "v1"]

    model.load_more()

    rows = model.rows()
    assert [row.kind for row in rows] == ["revision"] * 4
    assert rows[-1].revision.summary == "v0"


def test_model_keeps_an_off_page_selection_listed(tmp_path):
    repo, doc = _repo_with_commits(tmp_path, 3)
    model = HistoryModel()
    model.load(repo, doc, 1)
    model.load_more()
    model.load_more()
    oldest = model.commits[-1]
    model.selection.select(oldest)

    model.load(repo, doc, 1)  # the sidebar was hidden and reshown

    revisions = [row.revision for row in model.rows() if row.kind == "revision"]
    assert revisions[1] == oldest


def test_model_tracks_modification_and_stats(tmp_path):
    repo, doc = _repo_with_commits(tmp_path, 2)
    model = HistoryModel()
    model.load(repo, doc, 10)
    model.refresh_status()
    assert model.modified is False

    doc.write_text("changed text here\n", encoding="utf-8")
    model.refresh_status()

    assert model.modified is True
    assert model.working_stats().words == 3
    assert model.commit_stats(model.commits[0]).words == 2
    assert model.update_pins() is False
    assert model.selection.pin_visible(WORKING_COPY) is True


def test_model_hides_working_stats_when_the_file_vanishes(tmp_path):
    repo, doc = _repo_with_commits(tmp_path, 1)
    model = HistoryModel()
    model.load(repo, doc, 10)
    doc.unlink()

    assert model.working_stats() is None
