"""AppKit / WKWebView preview window for macOS."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import unquote, urlparse

from AppKit import (
    NSBackingStoreBuffered,
    NSImage,
    NSSplitViewController,
    NSSplitViewItem,
    NSToolbar,
    NSToolbarItem,
    NSViewController,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSWindowToolbarStyleUnified,
    NSWorkspace,
)
from Foundation import NSURL, NSMakeRect, NSObject, NSTimer
from WebKit import (
    WKNavigationActionPolicyAllow,
    WKNavigationActionPolicyCancel,
    WKNavigationTypeLinkActivated,
    WKWebView,
    WKWebViewConfiguration,
)

from ..core import git_history
from ..core.git_history import WORKING_COPY, Revision
from ..core.navigation import Allow, OpenDocument, OpenExternal, classify_link
from ..core.preferences import (
    MAX_SIDEBAR_WIDTH,
    MIN_SIDEBAR_WIDTH,
    load_preferences,
    save_preferences,
)
from ..core.session import (
    DEFAULT_ZOOM,
    base_uri,
    build_html,
    reloads_on_save,
    view_changed,
    window_titles,
    with_base_href,
    zoom_in,
    zoom_out,
)
from .sidebar import HistorySidebar
from .watcher import FileWatcher

# Matches the GTK front end: long enough to coalesce an editor's burst of
# write/rename events into one reload.
RELOAD_DELAY_SECONDS = 0.18
_HISTORY_ITEM = "io.github.yszhangit.mdprev.history"


class PreviewWindow:
    """One window showing one Markdown document."""

    def __init__(self, app, path: Path):
        self.app = app
        self.path = path
        prefs = load_preferences()
        self.font: str = prefs.get("font", "system")
        self.theme: str = prefs.get("theme", "system")
        self._history_limit: int = prefs.get("history_limit", 10)
        self._repo = git_history.find_repository(path) if git_history.AVAILABLE else None
        # What the sidebar last reported: the version shown, and the version it
        # is compared against (None for its implicit parent / HEAD).
        self.target: Revision = WORKING_COPY
        self.base: Revision | None = None
        self.mode = "rendered"
        self._pending_scroll_y: float | None = None
        self._reload_timer = None
        # WKWebView grants file access only to pages loaded from files, so the
        # rendered HTML is written here and loaded with read access to the
        # local images the sanitizer allowed.
        self._scratch = Path(tempfile.mkdtemp(prefix="mdprev-"))
        self._view_file = self._scratch / "view.html"

        self._bridge = _WindowBridge.alloc().init()
        self._bridge.owner = self

        self._webview = self._make_webview(prefs.get("zoom_level", DEFAULT_ZOOM))
        web_controller = NSViewController.alloc().init()
        web_controller.setView_(self._webview)

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, prefs.get("window_width", 920), prefs.get("window_height", 720)),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self._bridge)
        self.window.setRepresentedURL_(NSURL.fileURLWithPath_(str(path)))

        self.sidebar: HistorySidebar | None = None
        self._sidebar_item = None
        if self._repo is not None:
            self.sidebar = HistorySidebar(self._history_selected)
            sidebar_controller = NSViewController.alloc().init()
            sidebar_controller.setView_(self.sidebar.view)
            self._sidebar_item = NSSplitViewItem.sidebarWithViewController_(sidebar_controller)
            self._sidebar_item.setMinimumThickness_(MIN_SIDEBAR_WIDTH)
            self._sidebar_item.setMaximumThickness_(MAX_SIDEBAR_WIDTH)
            self._sidebar_item.setCanCollapse_(True)
            self._split = NSSplitViewController.alloc().init()
            self._split.addSplitViewItem_(self._sidebar_item)
            self._split.addSplitViewItem_(
                NSSplitViewItem.splitViewItemWithViewController_(web_controller)
            )
            self.window.setContentViewController_(self._split)
            toolbar = NSToolbar.alloc().initWithIdentifier_("io.github.yszhangit.mdprev")
            toolbar.setDelegate_(self._bridge)
            toolbar.setDisplayMode_(1)  # NSToolbarDisplayModeIconOnly
            self.window.setToolbar_(toolbar)
            self.window.setToolbarStyle_(NSWindowToolbarStyleUnified)
        else:
            self.window.setContentViewController_(web_controller)
        # Setting a content view controller resizes the window to the
        # controller's view; restore the saved size afterwards.
        self.window.setContentSize_((prefs.get("window_width", 920), prefs.get("window_height", 720)))
        self.window.center()
        if prefs.get("window_maximized", False):
            self.window.zoom_(None)

        visible = self.sidebar is not None and prefs.get("sidebar_visible", False)
        if self._sidebar_item is not None:
            self._sidebar_item.setCollapsed_(not visible)
            self._split.splitView().setPosition_ofDividerAtIndex_(
                prefs.get("sidebar_width", 280), 0
            )
            if visible:
                self.sidebar.load(self._repo, self.path, self._history_limit)

        self._watcher = FileWatcher(path, self._file_changed)
        self.load_document()

    def _make_webview(self, zoom: float) -> WKWebView:
        config = WKWebViewConfiguration.alloc().init()
        # Page JavaScript stays off; only scripts this application evaluates
        # (reading and restoring the scroll offset) run.
        config.defaultWebpagePreferences().setAllowsContentJavaScript_(False)
        webview = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, 600, 400), config
        )
        webview.setNavigationDelegate_(self._bridge)
        webview.setPageZoom_(zoom)
        webview.setAllowsMagnification_(True)
        return webview

    # -- presenting --------------------------------------------------------

    def present(self) -> None:
        self.window.makeKeyAndOrderFront_(None)

    def _update_titles(self) -> None:
        _title, subtitle = window_titles(self.path.name, self.target, self.base, self.mode)
        self.window.setTitle_(self.path.name)
        self.window.setSubtitle_(subtitle or "")

    def load_document(self, restore_scroll_y: float | None = None) -> None:
        self._update_titles()
        html = build_html(
            self.path, self._repo, self.target, self.base, self.mode, self.font, self.theme
        )
        self._view_file.write_text(with_base_href(html, base_uri(self.path)), encoding="utf-8")
        self._pending_scroll_y = restore_scroll_y
        self._webview.loadFileURL_allowingReadAccessToURL_(
            NSURL.fileURLWithPath_(str(self._view_file)), NSURL.fileURLWithPath_("/")
        )

    def refresh_document(self) -> None:
        """Re-render in place, keeping the reading position."""

        def captured(value, _error):
            scroll_y = max(0.0, float(value)) if isinstance(value, (int, float)) else 0.0
            self.load_document(scroll_y)

        self._webview.evaluateJavaScript_completionHandler_("window.scrollY", captured)

    def navigation_finished(self) -> None:
        if self._pending_scroll_y is None:
            return
        script = f"window.scrollTo(0, {self._pending_scroll_y!r})"
        self._pending_scroll_y = None
        self._webview.evaluateJavaScript_completionHandler_(script, None)

    # -- live reload -------------------------------------------------------

    def _file_changed(self) -> None:
        if self._reload_timer is not None:
            self._reload_timer.invalidate()
        self._reload_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            RELOAD_DELAY_SECONDS, self._bridge, "reloadTimerFired:", None, False
        )

    def reload_timer_fired(self) -> None:
        self._reload_timer = None
        # Saving changes whether the file differs from HEAD, so the
        # working-copy row's status is refreshed either way.
        if self.sidebar is not None:
            # refresh_status() may itself report a selection change (clearing
            # a working-copy pin the save made meaningless), which already
            # reloads the document; do not render twice.
            before = (self.target, self.base)
            self.sidebar.refresh_status()
            if (self.target, self.base) != before:
                return
        if reloads_on_save(self.target, self.base, self.mode):
            self.refresh_document()

    # -- navigation --------------------------------------------------------

    def decide_navigation(self, action) -> bool:
        """Return True to let the web view navigate."""

        url = action.request().URL()
        uri = url.absoluteString() if url is not None else ""
        gesture = action.navigationType() == WKNavigationTypeLinkActivated
        if not gesture and self._is_view_file(url):
            return True
        decision = classify_link(uri, self.path.parent, gesture)
        if isinstance(decision, Allow):
            fragment = urlparse(uri).fragment
            if gesture and fragment:
                # The page's own URL is the scratch file, not the document's
                # directory, so an in-document link would load that directory.
                # Scroll to the anchor instead.
                target = json.dumps(unquote(fragment))
                self._webview.evaluateJavaScript_completionHandler_(
                    f"document.getElementById({target})?.scrollIntoView()", None
                )
                return False
            return True
        if isinstance(decision, OpenExternal):
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(decision.uri))
        elif isinstance(decision, OpenDocument):
            self.app.open_path(decision.path)
        return False

    def _is_view_file(self, url) -> bool:
        if url is None or not url.isFileURL():
            return False
        return Path(url.path()).resolve() == self._view_file.resolve()

    # -- history -----------------------------------------------------------

    @property
    def sidebar_visible(self) -> bool:
        return self._sidebar_item is not None and not self._sidebar_item.isCollapsed()

    def set_sidebar_visible(self, visible: bool) -> None:
        if self._sidebar_item is None or visible == self.sidebar_visible:
            return
        self._sidebar_item.animator().setCollapsed_(not visible)
        if visible:
            # Re-query on open: the .git directory is not watched, so a commit
            # made externally appears the next time the sidebar is opened.
            self.sidebar.load(self._repo, self.path, self._history_limit)
        save_preferences(sidebar_visible=visible)

    def _history_selected(self, target: Revision, base: Revision | None, mode: str) -> None:
        changed = view_changed(self.target, self.base, target, base, mode)
        self.target = target
        self.base = base
        self.mode = mode
        self._update_titles()
        if changed:
            # A different document: start at the top rather than restoring an
            # offset that means nothing here.
            self.load_document()
        else:
            self.refresh_document()

    @property
    def can_leave_history(self) -> bool:
        return self.sidebar is not None and (
            self.sidebar.has_pin or self.target != WORKING_COPY
        )

    def show_working_copy(self) -> None:
        """Escape: unpin, else leave history for the working copy."""

        if self.sidebar is None or self.sidebar.clear_pin():
            return
        if self.target != WORKING_COPY:
            self.sidebar.select_working_copy()

    # -- reader options ----------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._webview.pageZoom()

    def set_zoom(self, level: float) -> None:
        self._webview.setPageZoom_(level)
        save_preferences(zoom_level=level)

    def zoom_in(self) -> None:
        self.set_zoom(zoom_in(self.zoom))

    def zoom_out(self) -> None:
        self.set_zoom(zoom_out(self.zoom))

    def zoom_reset(self) -> None:
        self.set_zoom(DEFAULT_ZOOM)

    def set_font(self, font: str) -> None:
        if font != self.font:
            self.font = font
            save_preferences(font=font)
            self.refresh_document()

    def set_theme(self, theme: str) -> None:
        if theme != self.theme:
            self.theme = theme
            save_preferences(theme=theme)
            self.refresh_document()

    # -- closing -----------------------------------------------------------

    def closed(self) -> None:
        self._watcher.stop()
        if self._reload_timer is not None:
            self._reload_timer.invalidate()
            self._reload_timer = None
        size = self.window.contentRectForFrameRect_(self.window.frame()).size
        prefs = {
            "window_maximized": bool(self.window.isZoomed()),
            "window_width": int(size.width),
            "window_height": int(size.height),
        }
        if self.sidebar_visible:
            prefs["sidebar_width"] = int(self.sidebar.view.frame().size.width)
        save_preferences(**prefs)
        shutil.rmtree(self._scratch, ignore_errors=True)
        self._webview.setNavigationDelegate_(None)
        self._bridge.owner = None
        self.app.window_closed(self)


class _WindowBridge(NSObject):
    """Receives AppKit and WebKit callbacks and menu actions for one window.

    Menu items target the first responder; AppKit tries the key window's
    delegate, so window-level actions are implemented here.
    """

    owner = None

    # NSWindowDelegate

    def windowWillClose_(self, _notification):
        if self.owner is not None:
            self.owner.closed()

    # WKNavigationDelegate

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, _webview, action, handler):
        allowed = self.owner is not None and self.owner.decide_navigation(action)
        handler(WKNavigationActionPolicyAllow if allowed else WKNavigationActionPolicyCancel)

    def webView_didFinishNavigation_(self, _webview, _navigation):
        if self.owner is not None:
            self.owner.navigation_finished()

    # Timers

    def reloadTimerFired_(self, _timer):
        if self.owner is not None:
            self.owner.reload_timer_fired()

    # NSToolbarDelegate

    def toolbarAllowedItemIdentifiers_(self, _toolbar):
        return [_HISTORY_ITEM]

    def toolbarDefaultItemIdentifiers_(self, _toolbar):
        return [_HISTORY_ITEM]

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(self, _toolbar, identifier, _insert):
        item = NSToolbarItem.alloc().initWithItemIdentifier_(identifier)
        item.setLabel_("History")
        item.setToolTip_("Git history (⌃⌘S)")
        item.setImage_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_("sidebar.left", "Git history")
        )
        item.setBordered_(True)
        item.setTarget_(self)
        item.setAction_("toggleHistorySidebar:")
        return item

    # Menu actions

    def toggleHistorySidebar_(self, _sender):
        if self.owner is not None:
            self.owner.set_sidebar_visible(not self.owner.sidebar_visible)

    def showWorkingCopy_(self, _sender):
        if self.owner is not None:
            self.owner.show_working_copy()

    def mdprevZoomIn_(self, _sender):
        if self.owner is not None:
            self.owner.zoom_in()

    def mdprevZoomOut_(self, _sender):
        if self.owner is not None:
            self.owner.zoom_out()

    def mdprevZoomReset_(self, _sender):
        if self.owner is not None:
            self.owner.zoom_reset()

    def mdprevSelectFont_(self, sender):
        if self.owner is not None:
            self.owner.set_font(sender.representedObject())

    def mdprevSelectTheme_(self, sender):
        if self.owner is not None:
            self.owner.set_theme(sender.representedObject())

    def validateMenuItem_(self, item):
        owner = self.owner
        if owner is None:
            return False
        action = item.action()
        if action == "mdprevSelectFont:":
            item.setState_(1 if item.representedObject() == owner.font else 0)
        elif action == "mdprevSelectTheme:":
            item.setState_(1 if item.representedObject() == owner.theme else 0)
        elif action == "toggleHistorySidebar:":
            item.setTitle_("Hide History" if owner.sidebar_visible else "Show History")
            return owner.sidebar is not None
        elif action == "showWorkingCopy:":
            return owner.can_leave_history
        return True
