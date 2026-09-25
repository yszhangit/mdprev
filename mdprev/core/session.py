"""What a preview window shows, independent of the GUI toolkit.

A window tracks the revision shown (target), the revision it is compared
against (base, None for the implicit parent / HEAD), and the view mode.  These
functions turn that state into titles, reload decisions, and HTML, so each
front end only wires them to its widgets.
"""

from __future__ import annotations

from pathlib import Path

from . import git_history
from .git_history import WORKING_COPY, Commit, Revision
from .preferences import MAX_ZOOM, MIN_ZOOM
from .render import (
    RenderError,
    error_document,
    read_source,
    render_comparison,
    render_markdown,
)

ZOOM_STEP = 0.1
DEFAULT_ZOOM = 1.0


def _short(revision: Revision) -> str:
    return revision.short_sha if isinstance(revision, Commit) else "Working copy"


def window_titles(
    name: str, target: Revision, base: Revision | None, mode: str
) -> tuple[str, str | None]:
    """Return the window title and header subtitle (None hides it)."""

    if base is not None and mode != "rendered":
        pair = f"{_short(base)} → {_short(target)}"
        return f"{name} — {pair}", pair
    if isinstance(target, Commit):
        return (
            f"{name} — {target.short_sha}",
            f"{target.short_sha} · {target.when.strftime('%b %-d, %Y')}",
        )
    return name, None


def view_changed(
    old_target: Revision,
    old_base: Revision | None,
    target: Revision,
    base: Revision | None,
    mode: str,
) -> bool:
    """True when the displayed document differs, so scroll must reset.

    Rendered mode shows only the target, so a base-only change there is not a
    document change.  A pure mode change (target and base both unchanged)
    always returns False; the caller re-renders in place for that case.
    """

    if target != old_target:
        return True
    return mode != "rendered" and base != old_base


def reloads_on_save(target: Revision, base: Revision | None, mode: str) -> bool:
    """True when a save to the working copy should refresh what is on screen.

    Rendered mode shows only the target, so a working-copy base is irrelevant
    there; diff and side-by-side show both sides.
    """

    if target == WORKING_COPY:
        return True
    return mode != "rendered" and base == WORKING_COPY


def zoom_in(level: float) -> float:
    return min(level + ZOOM_STEP, MAX_ZOOM)


def zoom_out(level: float) -> float:
    return max(level - ZOOM_STEP, MIN_ZOOM)


def build_html(
    path: Path,
    repo,
    target: Revision,
    base: Revision | None,
    mode: str,
    font: str,
    theme: str,
) -> str:
    """Return the complete HTML document for the current view.

    Expected read, parse, and repository failures become an error document
    rather than an exception, so the window always has something to show.
    """

    try:
        if mode != "rendered" and repo is not None:
            comparison = git_history.compare(repo, path, base, target)
            return render_comparison(comparison, mode, font=font, theme=theme)
        if isinstance(target, Commit):
            source = git_history.file_at(repo, target.sha, target.path)
        else:
            source = read_source(path)
        return render_markdown(source, path.parent, font=font, theme=theme)
    except (RenderError, git_history.GitHistoryError) as exc:
        return error_document(str(exc), font=font, theme=theme)


def base_uri(path: Path) -> str:
    """The directory URI relative images and fragment links resolve against."""

    uri = path.parent.as_uri()
    return uri if uri.endswith("/") else uri + "/"
