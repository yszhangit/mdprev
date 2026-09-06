"""GTK/WebKit application shell for MdPrev."""

from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, Gtk, WebKit  # noqa: E402

from .render import RenderError, error_document, read_source, render_markdown  # noqa: E402


APP_ID = "io.github.yszhangit.mdprev"


class PreviewWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "MdPrevApplication", path: Path):
        super().__init__(application=app)
        self.app = app
        self.path = path
        self._monitor: Gio.FileMonitor | None = None
        self._reload_source: int = 0
        self.set_default_size(920, 720)

        # Reader state
        self._font: str = "system"
        self._theme: str = "system"

        # Webview
        self._webview = WebKit.WebView()
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
        self._zoom_reset_btn = Gtk.Button(label="100%")
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

        font_dropdown = Gtk.DropDown.new_from_strings([
            "Default (System UI)",
            "Ubuntu / Cantarell (Sans)",
            "DejaVu / Noto (Serif)",
            "Ubuntu Mono (Monospace)",
        ])
        font_keys = ["system", "sans", "serif", "mono"]
        font_dropdown.connect("notify::selected", self._on_font_selected, font_keys)
        box.append(font_dropdown)

        # Theme Controls
        theme_label = Gtk.Label(label="Theme", xalign=0.0)
        theme_label.add_css_class("heading")
        box.append(theme_label)

        theme_dropdown = Gtk.DropDown.new_from_strings([
            "System (Auto)",
            "Light",
            "Dark",
            "Sepia",
        ])
        theme_keys = ["system", "light", "dark", "sepia"]
        theme_dropdown.connect("notify::selected", self._on_theme_selected, theme_keys)
        box.append(theme_dropdown)

        self._popover = popover
        popover.set_child(box)
        menu_button.set_popover(popover)
        header_bar.pack_end(menu_button)

        self.set_child(self._webview)

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

    def _update_zoom_label(self, level: float) -> None:
        pct = int(round(level * 100))
        if hasattr(self, "_zoom_reset_btn") and self._zoom_reset_btn:
            self._zoom_reset_btn.set_label(f"{pct}%")

    def _zoom_in(self) -> None:
        level = self._webview.get_zoom_level()
        new_level = min(level + 0.1, 3.0)
        self._webview.set_zoom_level(new_level)
        self._update_zoom_label(new_level)

    def _zoom_out(self) -> None:
        level = self._webview.get_zoom_level()
        new_level = max(level - 0.1, 0.5)
        self._webview.set_zoom_level(new_level)
        self._update_zoom_label(new_level)

    def _zoom_reset(self) -> None:
        self._webview.set_zoom_level(1.0)
        self._update_zoom_label(1.0)

    def _on_font_selected(self, dropdown, _param, font_keys: list[str]) -> None:
        idx = dropdown.get_selected()
        if 0 <= idx < len(font_keys):
            new_font = font_keys[idx]
            if new_font != self._font:
                self._font = new_font
                self.refresh_document()
                # Ensure the display options popover stays open
                if hasattr(self, "_popover") and self._popover:
                    self._popover.popup()

    def _on_theme_selected(self, dropdown, _param, theme_keys: list[str]) -> None:
        idx = dropdown.get_selected()
        if 0 <= idx < len(theme_keys):
            new_theme = theme_keys[idx]
            if new_theme != self._theme:
                self._theme = new_theme
                self.refresh_document()
                # Ensure the display options popover stays open
                if hasattr(self, "_popover") and self._popover:
                    self._popover.popup()

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
        self.set_title(self.path.name)
        try:
            source = read_source(self.path)
            html = render_markdown(
                source,
                self.path.parent,
                font=self._font,
                theme=self._theme,
            )
        except RenderError as exc:
            html = error_document(
                str(exc),
                font=self._font,
                theme=self._theme,
            )
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
