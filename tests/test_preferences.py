import json
from pathlib import Path

import pytest

from mdprev.preferences import (
    DEFAULT_FONT,
    DEFAULT_THEME,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_ZOOM_LEVEL,
    get_config_file_path,
    load_preferences,
    save_preferences,
)


def test_default_preferences_when_no_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    prefs = load_preferences()
    assert prefs["font"] == DEFAULT_FONT
    assert prefs["theme"] == DEFAULT_THEME
    assert prefs["zoom_level"] == DEFAULT_ZOOM_LEVEL
    assert prefs["window_width"] == DEFAULT_WINDOW_WIDTH
    assert prefs["window_height"] == DEFAULT_WINDOW_HEIGHT
    assert prefs["window_maximized"] is False


def test_save_and_load_preferences(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_preferences(
        font="serif",
        theme="sepia",
        zoom_level=1.2,
        window_width=1000,
        window_height=800,
        window_maximized=True,
    )
    prefs = load_preferences()
    assert prefs["font"] == "serif"
    assert prefs["theme"] == "sepia"
    assert prefs["zoom_level"] == 1.2
    assert prefs["window_width"] == 1000
    assert prefs["window_height"] == 800
    assert prefs["window_maximized"] is True

    # Verify underlying file was created
    config_file = get_config_file_path()
    assert config_file.is_file()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["font"] == "serif"
    assert data["theme"] == "sepia"
    assert data["zoom_level"] == 1.2
    assert data["window_width"] == 1000
    assert data["window_height"] == 800
    assert data["window_maximized"] is True


def test_partial_update_preferences(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_preferences(font="mono")
    prefs = load_preferences()
    assert prefs["font"] == "mono"
    assert prefs["theme"] == DEFAULT_THEME
    assert prefs["zoom_level"] == DEFAULT_ZOOM_LEVEL

    save_preferences(zoom_level=1.5)
    prefs = load_preferences()
    assert prefs["font"] == "mono"
    assert prefs["zoom_level"] == 1.5

    save_preferences(window_width=1200, window_height=900)
    prefs = load_preferences()
    assert prefs["window_width"] == 1200
    assert prefs["window_height"] == 900


def test_invalid_preferences_fall_back_to_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_file = get_config_file_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        '{"font": "comic-sans", "theme": "rainbow", "zoom_level": 99.0, "window_width": 10, "window_maximized": "yes"}',
        encoding="utf-8",
    )

    prefs = load_preferences()
    assert prefs["font"] == DEFAULT_FONT
    assert prefs["theme"] == DEFAULT_THEME
    assert prefs["zoom_level"] == DEFAULT_ZOOM_LEVEL
    assert prefs["window_width"] == DEFAULT_WINDOW_WIDTH
    assert prefs["window_maximized"] is False


def test_corrupted_json_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_file = get_config_file_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("invalid json content!", encoding="utf-8")

    prefs = load_preferences()
    assert prefs["font"] == DEFAULT_FONT
    assert prefs["theme"] == DEFAULT_THEME
    assert prefs["zoom_level"] == DEFAULT_ZOOM_LEVEL


def test_ignore_invalid_save_values(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_preferences(font="serif", theme="sepia", zoom_level=1.2)
    save_preferences(font="invalid_font", theme="invalid_theme", zoom_level=-5.0)

    prefs = load_preferences()
    assert prefs["font"] == "serif"
    assert prefs["theme"] == "sepia"
    assert prefs["zoom_level"] == 1.2
