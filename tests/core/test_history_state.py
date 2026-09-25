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
