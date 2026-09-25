import json
from pathlib import Path

from mdprev.core.preferences import (
    DEFAULT_FONT,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_SIDEBAR_VISIBLE,
    DEFAULT_SIDEBAR_WIDTH,
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


def test_defaults_include_sidebar_and_history_keys(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    prefs = load_preferences()

    assert prefs["sidebar_visible"] is DEFAULT_SIDEBAR_VISIBLE
    assert prefs["sidebar_width"] == DEFAULT_SIDEBAR_WIDTH
    assert prefs["history_limit"] == DEFAULT_HISTORY_LIMIT


def test_sidebar_and_history_values_round_trip(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_preferences(sidebar_visible=True, sidebar_width=340, history_limit=25)
    prefs = load_preferences()

    assert prefs["sidebar_visible"] is True
    assert prefs["sidebar_width"] == 340
    assert prefs["history_limit"] == 25


def test_out_of_range_sidebar_width_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_preferences(sidebar_width=10_000)

    assert load_preferences()["sidebar_width"] == DEFAULT_SIDEBAR_WIDTH


def test_out_of_range_history_limit_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_preferences(history_limit=0)

    assert load_preferences()["history_limit"] == DEFAULT_HISTORY_LIMIT


def test_wrongly_typed_sidebar_values_fall_back_to_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config = tmp_path / "mdprev" / "preferences.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"sidebar_visible": "yes", "sidebar_width": "wide", "history_limit": 1.5}',
        encoding="utf-8",
    )

    prefs = load_preferences()

    assert prefs["sidebar_visible"] is DEFAULT_SIDEBAR_VISIBLE
    assert prefs["sidebar_width"] == DEFAULT_SIDEBAR_WIDTH
    assert prefs["history_limit"] == DEFAULT_HISTORY_LIMIT


def test_config_path_defaults_to_xdg_on_linux(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("mdprev.core.preferences.sys.platform", "linux")

    assert get_config_file_path() == tmp_path / ".config" / "mdprev" / "preferences.json"


def test_config_path_defaults_to_application_support_on_macos(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("mdprev.core.preferences.sys.platform", "darwin")

    assert get_config_file_path() == (
        tmp_path / "Library" / "Application Support" / "MdPrev" / "preferences.json"
    )


def test_explicit_xdg_config_home_wins_on_macos(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("mdprev.core.preferences.sys.platform", "darwin")

    assert get_config_file_path() == tmp_path / "mdprev" / "preferences.json"
