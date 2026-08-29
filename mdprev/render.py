"""Markdown rendering and safety filtering.

The parser is deliberately kept outside the GTK application so that it can be
tested without a display server.  cmark-gfm produces HTML, which is then
filtered before it is handed to WebKit.
"""

from __future__ import annotations

from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlparse


class RenderError(RuntimeError):
    """An expected error while reading or rendering a document."""


_CMARK = "cmark-gfm"
_EXTENSIONS = ("table", "tasklist", "strikethrough", "autolink", "tagfilter")
_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "img", "input", "li", "ol", "p", "pre",
    "strong", "table", "tbody", "td", "th", "thead", "tr", "ul",
}
_VOID = {"br", "hr", "img", "input"}


def read_source(path: Path) -> str:
    """Read UTF-8 source and turn expected failures into RenderError."""

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RenderError(f"Unable to read {path.name}: {exc.strerror or exc}") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenderError(f"Unable to read {path.name}: the file is not valid UTF-8") from exc


class _SafeHTML(HTMLParser):
    """Keep cmark's known-safe structural tags and filter resource URLs."""

    def __init__(self, document_dir: Path | None):
        super().__init__(convert_charrefs=False)
        self.document_dir = document_dir
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag in {"script", "style", "iframe", "object", "embed", "form"}:
                self._skip_depth += 1
            return
        if tag in {"script", "style", "iframe", "object", "embed", "form"}:
            self._skip_depth = 1
            return
        if tag not in _TAGS:
            return
        if tag == "img":
            src = dict(attrs).get("src") or ""
            local = _local_image_uri(src, self.document_dir)
            if not local:
                return
            attrs = [("src", local)] + [(k, v) for k, v in attrs if k != "src"]
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if not _allowed_link(href):
                attrs = [(k, ("#" if k == "href" else v)) for k, v in attrs if k != "href"]
                attrs.insert(0, ("href", "#"))
        safe_attrs = []
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name in {"style", "srcset"}:
                continue
            if name not in {"alt", "checked", "class", "disabled", "height", "href", "id", "lang", "src", "title", "type", "width"}:
                continue
            safe_attrs.append(f' {name}="{escape(value or "", quote=True)}"')
        self.parts.append("<" + tag + "".join(safe_attrs) + (" />" if tag in _VOID else ">"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag.lower() in {"script", "style", "iframe", "object", "embed", "form"}:
                self._skip_depth -= 1
            return
        if tag.lower() in _TAGS and tag.lower() not in _VOID:
            self.parts.append(f"</{tag.lower()}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        # cmark comments are parser output, not user HTML.  Drop all comments.
        return


def _allowed_link(value: str) -> bool:
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if value.startswith("//"):
        return False
    return scheme in {"", "http", "https", "mailto"} and not scheme == "data"


def _local_image_uri(value: str, document_dir: Path | None) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme.lower() in {"http", "https", "data", "javascript"} or value.startswith("//"):
        return None
    if document_dir is None:
        return None
    try:
        if parsed.scheme or Path(unquote(parsed.path)).is_absolute():
            return None
        else:
            candidate = (document_dir / unquote(parsed.path)).resolve()
        # A file URI may point anywhere on the local machine, but only images
        # requested by the document are loaded.  Existence is checked by WebKit.
        return candidate.as_uri()
    except (OSError, ValueError):
        return None


def sanitize_fragment(fragment: str, document_dir: Path | None = None) -> str:
    parser = _SafeHTML(document_dir)
    parser.feed(fragment)
    parser.close()
    return "".join(parser.parts)


def render_markdown(source: str, document_dir: Path | None = None) -> str:
    """Return a complete safe HTML document for Markdown source."""

    command = [_CMARK, "--to", "html"]
    for extension in _EXTENSIONS:
        command.extend(("--extension", extension))
    try:
        result = subprocess.run(
            command, input=source.encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
    except OSError as exc:
        raise RenderError(f"Unable to run cmark-gfm: {exc.strerror or exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RenderError(f"Markdown rendering failed{': ' + detail if detail else ''}")
    try:
        fragment = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenderError("Markdown renderer returned invalid UTF-8") from exc
    body = _heading_ids(sanitize_fragment(fragment, document_dir))
    return _document(body)


def error_document(message: str) -> str:
    return _document(f'<div class="error"><h1>Unable to preview file</h1><p>{escape(message)}</p></div>')


def _document(body: str) -> str:
    return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { color-scheme: light dark; }
html, body { margin: 0; padding: 0; }
body { background: #fafafa; color: #242424; font: 16px/1.55 system-ui, sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 2.5rem 2rem 5rem; }
h1, h2, h3, h4, h5, h6 { line-height: 1.2; margin: 1.6em 0 .6em; }
h1 { font-size: 2.1rem; } h2 { font-size: 1.6rem; }
a { color: #1a5fb4; } img { max-width: 100%; height: auto; }
blockquote { margin: 1rem 0; padding: .2rem 1rem; border-left: 4px solid #bbb; color: #555; }
code, pre { font-family: ui-monospace, monospace; }
code { padding: .12em .3em; border-radius: 4px; background: #e8e8e8; }
pre { overflow-x: auto; padding: 1rem; border-radius: 7px; background: #eeeeee; }
pre code { padding: 0; background: transparent; }
table { border-collapse: collapse; display: block; overflow-x: auto; max-width: 100%; }
th, td { border: 1px solid #b9b9b9; padding: .4rem .65rem; }
th { background: #e7e7e7; } .error { max-width: 42rem; }
@media (prefers-color-scheme: dark) {
 body { background: #242424; color: #eee; } a { color: #78aeed; }
 blockquote { color: #bbb; border-color: #777; } code { background: #3b3b3b; }
 pre { background: #303030; } th { background: #3b3b3b; } th, td { border-color: #666; }
}
</style></head><body><main>""" + body + "</main></body></html>"


def _heading_ids(body: str) -> str:
    """Add stable, readable fragment IDs to cmark's heading elements."""

    used: dict[str, int] = {}

    def replace(match: re.Match[str]) -> str:
        tag, inner = match.group(1), match.group(2)
        plain = unescape(re.sub(r"<[^>]*>", "", inner))
        plain = unicodedata.normalize("NFKD", plain).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9 -]", "", plain.lower())
        slug = re.sub(r"\s+", "-", slug).strip("-") or "section"
        used[slug] = used.get(slug, 0) + 1
        if used[slug] > 1:
            slug = f"{slug}-{used[slug]}"
        return f'<{tag} id="{slug}">{inner}</{tag}>'

    return re.sub(r"<(h[1-6])>(.*?)</\1>", replace, body, flags=re.IGNORECASE | re.DOTALL)
