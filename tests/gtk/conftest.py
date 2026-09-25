import pytest

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


@pytest.fixture
def gtk_display():
    if not Gtk.init_check():
        pytest.skip("no display available")
