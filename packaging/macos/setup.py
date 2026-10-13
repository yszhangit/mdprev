"""py2app configuration for View Markdown.app.

Run by install.sh from a temporary build directory, so nothing is written
into the repository:

    python packaging/macos/setup.py py2app --iconfile ICON.icns
"""

from pathlib import Path
import sys

from setuptools import setup

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from view_markdown import __version__  # noqa: E402

PLIST = {
    "CFBundleName": "View Markdown",
    "CFBundleDisplayName": "View Markdown",
    "CFBundleIdentifier": "io.github.fixed-42.view-markdown",
    "CFBundleShortVersionString": __version__,
    "CFBundleVersion": __version__,
    "LSMinimumSystemVersion": "26.0",
    "LSApplicationCategoryType": "public.app-category.productivity",
    "NSHighResolutionCapable": True,
    "CFBundleDocumentTypes": [
        {
            "CFBundleTypeName": "Markdown Document",
            "CFBundleTypeRole": "Viewer",
            # Listed under Finder's "Open With" without taking over as the
            # default; the user chooses that in Get Info.
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["net.daringfireball.markdown"],
        }
    ],
}

setup(
    app=[str(HERE / "launcher.py")],
    options={
        "py2app": {
            "packages": ["view_markdown", "pygments", "pygit2", "cffi"],
            "excludes": ["gi", "pytest", "py2app", "setuptools", "pip"],
            "plist": PLIST,
        }
    },
)
