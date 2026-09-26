"""NSApplication shell for MdPrev on macOS."""

from __future__ import annotations

from pathlib import Path
import sys

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSMenu,
    NSMenuItem,
    NSModalResponseOK,
    NSOpenPanel,
    NSWindow,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from .window import PreviewWindow

APP_NAME = "MdPrev"

_FONTS = (("system", "System"), ("sans", "Sans"), ("serif", "Serif"), ("mono", "Monospace"))
_THEMES = (("system", "System"), ("light", "Light"), ("dark", "Dark"), ("sepia", "Sepia"))


class MdPrevApplication:
    def __init__(self, paths: list[Path]):
        self._windows: dict[Path, PreviewWindow] = {}
        self._initial_paths = paths
        self._delegate = _AppDelegate.alloc().init()
        self._delegate.owner = self

    def run(self) -> int:
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        app.setDelegate_(self._delegate)
        app.setMainMenu_(_main_menu())
        # One document per window; macOS would otherwise merge them into tabs.
        NSWindow.setAllowsAutomaticWindowTabbing_(False)
        AppHelper.runEventLoop()
        return 0

    def launched(self) -> None:
        for path in self._initial_paths:
            self.open_path(path)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def open_path(self, path: Path) -> None:
        path = path.resolve()
        window = self._windows.get(path)
        if window is None:
            window = PreviewWindow(self, path)
            self._windows[path] = window
        window.present()

    def window_closed(self, window: PreviewWindow) -> None:
        self._windows.pop(window.path, None)

    def choose_files(self) -> None:
        panel = NSOpenPanel.openPanel()
        panel.setAllowsMultipleSelection_(True)
        panel.setAllowedFileTypes_(["md", "markdown"])
        if panel.runModal() == NSModalResponseOK:
            for url in panel.URLs():
                self.open_path(Path(url.path()))


class _AppDelegate(NSObject):
    owner = None

    def applicationDidFinishLaunching_(self, _notification):
        self.owner.launched()

    def application_openURLs_(self, _app, urls):
        # Finder "Open With", the Dock, and `open -a MdPrev FILE`.
        for url in urls:
            if url.isFileURL():
                self.owner.open_path(Path(url.path()))

    def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
        return True

    def applicationSupportsSecureRestorableState_(self, _app):
        return True

    def openDocument_(self, _sender):
        self.owner.choose_files()


def _item(title: str, action: str | None, key: str = "", modifiers: int | None = None) -> NSMenuItem:
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
    if modifiers is not None:
        item.setKeyEquivalentModifierMask_(modifiers)
    return item


def _submenu(title: str, items) -> NSMenuItem:
    menu = NSMenu.alloc().initWithTitle_(title)
    for item in items:
        menu.addItem_(item)
    holder = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
    holder.setSubmenu_(menu)
    return holder


def _choices(action: str, choices) -> list[NSMenuItem]:
    items = []
    for key, title in choices:
        item = _item(title, action)
        item.setRepresentedObject_(key)
        items.append(item)
    return items


def _main_menu() -> NSMenu:
    main = NSMenu.alloc().init()
    main.addItem_(_submenu(APP_NAME, [
        _item(f"About {APP_NAME}", "orderFrontStandardAboutPanel:"),
        NSMenuItem.separatorItem(),
        _item(f"Hide {APP_NAME}", "hide:", "h"),
        _item("Hide Others", "hideOtherApplications:", "h",
              NSEventModifierFlagCommand | NSEventModifierFlagOption),
        _item("Show All", "unhideAllApplications:"),
        NSMenuItem.separatorItem(),
        _item(f"Quit {APP_NAME}", "terminate:", "q"),
    ]))
    main.addItem_(_submenu("File", [
        _item("Open…", "openDocument:", "o"),
        NSMenuItem.separatorItem(),
        _item("Close", "performClose:", "w"),
    ]))
    main.addItem_(_submenu("Edit", [
        _item("Copy", "copy:", "c"),
        _item("Select All", "selectAll:", "a"),
    ]))
    main.addItem_(_submenu("View", [
        _item("Zoom In", "mdprevZoomIn:", "="),
        _item("Zoom Out", "mdprevZoomOut:", "-"),
        _item("Actual Size", "mdprevZoomReset:", "0"),
        NSMenuItem.separatorItem(),
        _submenu("Font", _choices("mdprevSelectFont:", _FONTS)),
        _submenu("Theme", _choices("mdprevSelectTheme:", _THEMES)),
        NSMenuItem.separatorItem(),
        _item("Show Outline", "toggleOutline:", "s",
              NSEventModifierFlagCommand | NSEventModifierFlagControl),
        _item("Show History", "toggleHistorySidebar:", "h",
              NSEventModifierFlagCommand | NSEventModifierFlagControl),
        _item("Back to Working Copy", "showWorkingCopy:", "\x1b", 0),
        NSMenuItem.separatorItem(),
        _item("Enter Full Screen", "toggleFullScreen:", "f",
              NSEventModifierFlagCommand | NSEventModifierFlagControl),
    ]))
    window_menu = _submenu("Window", [
        _item("Minimize", "performMiniaturize:", "m"),
        _item("Zoom", "performZoom:"),
        NSMenuItem.separatorItem(),
        _item("Bring All to Front", "arrangeInFront:"),
    ])
    main.addItem_(window_menu)
    NSApplication.sharedApplication().setWindowsMenu_(window_menu.submenu())
    return main


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    # Launch Services may pass a process serial number argument to bundles.
    paths = [Path(arg) for arg in argv[1:] if not arg.startswith("-psn_")]
    return MdPrevApplication(paths).run()
