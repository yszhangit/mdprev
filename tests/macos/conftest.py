"""Fixtures for the macOS front-end tests (collected only on macOS)."""

import pytest

from macos_helpers import FakeApp


@pytest.fixture
def isolated_prefs(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def fake_app():
    return FakeApp()
