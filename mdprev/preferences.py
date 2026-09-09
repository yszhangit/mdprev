"""Reader preferences management for MdPrev."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR_NAME = "mdprev"
CONFIG_FILE_NAME = "preferences.json"

DEFAULT_FONT = "system"
DEFAULT_THEME = "system"
DEFAULT_ZOOM_LEVEL = 1.0
DEFAULT_WINDOW_WIDTH = 920
DEFAULT_WINDOW_HEIGHT = 720
DEFAULT_SIDEBAR_VISIBLE = False
DEFAULT_SIDEBAR_WIDTH = 280
DEFAULT_HISTORY_LIMIT = 10

VALID_FONTS = ("system", "sans", "serif", "mono")
VALID_THEMES = ("system", "light", "dark", "sepia")
MIN_ZOOM = 0.5
MAX_ZOOM = 3.0
MIN_WINDOW_WIDTH = 200
MIN_WINDOW_HEIGHT = 150
MIN_SIDEBAR_WIDTH = 180
MAX_SIDEBAR_WIDTH = 600
MIN_HISTORY_LIMIT = 1
MAX_HISTORY_LIMIT = 500


def get_config_file_path() -> Path:
    """Return the Path to the user's preferences JSON file following XDG Base Directory specification."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        base_dir = Path(xdg_config_home)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def load_preferences() -> dict[str, Any]:
    """Load user preferences from disk. Returns defaults if file is missing or invalid."""
    prefs: dict[str, Any] = {
        "font": DEFAULT_FONT,
        "theme": DEFAULT_THEME,
        "zoom_level": DEFAULT_ZOOM_LEVEL,
        "window_width": DEFAULT_WINDOW_WIDTH,
        "window_height": DEFAULT_WINDOW_HEIGHT,
        "window_maximized": False,
        "sidebar_visible": DEFAULT_SIDEBAR_VISIBLE,
        "sidebar_width": DEFAULT_SIDEBAR_WIDTH,
        "history_limit": DEFAULT_HISTORY_LIMIT,
    }
    path = get_config_file_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            font = data.get("font")
            if isinstance(font, str) and font in VALID_FONTS:
                prefs["font"] = font

            theme = data.get("theme")
            if isinstance(theme, str) and theme in VALID_THEMES:
                prefs["theme"] = theme

            zoom_level = data.get("zoom_level")
            if isinstance(zoom_level, (int, float)) and MIN_ZOOM <= zoom_level <= MAX_ZOOM:
                prefs["zoom_level"] = float(zoom_level)

            width = data.get("window_width")
            if isinstance(width, int) and width >= MIN_WINDOW_WIDTH:
                prefs["window_width"] = width

            height = data.get("window_height")
            if isinstance(height, int) and height >= MIN_WINDOW_HEIGHT:
                prefs["window_height"] = height

            maximized = data.get("window_maximized")
            if isinstance(maximized, bool):
                prefs["window_maximized"] = maximized

            sidebar_visible = data.get("sidebar_visible")
            if isinstance(sidebar_visible, bool):
                prefs["sidebar_visible"] = sidebar_visible

            sidebar_width = data.get("sidebar_width")
            if (
                isinstance(sidebar_width, int)
                and not isinstance(sidebar_width, bool)
                and MIN_SIDEBAR_WIDTH <= sidebar_width <= MAX_SIDEBAR_WIDTH
            ):
                prefs["sidebar_width"] = sidebar_width

            history_limit = data.get("history_limit")
            if (
                isinstance(history_limit, int)
                and not isinstance(history_limit, bool)
                and MIN_HISTORY_LIMIT <= history_limit <= MAX_HISTORY_LIMIT
            ):
                prefs["history_limit"] = history_limit
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return prefs


def save_preferences(
    font: str | None = None,
    theme: str | None = None,
    zoom_level: float | None = None,
    window_width: int | None = None,
    window_height: int | None = None,
    window_maximized: bool | None = None,
    sidebar_visible: bool | None = None,
    sidebar_width: int | None = None,
    history_limit: int | None = None,
) -> None:
    """Save updated preferences to disk, creating parent directories if needed."""
    current = load_preferences()
    if font is not None and font in VALID_FONTS:
        current["font"] = font
    if theme is not None and theme in VALID_THEMES:
        current["theme"] = theme
    if zoom_level is not None and isinstance(zoom_level, (int, float)) and MIN_ZOOM <= zoom_level <= MAX_ZOOM:
        current["zoom_level"] = round(float(zoom_level), 2)
    if window_width is not None and isinstance(window_width, int) and window_width >= MIN_WINDOW_WIDTH:
        current["window_width"] = window_width
    if window_height is not None and isinstance(window_height, int) and window_height >= MIN_WINDOW_HEIGHT:
        current["window_height"] = window_height
    if window_maximized is not None and isinstance(window_maximized, bool):
        current["window_maximized"] = window_maximized
    if sidebar_visible is not None and isinstance(sidebar_visible, bool):
        current["sidebar_visible"] = sidebar_visible
    if (
        sidebar_width is not None
        and isinstance(sidebar_width, int)
        and not isinstance(sidebar_width, bool)
        and MIN_SIDEBAR_WIDTH <= sidebar_width <= MAX_SIDEBAR_WIDTH
    ):
        current["sidebar_width"] = sidebar_width
    if (
        history_limit is not None
        and isinstance(history_limit, int)
        and not isinstance(history_limit, bool)
        and MIN_HISTORY_LIMIT <= history_limit <= MAX_HISTORY_LIMIT
    ):
        current["history_limit"] = history_limit

    path = get_config_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(current, indent=2) + "\n"
        path.write_text(content, encoding="utf-8")
    except OSError:
        pass
