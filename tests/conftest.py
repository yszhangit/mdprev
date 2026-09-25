import importlib.util

# GTK front-end tests need PyGObject; skip the directory where it is absent
# (e.g. macOS) so the toolkit-neutral core tests still run.
collect_ignore = [] if importlib.util.find_spec("gi") else ["gtk"]
