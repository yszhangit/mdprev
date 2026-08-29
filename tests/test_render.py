from html import unescape
from pathlib import Path
import re

import pytest

from mdprev.render import RenderError, error_document, read_source, render_markdown, sanitize_fragment


def test_gfm_features_and_complete_document(tmp_path: Path):
    html = render_markdown(
        "# Heading\n\n- [x] done\n- [ ] later\n\n~~gone~~\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```",
        tmp_path,
    )
    assert "<!doctype html>" in html
    assert '<h1 id="heading">Heading</h1>' in html
    assert 'type="checkbox"' in html and "checked" in html
    assert "<del>gone</del>" in html
    assert "<table>" in html and "<td>1</td>" in html
    assert '<pre><code class="highlight language-python">' in html
    assert _code_text(html) == "print(1)\n"


def _code_text(html: str) -> str:
    block = re.search(r"<pre><code[^>]*>(.*?)</code></pre>", html, re.DOTALL)
    assert block is not None
    return unescape(re.sub(r"<[^>]+>", "", block.group(1)))


def test_every_supported_language_is_highlighted():
    source = (Path(__file__).parent / "fixtures" / "highlighting.md").read_text()
    html = render_markdown(source)
    supported = {
        "bash", "python", "javascript", "typescript", "json", "yaml", "html",
        "css", "c", "cpp", "rust", "go", "sql", "markdown", "diff",
    }
    for language in supported:
        assert f'class="highlight language-{language}"' in html


@pytest.mark.parametrize(
    ("alias", "language"),
    [
        ("sh", "bash"), ("shell", "bash"), ("py", "python"),
        ("js", "javascript"), ("ts", "typescript"), ("yml", "yaml"),
        ("htm", "html"), ("c++", "cpp"), ("rs", "rust"),
        ("golang", "go"), ("md", "markdown"), ("patch", "diff"),
    ],
)
def test_language_aliases_use_controlled_lexer(alias: str, language: str):
    html = render_markdown(f"```{alias}\nvalue = 1\n```")
    assert f'class="highlight language-{language}"' in html


@pytest.mark.parametrize("tag", ["", "unknown", "python;touch-pwned", "python<script>"])
def test_missing_unknown_and_malicious_languages_stay_plain(tag: str):
    html = render_markdown(f"```{tag}\n<& dangerous\n```")
    assert 'class="highlight' not in html
    assert "&lt;&amp; dangerous" in html
    assert "<script>" not in html


def test_highlighting_preserves_code_and_cannot_inject_markup():
    code = '<script>alert("x")</script> & café\n'
    html = render_markdown(f"```python\n{code}```")
    assert _code_text(html) == code
    assert "<script>" not in html
    assert "enable_javascript" not in html


def test_highlight_palettes_cover_light_and_dark_appearances():
    html = render_markdown("```python\nprint(1)\n```")
    assert "code.highlight .k" in html
    assert "@media (prefers-color-scheme: dark)" in html
    # Both Pygments palettes emit a rule for keyword tokens.
    assert html.count("code.highlight .k") >= 2


def test_untrusted_markup_and_resources_are_filtered(tmp_path: Path):
    html = render_markdown(
        '<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![remote](https://example.invalid/x.png)\n\n![data](data:image/png;base64,AAAA)\n',
        tmp_path,
    )
    assert "script" not in html.lower()
    assert "alert" not in html
    assert "example.invalid" not in html
    assert "data:image" not in html


def test_relative_image_becomes_local_file_uri(tmp_path: Path):
    image = tmp_path / "image with space-雪.png"
    image.touch()
    html = render_markdown("![alt](image%20with%20space-%E9%9B%AA.png)", tmp_path)
    assert image.as_uri() in html


def test_absolute_and_file_uri_images_are_not_accepted(tmp_path: Path):
    html = render_markdown(
        "![absolute](/etc/passwd)\n\n![file](file:///etc/passwd)", tmp_path
    )
    assert "file:///etc/passwd" not in html


def test_heading_anchors_are_stable_and_duplicate_safe(tmp_path: Path):
    html = render_markdown("# Hello, world!\n\n# Hello, world!", tmp_path)
    assert '<h1 id="hello-world">Hello, world!</h1>' in html
    assert '<h1 id="hello-world-2">Hello, world!</h1>' in html


def test_links_keep_safe_schemes_only():
    html = sanitize_fragment('<a href="https://example.com">web</a><a href="mailto:a@b">mail</a><a href="data:text/html,x">no</a>')
    assert 'href="https://example.com"' in html
    assert 'href="mailto:a@b"' in html
    assert 'href="#"' in html
    assert "data:" not in html


def test_invalid_utf8_is_reported(tmp_path: Path):
    source = tmp_path / "bad.md"
    source.write_bytes(b"bad\xff")
    with pytest.raises(RenderError, match="UTF-8"):
        read_source(source)


def test_missing_file_is_reported(tmp_path: Path):
    with pytest.raises(RenderError, match="Unable to read"):
        read_source(tmp_path / "missing.md")


def test_error_document_escapes_text():
    assert "&lt;script&gt;" in error_document("<script>")
    assert "<script>" not in error_document("<script>")
