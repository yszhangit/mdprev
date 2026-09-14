from html import unescape
from pathlib import Path
import re

import pytest

from mdprev import render
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


def test_custom_font_selection():
    html_serif = render_markdown("# Title\n\nText", font="serif")
    assert "DejaVu Serif" in html_serif

    html_sans = render_markdown("# Title\n\nText", font="sans")
    assert "Ubuntu" in html_sans

    html_mono = render_markdown("# Title\n\nText", font="mono")
    assert "Ubuntu Sans Mono" in html_mono


def test_theme_selection():
    for theme in ("system", "light", "dark", "sepia"):
        html = render_markdown("# Title\n\nText", theme=theme)
        assert f'data-theme="{theme}"' in html

    # Fallback to system for invalid theme
    html_invalid = render_markdown("# Title\n\nText", theme="nonexistent")
    assert 'data-theme="system"' in html_invalid


def test_render_diff_marks_the_diff_language():
    html = render.render_diff("@@ -1 +1 @@\n-old\n+new\n")

    assert 'class="highlight language-diff"' in html


def test_render_diff_escapes_html_in_patch_text():
    html = render.render_diff("@@ -1 +1 @@\n-<script>alert(1)</script>\n+safe\n")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_diff_preserves_the_patch_text_exactly():
    patch = "@@ -1,2 +1,2 @@\n-one & two\n+one < two\n"

    html = render.render_diff(patch)
    stripped = unescape(re.sub(r"<[^>]+>", "", html.split("<pre>")[1]))

    assert "one & two" in stripped
    assert "one < two" in stripped


def test_render_diff_honors_font_and_theme():
    html = render.render_diff("@@ -1 +1 @@\n-old\n+new\n", font="serif", theme="sepia")

    assert 'data-theme="sepia"' in html
    assert "DejaVu Serif" in html


def test_render_diff_reports_an_empty_patch():
    html = render.render_diff("")

    assert "No changes in this commit" in html
    assert "<pre>" not in html


def test_render_diff_does_not_invoke_cmark(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("cmark-gfm must not be invoked for diff rendering")

    monkeypatch.setattr(render.subprocess, "run", fail)

    assert "+new" in unescape(re.sub(r"<[^>]+>", "", render.render_diff("@@ -1 +1 @@\n-old\n+new\n")))


from mdprev.diffmodel import Comparison, DiffLine, FileStats, Hunk, Side  # noqa: E402


def make_comparison(**overrides):
    values = dict(
        base=Side("a1b2c3d  Old notes", "doc.md", FileStats(4, 1, 1), None),
        target=Side("Working copy", "doc.md", FileStats(8, 2, 2), None),
        patch_text="@@ -1 +1,2 @@\n one\n+two\n",
        hunks=[Hunk(1, 1, 1, 2, [DiffLine(" ", 1, 1, "one"), DiffLine("+", -1, 2, "two")])],
        additions=1,
        deletions=0,
        binary=False,
        explicit_base=True,
    )
    values.update(overrides)
    return Comparison(**values)


def test_render_comparison_header_names_both_sides_and_stats():
    html = render.render_comparison(make_comparison(), "diff")

    assert '<header class="compare">' in html
    assert "a1b2c3d  Old notes" in html
    assert "Working copy" in html
    assert "Size +4 B (4 B → 8 B) · Lines +1 −0 (net +1) · Words +1 (1 → 2)" in html


def test_render_comparison_unified_body_highlights_the_patch():
    html = render.render_comparison(make_comparison(), "diff")

    assert 'class="highlight language-diff"' in html
    assert '<main class="wide">' not in html


def test_render_comparison_escapes_labels_and_paths():
    comparison = make_comparison(
        base=Side("<b>x</b> & y", "<old>.md", FileStats(1, 1, 1), None),
        target=Side("Working copy", "new&.md", FileStats(1, 1, 1), None),
    )

    html = render.render_comparison(comparison, "diff")

    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in html
    assert "Renamed: &lt;old&gt;.md → new&amp;.md" in html


def test_render_comparison_omits_renamed_line_for_the_same_path():
    assert "Renamed:" not in render.render_comparison(make_comparison(), "diff")


def test_render_comparison_shows_missing_base_as_none():
    comparison = make_comparison(base=Side("(none)", None, FileStats(0, 0, 0), None))

    html = render.render_comparison(comparison, "diff")

    assert "(none)" in html
    assert "Renamed:" not in html


def test_render_comparison_reports_unavailable_stats():
    comparison = make_comparison(
        target=Side("Working copy", "doc.md", None, "the file is binary")
    )

    assert "Stats unavailable: the file is binary" in render.render_comparison(comparison, "diff")


def test_render_comparison_empty_message_depends_on_the_pin():
    pinned = make_comparison(patch_text="", hunks=[], additions=0)
    implicit = make_comparison(patch_text="", hunks=[], additions=0, explicit_base=False)

    assert "No changes between these versions." in render.render_comparison(pinned, "diff")
    assert "No changes in this commit." in render.render_comparison(implicit, "diff")
