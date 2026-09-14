"""GTK/WebKit application shell for MdPrev."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, Gtk, Pango, WebKit  # noqa: E402

from . import git_history  # noqa: E402
from .git_history import WORKING_COPY, Commit, Revision  # noqa: E402
from .preferences import load_preferences, save_preferences  # noqa: E402
from .render import (  # noqa: E402
    RenderError,
    error_document,
    read_source,
    render_comparison,
    render_markdown,
)
from .sidebar import HistorySidebar  # noqa: E402


APP_ID = "io.github.yszhangit.mdprev"


def choice_row(
    choices: list[tuple[str, str, str | None]],
    current: str,
    on_change: Callable[[str], None],
) -> Gtk.Box:
    """Return a linked row of toggle buttons with exactly one active.

    Used inside the display-options popover instead of Gtk.DropDown: a
    dropdown's own popup nested in that popover leaves the popover unable to
    close on clicks inside the window on Wayland (GTK #4369).
    """

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    row.add_css_class("linked")
    row.set_homogeneous(True)
    group = None
    for key, label, tooltip in choices:
        button = Gtk.ToggleButton(label=label)
        if tooltip:
            button.set_tooltip_text(tooltip)
        if group is None:
            group = button
        else:
            button.set_group(group)
        button.set_active(key == current)
        # Connected after set_active so building the row reports nothing.
        button.connect(
            "toggled",
            lambda b, key=key: on_change(key) if b.get_active() else None,
        )
        row.append(button)
    return row


def _short(revision: Revision) -> str:
    return revision.short_sha if isinstance(revision, Commit) else "Working copy"


def window_titles(
    name: str, target: Revision, base: Revision | None, mode: str
) -> tuple[str, str | None]:
    """Return the window title and header subtitle (None hides it)."""

    if base is not None and mode != "rendered":
        pair = f"{_short(base)} → {_short(target)}"
        return f"{name} — {pair}", pair
    if isinstance(target, Commit):
        return (
            f"{name} — {target.short_sha}",
            f"{target.short_sha} · {target.when.strftime('%b %-d, %Y')}",
        )
    return name, None


def view_changed(
    old_target: Revision,
    old_base: Revision | None,
    target: Revision,
    base: Revision | None,
    mode: str,
) -> bool:
    """True when the displayed document differs, so scroll must reset.

    Rendered mode shows only the target, so a base-only change there is not a
    document change.  A pure mode change (target and base both unchanged)
    always returns False; the caller re-renders in place for that case.
    """

    if target != old_target:
        return True
    return mode != "rendered" and base != old_base


def reloads_on_save(target: Revision, base: Revision | None, mode: str) -> bool:
    """True when a save to the working copy should refresh what is on screen.

    Rendered mode shows only the target, so a working-copy base is irrelevant
    there; diff and side-by-side show both sides.
    """

    if target == WORKING_COPY:
        return True
    return mode != "rendered" and base == WORKING_COPY


class PreviewWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "MdPrevApplication", path: Path):
        super().__init__(application=app)
        self.app = app
        self.path = path
        self._monitor: Gio.FileMonitor | None = None
        self._reload_source: int = 0
        # Reader state loaded from global user preferences
        prefs = load_preferences()
        self._font: str = prefs.get("font", "system")
        self._theme: str = prefs.get("theme", "system")
        self._zoom_level: float = prefs.get("zoom_level", 1.0)
        self._sidebar_width: int = prefs.get("sidebar_width", 280)
        self._history_limit: int = prefs.get("history_limit", 10)
        self._sidebar_visible: bool = prefs.get("sidebar_visible", False)
        self._repo = git_history.find_repository(path) if git_history.AVAILABLE else None
        # What the sidebar last reported: the version shown, and the version it
        # is compared against (None for its implicit parent / HEAD).
        self._target: Revision = WORKING_COPY
        self._base: Revision | None = None
        self._mode = "rendered"

        width = prefs.get("window_width", 920)
        height = prefs.get("window_height", 720)
        self.set_default_size(width, height)
        if prefs.get("window_maximized", False):
            self.maximize()

        # Webview
        self._webview = WebKit.WebView()
        self._webview.set_zoom_level(self._zoom_level)
        settings = self._webview.get_settings()
        settings.set_enable_javascript(False)
        settings.set_auto_load_images(True)
        self._webview.connect("decide-policy", self._decide_policy)
        self._webview.connect("load-changed", self._load_changed)
        self._pending_scroll_y: float | None = None

        # Build UI layout with native GTK HeaderBar
        self._setup_ui()
        self._setup_actions()

        self._monitor_path()
        self.load_document()

    def _setup_ui(self) -> None:
        header_bar = Gtk.HeaderBar()
        self.set_titlebar(header_bar)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_box.set_valign(Gtk.Align.CENTER)
        self._title_label = Gtk.Label(label=self.path.name)
        self._title_label.add_css_class("title")
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._title_label.set_single_line_mode(True)
        self._title_label.set_max_width_chars(40)
        self._subtitle_label = Gtk.Label(label="")
        self._subtitle_label.add_css_class("subtitle")
        self._subtitle_label.set_visible(False)
        self._subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._subtitle_label.set_single_line_mode(True)
        self._subtitle_label.set_max_width_chars(40)
        title_box.append(self._title_label)
        title_box.append(self._subtitle_label)
        header_bar.set_title_widget(title_box)

        # Reader preferences popover
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("view-paged-symbolic")
        menu_button.set_tooltip_text("Display options")

        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        # Zoom Controls
        zoom_label = Gtk.Label(label="Zoom", xalign=0.0)
        zoom_label.add_css_class("heading")
        box.append(zoom_label)

        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        zoom_out_btn = Gtk.Button(icon_name="zoom-out-symbolic")
        zoom_out_btn.set_tooltip_text("Zoom out (Ctrl+-)")
        zoom_out_btn.connect("clicked", lambda _: self._zoom_out())
        pct = int(round(self._zoom_level * 100))
        self._zoom_reset_btn = Gtk.Button(label=f"{pct}%")
        self._zoom_reset_btn.set_tooltip_text("Reset zoom (Ctrl+0)")
        self._zoom_reset_btn.connect("clicked", lambda _: self._zoom_reset())
        zoom_in_btn = Gtk.Button(icon_name="zoom-in-symbolic")
        zoom_in_btn.set_tooltip_text("Zoom in (Ctrl++)")
        zoom_in_btn.connect("clicked", lambda _: self._zoom_in())

        zoom_box.append(zoom_out_btn)
        zoom_box.append(self._zoom_reset_btn)
        zoom_box.append(zoom_in_btn)
        box.append(zoom_box)

        # Font Family Controls
        font_label = Gtk.Label(label="Font Family", xalign=0.0)
        font_label.add_css_class("heading")
        box.append(font_label)

        box.append(choice_row(
            [
                ("system", "System", "Default (System UI)"),
                ("sans", "Sans", "Ubuntu / Cantarell"),
                ("serif", "Serif", "DejaVu / Noto Serif"),
                ("mono", "Mono", "Ubuntu Mono"),
            ],
            self._font,
            self._on_font_selected,
        ))

        # Theme Controls
        theme_label = Gtk.Label(label="Theme", xalign=0.0)
        theme_label.add_css_class("heading")
        box.append(theme_label)

        box.append(choice_row(
            [
                ("system", "System", "Follow the system style"),
                ("light", "Light", None),
                ("dark", "Dark", None),
                ("sepia", "Sepia", None),
            ],
            self._theme,
            self._on_theme_selected,
        ))

        self._popover = popover
        popover.set_child(box)
        menu_button.set_popover(popover)
        header_bar.pack_end(menu_button)

        self._sidebar = HistorySidebar(self._history_selected)
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_start_child(self._sidebar)
        self._paned.set_end_child(self._webview)
        self._paned.set_resize_start_child(False)
        self._paned.set_shrink_start_child(False)
        self._paned.set_position(self._sidebar_width)
        self.set_child(self._paned)

        if self._repo is not None:
            self._sidebar_button = Gtk.ToggleButton()
            self._sidebar_button.set_icon_name("view-sidebar-start-symbolic")
            self._sidebar_button.set_tooltip_text("Git history (Ctrl+H)")
            self._sidebar_button.set_active(self._sidebar_visible)
            self._sidebar_button.connect("toggled", self._sidebar_toggled)
            header_bar.pack_start(self._sidebar_button)
        else:
            self._sidebar_button = None
            self._sidebar_visible = False
        self._sidebar.set_visible(self._sidebar_visible)
        if self._sidebar_visible:
            self._sidebar.load(self._repo, self.path, self._history_limit)

    def _setup_actions(self) -> None:
        # Keyboard shortcuts for zoom
        action_zoom_in = Gio.SimpleAction.new("zoom-in", None)
        action_zoom_in.connect("activate", lambda *_: self._zoom_in())
        self.add_action(action_zoom_in)

        action_zoom_out = Gio.SimpleAction.new("zoom-out", None)
        action_zoom_out.connect("activate", lambda *_: self._zoom_out())
        self.add_action(action_zoom_out)

        action_zoom_reset = Gio.SimpleAction.new("zoom-reset", None)
        action_zoom_reset.connect("activate", lambda *_: self._zoom_reset())
        self.add_action(action_zoom_reset)

        action_toggle_sidebar = Gio.SimpleAction.new("toggle-sidebar", None)
        action_toggle_sidebar.connect(
            "activate", lambda *_: self._set_sidebar_visible(not self._sidebar_visible)
        )
        self.add_action(action_toggle_sidebar)

        action_working_copy = Gio.SimpleAction.new("working-copy", None)
        action_working_copy.connect("activate", lambda *_: self._show_working_copy())
        self.add_action(action_working_copy)

    def _update_zoom_label(self, level: float) -> None:
        pct = int(round(level * 100))
        if hasattr(self, "_zoom_reset_btn") and self._zoom_reset_btn:
            self._zoom_reset_btn.set_label(f"{pct}%")

    def _zoom_in(self) -> None:
        level = self._webview.get_zoom_level()
        new_level = min(level + 0.1, 3.0)
        self._webview.set_zoom_level(new_level)
        self._update_zoom_label(new_level)
        save_preferences(zoom_level=new_level)

    def _zoom_out(self) -> None:
        level = self._webview.get_zoom_level()
        new_level = max(level - 0.1, 0.5)
        self._webview.set_zoom_level(new_level)
        self._update_zoom_label(new_level)
        save_preferences(zoom_level=new_level)

    def _zoom_reset(self) -> None:
        self._webview.set_zoom_level(1.0)
        self._update_zoom_label(1.0)
        save_preferences(zoom_level=1.0)

    def _on_font_selected(self, font: str) -> None:
        if font != self._font:
            self._font = font
            save_preferences(font=font)
            self.refresh_document()

    def _on_theme_selected(self, theme: str) -> None:
        if theme != self._theme:
            self._theme = theme
            save_preferences(theme=theme)
            self.refresh_document()

    def _sidebar_toggled(self, button: Gtk.ToggleButton) -> None:
        self._set_sidebar_visible(button.get_active())

    def _set_sidebar_visible(self, visible: bool) -> None:
        if self._repo is None or visible == self._sidebar_visible:
            # The equality check also breaks the reentrancy below: setting the
            # button's active state emits "toggled" synchronously, which calls
            # back into this method before the outer call below returns. That
            # nested call sees the same (already-applied) state and bails out
            # here, so the query and the preferences write below each run once.
            return
        self._sidebar_visible = visible
        self._sidebar.set_visible(visible)
        if self._sidebar_button is not None and self._sidebar_button.get_active() != visible:
            self._sidebar_button.set_active(visible)
        if visible:
            # Re-query on open: the .git directory is not watched, so a commit
            # made externally appears the next time the sidebar is opened.
            self._sidebar.load(self._repo, self.path, self._history_limit)
        save_preferences(sidebar_visible=visible)

    def _history_selected(self, target: Revision, base: Revision | None, mode: str) -> None:
        changed = view_changed(self._target, self._base, target, base, mode)
        self._target = target
        self._base = base
        self._mode = mode
        self._update_titles()
        if changed:
            # A different document: start at the top rather than restoring an
            # offset that means nothing here.
            self.load_document()
        else:
            self.refresh_document()

    def _show_working_copy(self) -> None:
        """Escape: close the options popover, else unpin, else leave history."""

        # The popover's grab normally keeps Escape from reaching this window
        # shortcut; this guards the case where focus ended up outside it.
        if self._popover.get_visible():
            self._popover.popdown()
            return
        if self._sidebar.clear_pin():
            return
        if self._target == WORKING_COPY:
            return
        self._sidebar.select_working_copy()

    def _update_titles(self) -> None:
        title, subtitle = window_titles(self.path.name, self._target, self._base, self._mode)
        self.set_title(title)
        self._subtitle_label.set_text(subtitle or "")
        self._subtitle_label.set_visible(subtitle is not None)

    def refresh_document(self) -> None:
        script = "window.scrollY"
        self._webview.get_settings().set_enable_javascript(True)
        self._webview.evaluate_javascript(
            script, len(script), None, None, None, self._scroll_captured, None
        )

    def _monitor_path(self) -> None:
        if self._monitor:
            self._monitor.cancel()
        try:
            self._monitor = Gio.File.new_for_path(str(self.path)).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
            self._monitor.connect("changed", self._file_changed)
        except GLib.Error:
            self._monitor = None

    def _file_changed(self, _monitor, _file, _other, _event) -> None:
        if self._reload_source:
            GLib.source_remove(self._reload_source)
        self._reload_source = GLib.timeout_add(180, self._reload_timeout)

    def _reload_timeout(self) -> bool:
        self._reload_source = 0
        self._monitor_path()  # reconnect after atomic replacement
        # Saving changes whether the file differs from HEAD, so the
        # working-copy row's status dot is refreshed either way.
        if self._repo is not None:
            # Also clears a working-copy pin the save made meaningless, even
            # while the sidebar is hidden.  refresh_status() may itself emit a
            # selection change (e.g. that pin clearing), which already calls
            # _history_selected() -> load_document().  Snapshot first and bail
            # out if that happened, or the document below would render twice.
            before = (self._target, self._base)
            self._sidebar.refresh_status()
            if (self._target, self._base) != before:
                return GLib.SOURCE_REMOVE
        if not reloads_on_save(self._target, self._base, self._mode):
            # Rendered mode shows only the target, and no working-copy side is
            # on screen otherwise.  Saving the file must not swap the view;
            # only the working-copy row's status may change.
            return GLib.SOURCE_REMOVE
        # WebKit's page JavaScript remains disabled.  Code explicitly evaluated
        # by the host application lets us preserve the reading position.  The
        # setting is enabled only around this trusted expression; rendered HTML
        # is sanitized and contains no scripts.
        script = "window.scrollY"
        self._webview.get_settings().set_enable_javascript(True)
        self._webview.evaluate_javascript(
            script, len(script), None, None, None, self._scroll_captured, None
        )
        return GLib.SOURCE_REMOVE

    def _scroll_captured(self, webview, result, _user_data) -> None:
        scroll_y = 0.0
        try:
            value = webview.evaluate_javascript_finish(result)
            if value.is_number():
                scroll_y = max(0.0, value.to_double())
        except GLib.Error:
            pass
        finally:
            webview.get_settings().set_enable_javascript(False)
        self.load_document(scroll_y)

    def load_document(self, restore_scroll_y: float | None = None) -> None:
        self._title_label.set_text(self.path.name)
        self._update_titles()
        try:
            if self._mode != "rendered" and self._repo is not None:
                comparison = git_history.compare(
                    self._repo, self.path, self._base, self._target
                )
                html = render_comparison(
                    comparison, self._mode, font=self._font, theme=self._theme
                )
            elif isinstance(self._target, Commit):
                source = git_history.file_at(
                    self._repo, self._target.sha, self._target.path
                )
                html = render_markdown(
                    source, self.path.parent, font=self._font, theme=self._theme
                )
            else:
                source = read_source(self.path)
                html = render_markdown(
                    source, self.path.parent, font=self._font, theme=self._theme
                )
        except (RenderError, git_history.GitHistoryError) as exc:
            html = error_document(str(exc), font=self._font, theme=self._theme)
        base_uri = self.path.parent.as_uri()
        if not base_uri.endswith("/"):
            base_uri += "/"
        self._pending_scroll_y = restore_scroll_y
        self._webview.load_html(html, base_uri)

    def _load_changed(self, webview, event) -> None:
        if event != WebKit.LoadEvent.FINISHED or self._pending_scroll_y is None:
            return
        scroll_y = self._pending_scroll_y
        self._pending_scroll_y = None
        script = f"window.scrollTo(0, {scroll_y!r})"
        webview.get_settings().set_enable_javascript(True)
        webview.evaluate_javascript(
            script, len(script), None, None, None, self._scroll_restored, None
        )

    def _scroll_restored(self, webview, result, _user_data) -> None:
        try:
            webview.evaluate_javascript_finish(result)
        except GLib.Error:
            pass
        finally:
            webview.get_settings().set_enable_javascript(False)

    def _decide_policy(self, _view, decision, decision_type) -> bool:
        if decision_type != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        action = decision.get_navigation_action()
        request = action.get_request() if action else None
        uri = request.get_uri() if request else ""
        parsed = urlparse(uri)
        if parsed.scheme.lower() in {"http", "https", "mailto"}:
            if action and action.is_user_gesture():
                Gio.AppInfo.launch_default_for_uri(uri, None)
            decision.ignore()
            return True
        if parsed.scheme.lower() == "file":
            target = Path(unquote(parsed.path)).resolve()
            # load_html() reports its document base URI as a non-user file
            # navigation.  It must be allowed or WebKit displays a blank page.
            if (
                action
                and not action.is_user_gesture()
                and target == self.path.parent.resolve()
            ):
                return False
            # Fragment-only links resolve against the HTML base directory.
            if parsed.fragment and target == self.path.parent.resolve():
                return False
            if target.suffix.lower() in {".md", ".markdown"}:
                if action and action.is_user_gesture():
                    self.app._open_path(target)
                decision.ignore()
                return True
            decision.ignore()
            return True
        if parsed.scheme.lower() in {"javascript", "data"}:
            decision.ignore()
            return True
        return False

    def close_request(self) -> bool:
        if self._monitor:
            self._monitor.cancel()
        if self._reload_source:
            GLib.source_remove(self._reload_source)
            self._reload_source = 0
        try:
            is_max = self.is_maximized()
            width, height = self.get_default_size()
            save_preferences(
                window_width=width,
                window_height=height,
                window_maximized=is_max,
                sidebar_width=self._paned.get_position(),
            )
        except Exception:
            pass
        return False


class MdPrevApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self._windows: dict[Path, PreviewWindow] = {}

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.set_accels_for_action("win.zoom-in", ["<Ctrl>plus", "<Ctrl>equal", "<Ctrl>KP_Add"])
        self.set_accels_for_action("win.zoom-out", ["<Ctrl>minus", "<Ctrl>KP_Subtract"])
        self.set_accels_for_action("win.zoom-reset", ["<Ctrl>0", "<Ctrl>KP_0"])
        self.set_accels_for_action("win.toggle-sidebar", ["<Ctrl>h"])
        self.set_accels_for_action("win.working-copy", ["Escape"])

    def do_activate(self) -> None:
        # File launches arrive through do_open().  Do not silently substitute a
        # repository README when the application is activated without a file.
        return

    def do_open(self, files, _n_files, _hint) -> None:
        for file in files:
            self._open_path(Path(file.get_path() or file.get_parse_name()).resolve())

    def _open_path(self, path: Path) -> None:
        window = self._windows.get(path)
        if window is None:
            window = PreviewWindow(self, path)
            self._windows[path] = window
            window.connect("close-request", self._window_closed, path)
        window.present()

    def _window_closed(self, window, path: Path) -> bool:
        self._windows.pop(path, None)
        window.close_request()
        return False


def main(argv: list[str] | None = None) -> int:
    return MdPrevApplication().run(sys.argv if argv is None else argv)
