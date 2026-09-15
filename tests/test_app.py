import mdprev.app as app_module
from gi.repository import Gtk


def _buttons(row):
    buttons = []
    child = row.get_first_child()
    while child is not None:
        buttons.append(child)
        child = child.get_next_sibling()
    return buttons


CHOICES = [("light", "Light", None), ("dark", "Dark", "Dark palette")]


def test_choice_row_activates_current_key(gtk_display):
    row = app_module.choice_row(CHOICES, "dark", lambda _key: None)

    buttons = _buttons(row)
    assert [button.get_label() for button in buttons] == ["Light", "Dark"]
    assert [button.get_active() for button in buttons] == [False, True]
    assert buttons[1].get_tooltip_text() == "Dark palette"
    assert row.has_css_class("linked")


def test_choice_row_reports_only_newly_chosen_key(gtk_display):
    chosen = []
    row = app_module.choice_row(CHOICES, "light", chosen.append)
    light, dark = _buttons(row)

    dark.set_active(True)
    light.set_active(True)

    # Deactivating the previous button must not report its key.
    assert chosen == ["dark", "light"]


def test_choice_row_has_no_nested_popup(gtk_display):
    # A popup inside the display-options popover breaks its autohide on
    # Wayland (GTK #4369), so the row must be plain buttons.
    row = app_module.choice_row(CHOICES, "light", lambda _key: None)

    assert all(type(button) is Gtk.ToggleButton for button in _buttons(row))


def test_main_forwards_process_arguments(monkeypatch):
    received = []

    class FakeApplication:
        def run(self, argv):
            received.extend(argv)
            return 0

    monkeypatch.setattr(app_module, "MdPrevApplication", FakeApplication)
    monkeypatch.setattr(app_module.sys, "argv", ["mdprev", "/tmp/example.md"])

    assert app_module.main() == 0
    assert received == ["mdprev", "/tmp/example.md"]


from datetime import datetime, timezone  # noqa: E402

from mdprev.git_history import WORKING_COPY, Commit  # noqa: E402


def _commit(sha="a1b2c3d" + "0" * 33):
    return Commit(sha=sha, short_sha=sha[:7], summary="Notes", author="A",
                  when=datetime(2026, 9, 2, tzinfo=timezone.utc), path="doc.md")


def test_window_titles_for_the_working_copy():
    assert app_module.window_titles("doc.md", WORKING_COPY, None, "rendered") == ("doc.md", None)


def test_window_titles_for_a_commit():
    assert app_module.window_titles("doc.md", _commit(), None, "diff") == (
        "doc.md — a1b2c3d", "a1b2c3d · Sep 2, 2026",
    )


def test_window_titles_for_a_comparison():
    base = _commit("9f8e7d6" + "0" * 33)

    assert app_module.window_titles("doc.md", WORKING_COPY, base, "side-by-side") == (
        "doc.md — 9f8e7d6 → Working copy", "9f8e7d6 → Working copy",
    )


def test_window_titles_ignore_the_base_in_rendered_mode():
    assert app_module.window_titles("doc.md", WORKING_COPY, _commit(), "rendered") == (
        "doc.md", None,
    )


def test_view_changed_ignores_base_in_rendered_mode():
    commit = _commit()
    assert app_module.view_changed(WORKING_COPY, None, WORKING_COPY, commit, "rendered") is False


def test_view_changed_honors_base_outside_rendered_mode():
    commit = _commit()
    assert app_module.view_changed(WORKING_COPY, None, WORKING_COPY, commit, "diff") is True


def test_view_changed_when_target_differs():
    commit = _commit()
    assert app_module.view_changed(WORKING_COPY, None, commit, None, "rendered") is True
    assert app_module.view_changed(WORKING_COPY, None, commit, None, "diff") is True


def test_view_changed_false_for_the_same_target_and_base():
    commit = _commit()
    assert app_module.view_changed(WORKING_COPY, commit, WORKING_COPY, commit, "diff") is False


def test_reloads_on_save_when_working_copy_is_the_target():
    for mode in ("rendered", "diff", "side-by-side"):
        assert app_module.reloads_on_save(WORKING_COPY, None, mode) is True
        assert app_module.reloads_on_save(WORKING_COPY, _commit(), mode) is True


def test_reloads_on_save_ignores_a_working_copy_base_in_rendered_mode():
    commit = _commit()
    assert app_module.reloads_on_save(commit, WORKING_COPY, "rendered") is False
    assert app_module.reloads_on_save(commit, WORKING_COPY, "diff") is True
    assert app_module.reloads_on_save(commit, WORKING_COPY, "side-by-side") is True


def test_reloads_on_save_false_without_a_working_copy_on_screen():
    commit = _commit()
    other = _commit("9f8e7d6" + "0" * 33)
    assert app_module.reloads_on_save(commit, other, "diff") is False
    assert app_module.reloads_on_save(commit, None, "diff") is False
