"""Navigation policy for the preview's web view.

Every navigation the web view attempts is classified here; the front end only
carries out the decision.  Rendered HTML is untrusted, so anything not
explicitly allowed is blocked, and external targets open only on a user
gesture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

_EXTERNAL_SCHEMES = {"http", "https", "mailto"}
_BLOCKED_SCHEMES = {"javascript", "data"}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


@dataclass(frozen=True)
class Allow:
    """Let the web view perform the navigation itself."""


@dataclass(frozen=True)
class Block:
    """Ignore the navigation."""


@dataclass(frozen=True)
class OpenExternal:
    """Ignore the navigation and open uri in the user's default application."""

    uri: str


@dataclass(frozen=True)
class OpenDocument:
    """Ignore the navigation and open path in an MdPrev window."""

    path: Path


Decision = Allow | Block | OpenExternal | OpenDocument


def classify_link(uri: str, document_dir: Path, user_gesture: bool) -> Decision:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if scheme in _EXTERNAL_SCHEMES:
        return OpenExternal(uri) if user_gesture else Block()
    if scheme == "file":
        target = Path(unquote(parsed.path)).resolve()
        at_base = target == document_dir.resolve()
        # Loading the HTML reports its document base URI as a non-user file
        # navigation.  It must be allowed or the web view displays a blank page.
        if at_base and not user_gesture:
            return Allow()
        # Fragment-only links resolve against the HTML base directory.
        if at_base and parsed.fragment:
            return Allow()
        if target.suffix.lower() in _MARKDOWN_SUFFIXES and user_gesture:
            return OpenDocument(target)
        return Block()
    if scheme in _BLOCKED_SCHEMES:
        return Block()
    return Allow()
