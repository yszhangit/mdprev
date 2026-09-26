import importlib.util
import sys

# Each front end's tests need its toolkit; skip a directory where it is absent
# so the toolkit-neutral core tests still run everywhere.
collect_ignore = []
if importlib.util.find_spec("gi") is None:
    collect_ignore.append("gtk")
if sys.platform != "darwin" or importlib.util.find_spec("AppKit") is None:
    collect_ignore.append("macos")
