"""mdprev.core must stay importable without any GUI toolkit."""

import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).parent.parent / "mdprev" / "core"

_BLOCKED = ("gi", "objc", "AppKit", "Foundation", "WebKit", "Cocoa")

_SCRIPT = f"""
import importlib, importlib.abc, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {_BLOCKED!r}:
            raise ImportError("GUI import from mdprev.core: " + name)
        return None

sys.meta_path.insert(0, Block())
for name in sys.argv[1:]:
    importlib.import_module(name)
"""


def test_core_modules_import_without_gui_toolkits():
    modules = ["mdprev.core"] + [
        f"mdprev.core.{path.stem}" for path in sorted(CORE.glob("*.py"))
        if path.stem != "__init__"
    ]
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, *modules],
        cwd=CORE.parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
