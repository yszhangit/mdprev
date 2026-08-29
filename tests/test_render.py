from pathlib import Path

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
    assert "<pre><code" in html and "print(1)" in html


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
