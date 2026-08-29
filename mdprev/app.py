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
        self._webview = WebKit.WebView()
        settings = self._webview.get_settings()
        settings.set_enable_javascript(False)
        settings.set_auto_load_images(True)
        self._webview.connect("decide-policy", self._decide_policy)
        self._webview.connect("load-changed", self._load_changed)
        self._pending_scroll_y: float | None = None
        self.set_child(self._webview)
        self._monitor_path()
        self.load_document()

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
            html = render_markdown(source, self.path.parent)
        except RenderError as exc:
            html = error_document(str(exc))
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
