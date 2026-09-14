# Revision Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the reader pin any version of the document in the history sidebar and compare it with any other version (including uncommitted changes) as a unified or side-by-side diff, with size/line/word stats on every row and in every diff.

**Architecture:** A new pure-Python module `mdprev/diffmodel.py` holds stats, formatting, the pin-availability rule, and the plain dataclasses describing a comparison. `git_history.compare()` builds one `pygit2.Patch` per comparison and converts it to those dataclasses; `render.render_comparison()` turns them into HTML (unified or a two-column table). `sidebar.py` gains pins, stats labels, and a third view mode, and reports `(target, base, mode)`; `app.py` renders whatever it is told.

**Tech Stack:** Python 3, PyGObject (GTK 4, WebKitGTK 6.0), pygit2 1.19.1, Pygments, stdlib `difflib`, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-14-compare-revisions-design.md`

## Global Constraints

- Ubuntu 26.04 system packages only; no new runtime dependencies (`difflib` is stdlib).
- Run tests with the system interpreter: `/usr/bin/python3 -m pytest` (never the `venv/`).
- Lint with `ruff check mdprev tests`; it must report "All checks passed!".
- The git integration is strictly read-only: never write the repository or the source file.
- JavaScript stays disabled; all diff text is escaped and never passed to `cmark-gfm`.
- `mdprev/diffmodel.py` must not import GTK, pygit2, or `git_history`. `mdprev/render.py` must not import pygit2 or `git_history`.
- Avoid broad exception handling; catch explicit exception types only.
- pygit2-dependent tests sit behind `pytest.importorskip("pygit2")`; GTK widget tests skip when `Gtk.init_check()` fails.
- Commit messages: imperative sentence subject, no `feat:` prefix, ending with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik
  ```
- Mode strings are exactly `"rendered"`, `"diff"`, `"side-by-side"`.
- Minus signs in user-facing deltas are U+2212 `−`; zero deltas are `±0`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `mdprev/diffmodel.py` | Create | `FileStats`, `StatsUnavailable`, `stats_for`, `format_size`, `format_delta`, `format_stats`, `pins_available`, `DiffLine`, `Hunk`, `Side`, `Comparison`, `stats_line` |
| `mdprev/git_history.py` | Modify | `WorkingCopy`/`WORKING_COPY`/`Revision`, `revision_stats`, `compare`; `patch_for`/`working_patch` become wrappers over `compare` |
| `mdprev/render.py` | Modify | `_diff_body` (extracted), `render_comparison`, side-by-side table, comparison header, diff colors, `wide` layout |
| `mdprev/sidebar.py` | Modify | `Revision` selection, three-mode switch, pins, stats labels, `clear_pin` |
| `mdprev/app.py` | Modify | `window_titles`, `(target, base)` state, comparison loading, two-step Escape, live reload rule |
| `tests/test_diffmodel.py` | Create | Pure tests for `diffmodel.py` |
| `tests/test_git_history.py` | Modify | `compare`, `revision_stats` tests |
| `tests/test_render.py` | Modify | Header, unified, side-by-side tests |
| `tests/conftest.py` | Create | Shared `gtk_display` fixture |
| `tests/test_sidebar.py` | Create | GTK widget tests with real temporary repositories |
| `tests/test_app.py` | Modify | `window_titles` tests; fixture moves to conftest |
| `FEATURE_REQUIREMENTS.md`, `README.md`, `AGENTS.md` | Modify | MVP 5 requirements and user docs |

---

### Task 1: `diffmodel.py` — stats, formatting, pin rule, comparison records

**Files:**
- Create: `mdprev/diffmodel.py`
- Test: `tests/test_diffmodel.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FileStats(size: int, lines: int, words: int)` (frozen), `EMPTY_STATS = FileStats(0, 0, 0)`
  - `class StatsUnavailable(ValueError)`; `stats_for(data: bytes) -> FileStats` raises it with message `"the file is binary"` or `"the file is not valid UTF-8"`
  - `format_size(size: int) -> str`, `format_delta(value: int) -> str`, `format_stats(stats: FileStats) -> str`
  - `pins_available(loaded_commits: int, has_more: bool, modified: bool) -> bool`
  - `DiffLine(origin: str, old_lineno: int, new_lineno: int, text: str)`
  - `Hunk(old_start: int, old_lines: int, new_start: int, new_lines: int, lines: list[DiffLine])`
  - `Side(label: str, path: str | None, stats: FileStats | None, stats_error: str | None)`
  - `Comparison(base: Side, target: Side, patch_text: str, hunks: list[Hunk], additions: int, deletions: int, binary: bool, explicit_base: bool)`
  - `stats_line(comparison: Comparison) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diffmodel.py`:

```python
"""Pure comparison model: no GTK, no pygit2."""

import pytest

from mdprev.diffmodel import (
    EMPTY_STATS,
    Comparison,
    FileStats,
    Side,
    StatsUnavailable,
    format_delta,
    format_size,
    format_stats,
    pins_available,
    stats_for,
    stats_line,
)


def test_stats_for_empty_content():
    assert stats_for(b"") == FileStats(size=0, lines=0, words=0)
    assert EMPTY_STATS == FileStats(0, 0, 0)


def test_stats_for_counts_bytes_lines_and_words():
    assert stats_for(b"one two\nthree\n") == FileStats(size=14, lines=2, words=3)


def test_stats_for_counts_a_last_line_without_newline():
    assert stats_for(b"a\nb").lines == 2


def test_stats_for_handles_crlf():
    assert stats_for(b"a b\r\nc\r\n") == FileStats(size=8, lines=2, words=3)


def test_stats_for_counts_utf8_bytes_and_non_ascii_words():
    assert stats_for("héllo wörld\n".encode("utf-8")) == FileStats(size=14, lines=1, words=2)


def test_stats_for_rejects_binary_content():
    with pytest.raises(StatsUnavailable, match="the file is binary"):
        stats_for(b"abc\x00def")


def test_stats_for_rejects_invalid_utf8():
    with pytest.raises(StatsUnavailable, match="the file is not valid UTF-8"):
        stats_for(b"\xff\xfe")


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (4300, "4.2 KB"), (1024 * 1024, "1.0 MB")],
)
def test_format_size(size, expected):
    assert format_size(size) == expected


@pytest.mark.parametrize(("value", "expected"), [(3, "+3"), (-11, "−11"), (0, "±0")])
def test_format_delta(value, expected):
    assert format_delta(value) == expected


def test_format_stats_pluralizes():
    assert format_stats(FileStats(4300, 118, 812)) == "4.2 KB · 118 lines · 812 words"
    assert format_stats(FileStats(5, 1, 1)) == "5 B · 1 line · 1 word"


@pytest.mark.parametrize(
    ("loaded", "has_more", "modified", "expected"),
    [
        (1, False, False, False),  # one commit, clean copy
        (1, False, True, True),    # one commit plus uncommitted changes
        (3, False, False, True),   # several commits
        (3, False, True, True),
        (0, False, False, False),  # untracked / unborn / no history
        (0, False, True, False),
        (1, True, False, True),    # more pages exist beyond the one loaded
    ],
)
def test_pins_available(loaded, has_more, modified, expected):
    assert pins_available(loaded, has_more, modified) is expected


def _comparison(base_stats, target_stats, additions=0, deletions=0,
                base_error=None, target_error=None):
    return Comparison(
        base=Side("a1b2c3d  Old", "doc.md", base_stats, base_error),
        target=Side("Working copy", "doc.md", target_stats, target_error),
        patch_text="",
        hunks=[],
        additions=additions,
        deletions=deletions,
        binary=False,
        explicit_base=True,
    )


def test_stats_line_reports_signed_deltas():
    comparison = _comparison(FileStats(4300, 118, 812), FileStats(3988, 110, 760),
                             additions=3, deletions=11)

    assert stats_line(comparison) == (
        "Size −312 B (4.2 KB → 3.9 KB) · Lines +3 −11 (net −8) · Words −52 (812 → 760)"
    )


def test_stats_line_shows_zero_deltas_as_plus_minus_zero():
    same = FileStats(10, 1, 2)

    assert stats_line(_comparison(same, same)) == (
        "Size ±0 B (10 B → 10 B) · Lines +0 −0 (net ±0) · Words ±0 (2 → 2)"
    )


def test_stats_line_reports_unavailable_stats():
    comparison = _comparison(FileStats(1, 1, 1), None, target_error="the file is binary")

    assert stats_line(comparison) == "Stats unavailable: the file is binary"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/test_diffmodel.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'mdprev.diffmodel'`

- [ ] **Step 3: Write the implementation**

Create `mdprev/diffmodel.py`:

```python
"""Plain data and rules for comparing two versions of a document.

Nothing here imports GTK or pygit2, so render.py can use these records where
pygit2 is absent and the rules can be tested without a display server.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileStats:
    size: int
    lines: int
    words: int


EMPTY_STATS = FileStats(size=0, lines=0, words=0)


class StatsUnavailable(ValueError):
    """The content cannot be counted as text."""


def stats_for(data: bytes) -> FileStats:
    """Count bytes, lines, and whitespace-separated words of UTF-8 text."""

    # The same NUL heuristic git uses to call content binary.
    if b"\x00" in data[:8000]:
        raise StatsUnavailable("the file is binary")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StatsUnavailable("the file is not valid UTF-8") from exc
    return FileStats(size=len(data), lines=len(text.splitlines()), words=len(text.split()))


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def format_delta(value: int) -> str:
    if value == 0:
        return "±0"
    return f"+{value}" if value > 0 else f"−{-value}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def format_stats(stats: FileStats) -> str:
    return (
        f"{format_size(stats.size)} · {_plural(stats.lines, 'line')} · "
        f"{_plural(stats.words, 'word')}"
    )


def pins_available(loaded_commits: int, has_more: bool, modified: bool) -> bool:
    """Report whether at least two versions exist to compare.

    A modified working copy is a version of its own; an unmodified one has the
    newest commit's content and is not.  An unloaded page of history counts as
    at least one more commit.
    """

    if loaded_commits >= 1 and has_more:
        return True
    return loaded_commits + (1 if modified else 0) >= 2


@dataclass(frozen=True)
class DiffLine:
    origin: str  # " ", "+", or "-"
    old_lineno: int  # -1 when the line is absent from the base
    new_lineno: int  # -1 when the line is absent from the target
    text: str  # without its line ending


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine]


@dataclass(frozen=True)
class Side:
    label: str
    path: str | None
    stats: FileStats | None
    stats_error: str | None


@dataclass(frozen=True)
class Comparison:
    base: Side
    target: Side
    patch_text: str
    hunks: list[Hunk]
    additions: int
    deletions: int
    binary: bool
    explicit_base: bool


def _size_delta(value: int) -> str:
    if value == 0:
        return "±0 B"
    sign = "+" if value > 0 else "−"
    return f"{sign}{format_size(abs(value))}"


def stats_line(comparison: Comparison) -> str:
    base = comparison.base.stats
    target = comparison.target.stats
    if base is None or target is None:
        reason = comparison.base.stats_error or comparison.target.stats_error
        return f"Stats unavailable: {reason}"
    return (
        f"Size {_size_delta(target.size - base.size)} "
        f"({format_size(base.size)} → {format_size(target.size)}) · "
        f"Lines +{comparison.additions} −{comparison.deletions} "
        f"(net {format_delta(target.lines - base.lines)}) · "
        f"Words {format_delta(target.words - base.words)} ({base.words} → {target.words})"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_diffmodel.py -v && ruff check mdprev tests`
Expected: all PASS; "All checks passed!"

- [ ] **Step 5: Commit**

```bash
git add mdprev/diffmodel.py tests/test_diffmodel.py
git commit -m "Add the pure comparison model: stats, formatting, and pin rule

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

---

### Task 2: `git_history.compare()` and `revision_stats()`

**Files:**
- Modify: `mdprev/git_history.py` (add after `Commit`/`Cursor`/`History` records; replace `patch_for` at lines 283-311 and `working_patch` at lines 314-347)
- Test: `tests/test_git_history.py`

**Interfaces:**
- Consumes: from `mdprev.diffmodel`: `EMPTY_STATS`, `Comparison`, `DiffLine`, `FileStats`, `Hunk`, `Side`, `StatsUnavailable`, `stats_for`.
- Produces:
  - `class WorkingCopy` (frozen dataclass, no fields), `WORKING_COPY = WorkingCopy()`, `Revision = Commit | WorkingCopy`
  - `revision_stats(repo, path: Path, revision: Revision) -> FileStats | None`
  - `compare(repo, path: Path, base: Revision | None, target: Revision) -> Comparison`
    - `path` is the open document on disk (used for the working copy and the repo-relative name).
    - `base=None`, or `base == target`, means the implicit base: first parent for a commit, HEAD for the working copy. `explicit_base` is `True` only otherwise.
    - Side labels: `f"{short_sha}  {summary or '(no message)'}"` for commits (two spaces), `"Working copy"`, or `"(none)"` when that side has no content.
    - Raises `GitHistoryError` on libgit2/`KeyError`/`OSError` failures, unknown revisions, and unreadable working copies.
  - `patch_for(repo, sha, path) -> str` and `working_patch(repo, path) -> str` keep their signatures and behavior.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_git_history.py` (the helpers `repo_factory`, `commit_file`, `rename_file` already exist in this file):

```python
from mdprev.diffmodel import EMPTY_STATS, FileStats  # noqa: E402


def records(repo, workdir, relpath="doc.md"):
    """Commit records touching relpath, newest first."""
    return git_history.history(repo, workdir / relpath, limit=50).commits


def test_working_copy_marker_is_a_single_equal_value():
    assert git_history.WORKING_COPY == git_history.WorkingCopy()


def test_compare_two_commits_explicitly(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "one\ntwo\n", "Second", when=1700000100)
    commit_file(repo, workdir, "doc.md", "one\ntwo\nthree\n", "Third", when=1700000200)
    third, _second, first = records(repo, workdir)

    comparison = git_history.compare(repo, workdir / "doc.md", first, third)

    assert comparison.explicit_base is True
    assert comparison.base.label == f"{first.short_sha}  First"
    assert comparison.target.label == f"{third.short_sha}  Third"
    assert comparison.additions == 2
    assert comparison.deletions == 0
    assert "+three" in comparison.patch_text
    assert comparison.base.stats == FileStats(size=4, lines=1, words=1)
    assert comparison.target.stats == FileStats(size=14, lines=3, words=3)


def test_compare_newer_base_against_older_target_reads_base_to_target(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "one\ntwo\nthree\n", "Second", when=1700000100)
    second, first = records(repo, workdir)

    comparison = git_history.compare(repo, workdir / "doc.md", second, first)

    assert comparison.additions == 0
    assert comparison.deletions == 2
    assert "-three" in comparison.patch_text


def test_compare_commit_against_the_working_copy(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (first,) = records(repo, workdir)
    (workdir / "doc.md").write_text("edited text\n", encoding="utf-8")

    comparison = git_history.compare(
        repo, workdir / "doc.md", first, git_history.WORKING_COPY
    )

    assert comparison.target.label == "Working copy"
    assert comparison.target.stats == FileStats(size=12, lines=1, words=2)
    assert "+edited text" in comparison.patch_text


def test_compare_working_copy_as_base(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (first,) = records(repo, workdir)
    (workdir / "doc.md").write_text("edited\n", encoding="utf-8")

    comparison = git_history.compare(
        repo, workdir / "doc.md", git_history.WORKING_COPY, first
    )

    assert comparison.base.label == "Working copy"
    assert "-edited" in comparison.patch_text
    assert "+committed" in comparison.patch_text


def test_compare_root_commit_has_no_base(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First")
    (first,) = records(repo, workdir)

    comparison = git_history.compare(repo, workdir / "doc.md", None, first)

    assert comparison.explicit_base is False
    assert comparison.base.label == "(none)"
    assert comparison.base.path is None
    assert comparison.base.stats == EMPTY_STATS
    assert comparison.additions == 1


def test_compare_selecting_the_pinned_version_uses_the_implicit_base(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "two\n", "Second", when=1700000100)
    second, first = records(repo, workdir)

    comparison = git_history.compare(repo, workdir / "doc.md", second, second)

    assert comparison.explicit_base is False
    assert comparison.base.label == f"{first.short_sha}  First"


def test_compare_across_a_rename_reports_both_paths(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename", when=1700000100)
    commit_file(repo, workdir, "new.md", "shared content\n" * 20 + "more\n", "Edit",
                when=1700000200)
    edit, _rename, add = records(repo, workdir, "new.md")

    comparison = git_history.compare(repo, workdir / "new.md", add, edit)

    assert comparison.base.path == "old.md"
    assert comparison.target.path == "new.md"
    assert "+more" in comparison.patch_text


def test_compare_implicit_base_of_a_rename_uses_the_old_name(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename", when=1700000100)
    rename, _add = records(repo, workdir, "new.md")

    comparison = git_history.compare(repo, workdir / "new.md", None, rename)

    assert comparison.base.path == "old.md"
    assert "old.md" in comparison.patch_text


def test_compare_unchanged_versions_is_empty(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "same\n", "First")
    (first,) = records(repo, workdir)

    comparison = git_history.compare(
        repo, workdir / "doc.md", first, git_history.WORKING_COPY
    )

    assert comparison.patch_text == ""
    assert comparison.hunks == []
    assert (comparison.additions, comparison.deletions) == (0, 0)


def test_compare_hunk_lines_agree_with_line_counts(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "a\nb\nc\nd\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "a\nB\nc\nd\ne", "Second", when=1700000100)
    second, first = records(repo, workdir)

    comparison = git_history.compare(repo, workdir / "doc.md", first, second)
    lines = [line for hunk in comparison.hunks for line in hunk.lines]

    assert {line.origin for line in lines} <= {" ", "+", "-"}
    assert sum(line.origin == "+" for line in lines) == comparison.additions
    assert sum(line.origin == "-" for line in lines) == comparison.deletions
    assert [line.text for line in lines if line.origin == "+"] == ["B", "e"]
    removed = next(line for line in lines if line.origin == "-")
    assert (removed.old_lineno, removed.new_lineno) == (2, -1)


def test_compare_binary_content_has_no_stats(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "text\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", b"\x00\x01binary", "Second", when=1700000100)
    second, first = records(repo, workdir)

    comparison = git_history.compare(repo, workdir / "doc.md", first, second)

    assert comparison.binary is True
    assert comparison.target.stats is None
    assert comparison.target.stats_error == "the file is binary"


def test_compare_rejects_an_unreadable_working_copy(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First")
    (first,) = records(repo, workdir)
    (workdir / "doc.md").unlink()

    with pytest.raises(git_history.GitHistoryError):
        git_history.compare(repo, workdir / "doc.md", first, git_history.WORKING_COPY)


def test_revision_stats_for_commit_and_working_copy(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one two\n", "First")
    (first,) = records(repo, workdir)
    (workdir / "doc.md").write_text("one two three\n", encoding="utf-8")

    assert git_history.revision_stats(repo, workdir / "doc.md", first) == FileStats(8, 1, 2)
    assert git_history.revision_stats(
        repo, workdir / "doc.md", git_history.WORKING_COPY
    ) == FileStats(14, 1, 3)


def test_revision_stats_is_none_for_unusable_content(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", b"\xff\xfe", "Invalid", when=1700000000)
    commit_file(repo, workdir, "doc.md", b"\x00bin", "Binary", when=1700000100)
    binary, invalid = records(repo, workdir)

    assert git_history.revision_stats(repo, workdir / "doc.md", binary) is None
    assert git_history.revision_stats(repo, workdir / "doc.md", invalid) is None


def test_revision_stats_is_none_where_the_commit_deleted_the_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    repo.index.remove("doc.md")
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000100, 0)
    repo.create_commit("HEAD", signature, signature, "Delete", tree, [repo.head.target])
    deletion = records(repo, workdir)[0]

    assert git_history.revision_stats(repo, workdir / "doc.md", deletion) is None
```

Also extend the existing `test_expected_libgit2_failures_convert_to_git_history_error` by adding, at its end:

```python
    record = git_history.Commit(
        sha=sha, short_sha=sha[:7], summary="First", author="Test Author",
        when=None, path="doc.md",
    )
    with pytest.raises(git_history.GitHistoryError):
        git_history.compare(repo, workdir / "doc.md", None, record)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: the new tests FAIL with `AttributeError: module 'mdprev.git_history' has no attribute 'WORKING_COPY'` (or `compare` / `revision_stats`); existing tests PASS.

- [ ] **Step 3: Add the working-copy marker and imports**

In `mdprev/git_history.py`, add to the imports (after `from pathlib import Path`):

```python
from .diffmodel import (
    EMPTY_STATS,
    Comparison,
    DiffLine,
    FileStats,
    Hunk,
    Side,
    StatsUnavailable,
    stats_for,
)
```

After the `History` dataclass add:

```python
@dataclass(frozen=True)
class WorkingCopy:
    """The file on disk, as opposed to a committed revision."""


WORKING_COPY = WorkingCopy()
Revision = Commit | WorkingCopy
```

- [ ] **Step 4: Replace `patch_for` and `working_patch` with `compare` and wrappers**

Replace the whole of `patch_for()` and `working_patch()` with:

```python
_DIFF_ORIGINS = {" ", "+", "-"}


def _label(revision: Revision) -> str:
    if isinstance(revision, WorkingCopy):
        return "Working copy"
    return f"{revision.short_sha}  {revision.summary or '(no message)'}"


def _read_working_copy(path: Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise GitHistoryError(
            f"Unable to read {Path(path).name}: {exc.strerror or exc}"
        ) from exc


def _resolve(repo, path: Path, relative: str, revision: Revision):
    """Return (label, repo-relative path, blob or bytes or None) for revision."""

    if isinstance(revision, WorkingCopy):
        return _label(revision), relative, _read_working_copy(path)
    commit = _lookup_commit(repo, revision.sha)
    return _label(revision), revision.path, _entry(commit.tree, revision.path)


def _implicit_base(repo, relative: str, target: Revision, target_content):
    """Return (label, path, content, rename patch) of target's default base.

    That is HEAD for the working copy and the first parent for a commit.  A
    side without the file is labelled "(none)".  When the commit renamed the
    file, the parent's content is read under the old name and the
    rename-detecting patch is returned so its "renamed from" header survives
    (see _rename_patch).
    """

    none = ("(none)", None, None, None)
    if isinstance(target, WorkingCopy):
        if repo.head_is_unborn:
            return none
        head = repo[repo.head.target]
        blob = _entry(head.tree, relative)
        if blob is None:
            return none
        return _label(_commit_record(head, relative)), relative, blob, None
    commit = _lookup_commit(repo, target.sha)
    if not commit.parents:
        return none
    parent = commit.parents[0]
    blob = _entry(parent.tree, target.path)
    if blob is not None:
        return _label(_commit_record(parent, target.path)), target.path, blob, None
    if target_content is not None:
        renamed = _rename_patch(repo, parent, commit, target.path)
        if renamed is not None:
            old_path = renamed.delta.old_file.path
            return (
                _label(_commit_record(parent, old_path)),
                old_path,
                _entry(parent.tree, old_path),
                renamed,
            )
    return none


def _content_bytes(content) -> bytes | None:
    # Blob content is loaded lazily; callers must keep this inside their
    # libgit2 error guard (see file_at).
    if content is None or isinstance(content, bytes):
        return content
    return content.data


def _side(label: str, path: str | None, data: bytes | None) -> Side:
    if data is None:
        return Side(label=label, path=None, stats=EMPTY_STATS, stats_error=None)
    try:
        return Side(label=label, path=path, stats=stats_for(data), stats_error=None)
    except StatsUnavailable as exc:
        return Side(label=label, path=path, stats=None, stats_error=str(exc))


def _hunks(patch) -> list[Hunk]:
    hunks = []
    for hunk in patch.hunks:
        lines = [
            DiffLine(
                origin=line.origin,
                old_lineno=line.old_lineno,
                new_lineno=line.new_lineno,
                text=line.raw_content.decode("utf-8", errors="replace")
                .removesuffix("\n")
                .removesuffix("\r"),
            )
            # "<", ">" and "=" mark end-of-file newline notes, not lines.
            for line in hunk.lines
            if line.origin in _DIFF_ORIGINS
        ]
        hunks.append(
            Hunk(hunk.old_start, hunk.old_lines, hunk.new_start, hunk.new_lines, lines)
        )
    return hunks


def compare(repo, path: Path, base: Revision | None, target: Revision) -> Comparison:
    """Compare two versions of the document at path, reading base → target.

    base None (or equal to target) selects target's implicit base.  One
    Patch is built and both the unified text and the hunks come from it, so
    the unified and side-by-side views can never disagree.
    """

    relative = _relative_path(repo, path)
    explicit = base is not None and base != target
    try:
        target_label, target_path, target_content = _resolve(repo, path, relative, target)
        rename_patch = None
        if explicit:
            base_label, base_path, base_content = _resolve(repo, path, relative, base)
        else:
            base_label, base_path, base_content, rename_patch = _implicit_base(
                repo, relative, target, target_content
            )
        base_data = _content_bytes(base_content)
        target_data = _content_bytes(target_content)
        if rename_patch is not None:
            patch = rename_patch
        elif not base_data and not target_data:
            patch = None
        else:
            patch = pygit2.Patch.create_from(
                base_content,
                target_content,
                old_as_path=base_path or target_path,
                new_as_path=target_path or base_path,
            )
        return Comparison(
            base=_side(base_label, base_path, base_data),
            target=_side(target_label if target_content is not None else "(none)",
                         target_path, target_data),
            patch_text=(patch.text or "") if patch is not None else "",
            hunks=_hunks(patch) if patch is not None else [],
            additions=patch.line_stats[1] if patch is not None else 0,
            deletions=patch.line_stats[2] if patch is not None else 0,
            binary=patch is not None and patch.delta.is_binary,
            explicit_base=explicit,
        )
    except (pygit2.GitError, KeyError, OSError) as exc:
        raise GitHistoryError(f"Unable to compare versions of {Path(path).name}") from exc


def revision_stats(repo, path: Path, revision: Revision) -> FileStats | None:
    """Return the stats of one version, or None when they cannot be counted."""

    try:
        if isinstance(revision, WorkingCopy):
            data = _read_working_copy(path)
        else:
            commit = _lookup_commit(repo, revision.sha)
            blob = _entry(commit.tree, revision.path)
            if blob is None:
                return None
            data = blob.data
        return stats_for(data)
    except (GitHistoryError, StatsUnavailable, pygit2.GitError, KeyError, OSError):
        return None


def patch_for(repo, sha: str, path: str) -> str:
    """Return the unified diff of path at sha against its first parent."""

    commit = _lookup_commit(repo, sha)
    try:
        record = _commit_record(commit, path)
    except (pygit2.GitError, KeyError, OSError) as exc:
        raise GitHistoryError(f"Unable to read {path} at {sha[:7]}") from exc
    return compare(repo, Path(repo.workdir) / path, None, record).patch_text


def working_patch(repo, path: Path) -> str:
    """Return the unified diff of the file on disk against HEAD.

    Unlike is_modified(), a path outside the repository is left to raise
    GitHistoryError here rather than being swallowed: the caller renders that
    error as visible text, and reporting an empty diff for a genuinely
    invalid path would be misleading.
    """

    return compare(repo, path, None, WORKING_COPY).patch_text
```

Note: `patch_for` passes `Path(repo.workdir) / path` because `compare` derives the repo-relative name from a filesystem path; for a commit target only `Commit.path` is used, so the file need not exist on disk.

- [ ] **Step 5: Run the whole git history suite**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v && ruff check mdprev tests`
Expected: all PASS, including the pre-existing `patch_for`/`working_patch` tests (merge, rename, root commit, unreadable file); "All checks passed!"

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Compare any two versions of a document through one patch

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

---

### Task 3: Comparison header and unified comparison rendering

**Files:**
- Modify: `mdprev/render.py` (`render_diff` at lines 287-312, `_document` at lines 315-445)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `mdprev.diffmodel.Comparison`, `Side`, `FileStats`, `Hunk`, `DiffLine`, `stats_line`.
- Produces:
  - `render_comparison(comparison: Comparison, mode: str, font: str = "system", theme: str = "system") -> str` — in this task `mode` `"diff"` renders unified; `"side-by-side"` is added in Task 4.
  - `_document(body, font="system", theme="system", wide=False)` — `wide=True` gives `<main class="wide">`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/test_render.py -v`
Expected: new tests FAIL with `AttributeError: module 'mdprev.render' has no attribute 'render_comparison'`

- [ ] **Step 3: Extract `_diff_body` and add the header and `render_comparison`**

In `mdprev/render.py` add to the imports:

```python
from .diffmodel import Comparison, stats_line
```

Replace `render_diff` with:

```python
def _diff_body(patch: str, empty_message: str) -> str:
    """Return the highlighted unified diff, or empty_message for no changes.

    cmark is deliberately not involved: a patch must never be parsed as
    Markdown.  Highlighting reuses the DiffLexer already available for fenced
    code blocks, so themes and palettes apply unchanged.
    """

    if not patch.strip():
        return f'<p class="empty">{escape(empty_message)}</p>'
    highlighted = highlight(patch, DiffLexer(), HtmlFormatter(nowrap=True))
    # The formatter must never be allowed to change the patch text.
    rendered_text = unescape(re.sub(r"<[^>]+>", "", highlighted))
    if rendered_text.rstrip("\n") != patch.rstrip("\n"):
        return f'<pre><code class="language-diff">{escape(patch)}</code></pre>'
    return f'<pre><code class="highlight language-diff">{highlighted}</code></pre>'


def render_diff(patch: str, font: str = "system", theme: str = "system") -> str:
    """Return a complete HTML document showing a unified diff."""

    return _document(_diff_body(patch, "No changes in this commit."), font=font, theme=theme)


def _comparison_header(comparison: Comparison) -> str:
    base, target = comparison.base, comparison.target
    parts = [
        '<header class="compare">',
        f'<p class="sides"><span class="side">{escape(base.label)}</span>'
        f' <span class="arrow">→</span> '
        f'<span class="side">{escape(target.label)}</span></p>',
        f'<p class="stats">{escape(stats_line(comparison))}</p>',
    ]
    if base.path and target.path and base.path != target.path:
        parts.append(
            f'<p class="renamed">Renamed: {escape(base.path)} → {escape(target.path)}</p>'
        )
    parts.append("</header>")
    return "".join(parts)


def _empty_message(comparison: Comparison) -> str:
    if comparison.explicit_base:
        return "No changes between these versions."
    return "No changes in this commit."


def render_comparison(
    comparison: Comparison, mode: str, font: str = "system", theme: str = "system"
) -> str:
    """Return a complete HTML document comparing two versions.

    Every piece of text is escaped; nothing here is parsed as Markdown.
    """

    header = _comparison_header(comparison)
    body = _diff_body(comparison.patch_text, _empty_message(comparison))
    return _document(header + body, font=font, theme=theme)
```

Change the `_document` signature and its `<main>` tag:

```python
def _document(body: str, font: str = "system", theme: str = "system", wide: bool = False) -> str:
```

```python
</style></head><body><main{' class="wide"' if wide else ''}>{body}</main></body></html>"""
```

Add these rules right after the `.empty { ... }` rule inside the `<style>` block:

```css
main.wide {{ max-width: none; }}
.compare {{ margin: 0 0 1.25rem; padding-bottom: .75rem; border-bottom: 1px solid var(--table-border); }}
.compare p {{ margin: .15rem 0; }}
.compare .side {{ font-weight: 600; }}
.compare .stats, .compare .renamed {{ color: var(--quote-color); font-size: .9rem; }}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_render.py -v && ruff check mdprev tests`
Expected: all PASS (including the six pre-existing `render_diff` tests); "All checks passed!"

- [ ] **Step 5: Commit**

```bash
git add mdprev/render.py tests/test_render.py
git commit -m "Render a comparison header with stats above the unified diff

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

---

### Task 4: Side-by-side table

**Files:**
- Modify: `mdprev/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `render_comparison`, `_comparison_header`, `_empty_message`, `_document(..., wide=)` from Task 3; `Comparison`, `Hunk`, `DiffLine`.
- Produces: `render_comparison(comparison, "side-by-side", ...)` renders a `<table class="sbs">` inside `<main class="wide">`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:

```python
def _rows(html):
    """Return each table row as a list of (cell class, cell inner HTML)."""
    return [
        re.findall(r'<td class="([\w ]+)"(?: colspan="4")?>(.*?)</td>', row, re.DOTALL)
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    ]


def _sbs(hunks, base_lines, **overrides):
    comparison = make_comparison(
        hunks=hunks, base=Side("a1b2c3d  Old", "doc.md", FileStats(1, base_lines, 1), None),
        **overrides,
    )
    return render.render_comparison(comparison, "side-by-side")


def test_side_by_side_is_a_wide_table():
    html = _sbs([Hunk(1, 1, 1, 1, [DiffLine(" ", 1, 1, "same")])], base_lines=1)

    assert '<main class="wide">' in html
    assert '<table class="sbs">' in html
    assert '<header class="compare">' in html


def test_side_by_side_pairs_equal_runs():
    hunk = Hunk(1, 3, 1, 3, [
        DiffLine(" ", 1, 1, "a"),
        DiffLine("-", 2, -1, "old"),
        DiffLine("+", -1, 2, "new"),
        DiffLine(" ", 3, 3, "c"),
    ])

    rows = _rows(_sbs([hunk], base_lines=3))

    assert [[cls for cls, _ in row] for row in rows] == [
        ["ln", "ctx", "ln", "ctx"],
        ["ln", "del", "ln", "add"],
        ["ln", "ctx", "ln", "ctx"],
    ]
    assert rows[1][0][1] == "2" and rows[1][2][1] == "2"


def test_side_by_side_pads_a_longer_deletion_run():
    hunk = Hunk(1, 2, 1, 1, [
        DiffLine("-", 1, -1, "one"),
        DiffLine("-", 2, -1, "two"),
        DiffLine("+", -1, 1, "uno"),
    ])

    rows = _rows(_sbs([hunk], base_lines=2))

    assert [[cls for cls, _ in row] for row in rows] == [
        ["ln", "del", "ln", "add"],
        ["ln", "del", "ln", "none"],
    ]
    assert rows[1][2][1] == ""


def test_side_by_side_pads_a_longer_addition_run():
    hunk = Hunk(1, 1, 1, 2, [
        DiffLine("-", 1, -1, "one"),
        DiffLine("+", -1, 1, "uno"),
        DiffLine("+", -1, 2, "dos"),
    ])

    rows = _rows(_sbs([hunk], base_lines=1))

    assert [cls for cls, _ in rows[1]] == ["ln", "none", "ln", "add"]


def test_side_by_side_pure_additions_and_deletions():
    added = Hunk(0, 0, 1, 1, [DiffLine("+", -1, 1, "new")])
    deleted = Hunk(1, 1, 0, 0, [DiffLine("-", 1, -1, "gone")])

    assert [cls for cls, _ in _rows(_sbs([added], base_lines=0))[0]] == ["ln", "none", "ln", "add"]
    assert [cls for cls, _ in _rows(_sbs([deleted], base_lines=1))[0]] == ["ln", "del", "ln", "none"]


def test_side_by_side_folds_unchanged_stretches():
    first = Hunk(10, 1, 10, 1, [DiffLine("-", 10, -1, "x"), DiffLine("+", -1, 10, "y")])
    second = Hunk(20, 1, 20, 1, [DiffLine("-", 20, -1, "p"), DiffLine("+", -1, 20, "q")])

    html = _sbs([first, second], base_lines=30)
    folds = re.findall(r'<tr class="fold"><td class="fold" colspan="4">(.*?)</td></tr>', html)

    assert folds == ["⋯ 9 unchanged lines", "⋯ 9 unchanged lines", "⋯ 10 unchanged lines"]


def test_side_by_side_fold_after_an_insertion_hunk():
    # "-3,0 +4,2" inserts after base line 3; base lines 1-3 precede it.
    hunk = Hunk(3, 0, 4, 2, [DiffLine("+", -1, 4, "a"), DiffLine("+", -1, 5, "b")])

    html = _sbs([hunk], base_lines=5)
    folds = re.findall(r'colspan="4">(.*?)</td>', html)

    assert folds == ["⋯ 3 unchanged lines", "⋯ 2 unchanged lines"]


def test_side_by_side_singular_fold():
    hunk = Hunk(2, 1, 2, 1, [DiffLine("-", 2, -1, "x"), DiffLine("+", -1, 2, "y")])

    assert "⋯ 1 unchanged line<" in _sbs([hunk], base_lines=2)


def test_side_by_side_highlights_changed_words_in_similar_lines():
    hunk = Hunk(1, 1, 1, 1, [
        DiffLine("-", 1, -1, "the quick brown fox"),
        DiffLine("+", -1, 1, "the quick red fox"),
    ])

    html = _sbs([hunk], base_lines=1)

    assert "<del>brown</del>" in html
    assert "<ins>red</ins>" in html


def test_side_by_side_skips_word_highlights_for_dissimilar_lines():
    hunk = Hunk(1, 1, 1, 1, [
        DiffLine("-", 1, -1, "alpha beta"),
        DiffLine("+", -1, 1, "totally different words here"),
    ])

    html = _sbs([hunk], base_lines=1)

    assert "<del>" not in html.split("<table")[1]
    assert "<ins>" not in html.split("<table")[1]


def test_side_by_side_escapes_line_text():
    hunk = Hunk(1, 1, 1, 1, [
        DiffLine("-", 1, -1, "<script>alert(1)</script> & co"),
        DiffLine("+", -1, 1, "<script>alert(2)</script> & co"),
    ])

    html = _sbs([hunk], base_lines=1)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; co" in html


def test_side_by_side_needs_utf8_text():
    binary = make_comparison(binary=True)
    undecodable = make_comparison(
        target=Side("Working copy", "doc.md", None, "the file is not valid UTF-8")
    )

    for comparison in (binary, undecodable):
        html = render.render_comparison(comparison, "side-by-side")
        assert "Side-by-side view needs UTF-8 text on both sides." in html
        assert '<header class="compare">' in html


def test_side_by_side_empty_comparison():
    html = _sbs([], base_lines=3, patch_text="", additions=0)

    assert "No changes between these versions." in html
    assert '<table class="sbs">' not in html


def test_diff_palette_is_defined_for_every_theme():
    html = render.render_comparison(make_comparison(), "side-by-side")

    for theme in ('html[data-theme="light"]', 'html[data-theme="dark"]', 'html[data-theme="sepia"]'):
        block = html.split(theme + " {", 1)[1].split("}", 1)[0]
        assert "--diff-del-bg" in block and "--diff-add-word" in block
    assert html.count("--diff-fold:") >= 5  # :root, system dark, light, dark, sepia
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/test_render.py -k "side_by_side or diff_palette" -v`
Expected: FAIL — no `<table class="sbs">` in the output (side-by-side still renders unified).

- [ ] **Step 3: Implement the table**

In `mdprev/render.py` add `import difflib` to the stdlib imports, extend the diffmodel import to `from .diffmodel import Comparison, DiffLine, stats_line`, and add above `render_comparison`:

```python
_TOKEN = re.compile(r"\s+|\w+|[^\w\s]")
_WORD_DIFF_MIN_RATIO = 0.5


def _word_diff(old: str, new: str) -> tuple[str, str]:
    """Return escaped old/new text with differing tokens wrapped.

    Lines that share less than half their tokens are shown as a plain
    replacement: highlighting scattered fragments of unrelated lines hides
    more than it shows.
    """

    a = _TOKEN.findall(old)
    b = _TOKEN.findall(new)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if matcher.ratio() < _WORD_DIFF_MIN_RATIO:
        return escape(old), escape(new)
    left: list[str] = []
    right: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_part = escape("".join(a[i1:i2]))
        new_part = escape("".join(b[j1:j2]))
        if tag == "equal":
            left.append(old_part)
            right.append(new_part)
            continue
        if old_part:
            left.append(f"<del>{old_part}</del>")
        if new_part:
            right.append(f"<ins>{new_part}</ins>")
    return "".join(left), "".join(right)


def _lineno(value: int) -> str:
    return str(value) if value > 0 else ""


def _sbs_row(old: DiffLine | None, new: DiffLine | None) -> str:
    if old is not None and new is not None and old.origin == " ":
        text = escape(old.text)
        return (
            f'<tr><td class="ln">{_lineno(old.old_lineno)}</td><td class="ctx">{text}</td>'
            f'<td class="ln">{_lineno(new.new_lineno)}</td><td class="ctx">{text}</td></tr>'
        )
    if old is not None and new is not None:
        left, right = _word_diff(old.text, new.text)
    else:
        left = escape(old.text) if old is not None else ""
        right = escape(new.text) if new is not None else ""
    return (
        f'<tr><td class="ln">{_lineno(old.old_lineno) if old else ""}</td>'
        f'<td class="{"del" if old else "none"}">{left}</td>'
        f'<td class="ln">{_lineno(new.new_lineno) if new else ""}</td>'
        f'<td class="{"add" if new else "none"}">{right}</td></tr>'
    )


def _fold_row(count: int) -> str:
    noun = "line" if count == 1 else "lines"
    return (
        f'<tr class="fold"><td class="fold" colspan="4">'
        f"⋯ {count} unchanged {noun}</td></tr>"
    )


def _side_by_side_body(comparison: Comparison) -> str:
    if comparison.binary or comparison.base.stats is None or comparison.target.stats is None:
        return '<p class="empty">Side-by-side view needs UTF-8 text on both sides.</p>'
    if not comparison.hunks:
        return f'<p class="empty">{escape(_empty_message(comparison))}</p>'

    rows: list[str] = []
    shown_through = 0  # last base line number covered by a hunk
    for hunk in comparison.hunks:
        # A hunk that removes nothing names the base line it follows.
        first_old = hunk.old_start if hunk.old_lines else hunk.old_start + 1
        if first_old - 1 > shown_through:
            rows.append(_fold_row(first_old - 1 - shown_through))
        shown_through = first_old + hunk.old_lines - 1

        lines = hunk.lines
        i = 0
        while i < len(lines):
            if lines[i].origin == " ":
                rows.append(_sbs_row(lines[i], lines[i]))
                i += 1
                continue
            removed: list[DiffLine] = []
            while i < len(lines) and lines[i].origin == "-":
                removed.append(lines[i])
                i += 1
            added: list[DiffLine] = []
            while i < len(lines) and lines[i].origin == "+":
                added.append(lines[i])
                i += 1
            for k in range(max(len(removed), len(added))):
                rows.append(_sbs_row(
                    removed[k] if k < len(removed) else None,
                    added[k] if k < len(added) else None,
                ))
    if comparison.base.stats.lines > shown_through:
        rows.append(_fold_row(comparison.base.stats.lines - shown_through))

    return (
        '<table class="sbs"><colgroup><col class="ln"><col><col class="ln"><col>'
        f'</colgroup><tbody>{"".join(rows)}</tbody></table>'
    )
```

Replace the body of `render_comparison` with:

```python
    header = _comparison_header(comparison)
    if mode == "side-by-side":
        return _document(
            header + _side_by_side_body(comparison), font=font, theme=theme, wide=True
        )
    body = _diff_body(comparison.patch_text, _empty_message(comparison))
    return _document(header + body, font=font, theme=theme)
```

- [ ] **Step 4: Add the diff palette and table CSS**

In `_document`'s `<style>`, add these five custom properties to **each** palette block — the values differ per block:

`:root` and `html[data-theme="light"]`:
```css
  --diff-del-bg: #fbe3e4;
  --diff-add-bg: #e2f5e7;
  --diff-del-word: #f5b8bb;
  --diff-add-word: #a9e2b9;
  --diff-fold: #ececec;
```

`@media (prefers-color-scheme: dark) { html[data-theme="system"] { ... } }` and `html[data-theme="dark"]`:
```css
    --diff-del-bg: #4a2527;
    --diff-add-bg: #1f3d2a;
    --diff-del-word: #7a3438;
    --diff-add-word: #2f6b44;
    --diff-fold: #303030;
```

`html[data-theme="sepia"]`:
```css
  --diff-del-bg: #f2d6c9;
  --diff-add-bg: #dfe8c8;
  --diff-del-word: #e3ad98;
  --diff-add-word: #c2d49a;
  --diff-fold: #e8deca;
```

(Remember the `_document` string is an f-string: literal braces are doubled, `{{ }}`. Custom property lines contain no braces.)

After the `.compare` rules from Task 3 add:

```css
table.sbs {{ display: table; width: 100%; table-layout: fixed; border-collapse: collapse; font-family: 'Ubuntu Sans Mono', 'Ubuntu Mono', 'DejaVu Sans Mono', ui-monospace, monospace; font-size: .9rem; line-height: 1.45; }}
table.sbs col.ln {{ width: 3.5em; }}
table.sbs td {{ border: 0; padding: 0 .5rem; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere; }}
table.sbs td.ln {{ text-align: right; color: var(--quote-color); user-select: none; }}
table.sbs td.del {{ background: var(--diff-del-bg); }}
table.sbs td.add {{ background: var(--diff-add-bg); }}
table.sbs del {{ background: var(--diff-del-word); text-decoration: none; }}
table.sbs ins {{ background: var(--diff-add-word); text-decoration: none; }}
table.sbs tr.fold td {{ text-align: center; color: var(--quote-color); background: var(--diff-fold); padding: .15rem .5rem; }}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_render.py -v && ruff check mdprev tests`
Expected: all PASS; "All checks passed!"

- [ ] **Step 6: Commit**

```bash
git add mdprev/render.py tests/test_render.py
git commit -m "Render comparisons side by side with word highlights and folds

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

---

### Task 5: Sidebar and window report `(target, base, mode)` with three view modes

Behavior-preserving refactor plus the third mode: the working copy becomes `WORKING_COPY` instead of `None`, the callback gains a `base` argument (always `None` in this task), and both diff modes render through `compare()`.

**Files:**
- Create: `tests/conftest.py`, `tests/test_sidebar.py`
- Modify: `mdprev/sidebar.py` (whole file), `mdprev/app.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `git_history.WORKING_COPY`, `Revision`, `Commit`, `compare`; `render.render_comparison`.
- Produces:
  - `HistorySidebar(on_select: Callable[[Revision, Revision | None, str], None])`
  - `HistorySidebar._rows: dict[str, Gtk.ListBoxRow]` keyed by `_key(revision)` (`"working"` or the sha); `HistorySidebar._mode_buttons: list[Gtk.ToggleButton]`; `HistorySidebar._emit() -> None` — tests and Task 6 rely on these.
  - `sidebar._key(revision: Revision) -> str`
  - `app.window_titles(name: str, target: Revision, base: Revision | None, mode: str) -> tuple[str, str | None]`
  - `PreviewWindow._target: Revision`, `PreviewWindow._base: Revision | None`

- [ ] **Step 1: Move the display fixture to a conftest**

Create `tests/conftest.py`:

```python
import pytest

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


@pytest.fixture
def gtk_display():
    if not Gtk.init_check():
        pytest.skip("no display available")
```

In `tests/test_app.py` delete the local `gtk_display` fixture (the `@pytest.fixture` block) and keep `from gi.repository import Gtk` (still used by `test_choice_row_has_no_nested_popup`).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_app.py`:

```python
from datetime import datetime, timezone  # noqa: E402

from mdprev.git_history import WORKING_COPY, Commit  # noqa: E402


def _commit(sha="a1b2c3d" + "0" * 33):
    return Commit(sha=sha, short_sha=sha[:7], summary="Notes", author="A",
                  when=datetime(2026, 9, 2, tzinfo=timezone.utc), path="doc.md")


def test_window_titles_for_the_working_copy():
    assert app_module.window_titles("doc.md", WORKING_COPY, None, "rendered") == ("doc.md", None)


def test_window_titles_for_a_commit():
    assert app_module.window_titles("doc.md", _commit(), None, "diff") == (
        "doc.md — a1b2c3d", "a1b2c3d · Sep 2, 2026",
    )


def test_window_titles_for_a_comparison():
    base = _commit("9f8e7d6" + "0" * 33)

    assert app_module.window_titles("doc.md", WORKING_COPY, base, "side-by-side") == (
        "doc.md — 9f8e7d6 → Working copy", "9f8e7d6 → Working copy",
    )


def test_window_titles_ignore_the_base_in_rendered_mode():
    assert app_module.window_titles("doc.md", WORKING_COPY, _commit(), "rendered") == (
        "doc.md", None,
    )
```

Create `tests/test_sidebar.py`:

```python
"""History sidebar behavior, against real temporary repositories."""

import pytest

pygit2 = pytest.importorskip("pygit2")

from mdprev.git_history import WORKING_COPY  # noqa: E402
from mdprev.sidebar import HistorySidebar  # noqa: E402


def commit_doc(repo, workdir, content, message, when):
    (workdir / "doc.md").write_text(content, encoding="utf-8")
    repo.index.add("doc.md")
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return str(repo.create_commit("HEAD", signature, signature, message, tree, parents))


@pytest.fixture
def repo(tmp_path, gtk_display):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    return pygit2.init_repository(str(workdir)), workdir


def load_sidebar(repo, workdir):
    calls = []
    sidebar = HistorySidebar(lambda target, base, mode: calls.append((target, base, mode)))
    sidebar.load(repo, workdir / "doc.md", 10)
    return sidebar, calls


def test_loading_reports_nothing(repo):
    commit_doc(*repo, "one\n", "First", 1700000000)

    _sidebar, calls = load_sidebar(*repo)

    assert calls == []


def test_mode_switch_offers_three_modes(repo):
    commit_doc(*repo, "one\n", "First", 1700000000)
    sidebar, calls = load_sidebar(*repo)

    assert [button.get_label() for button in sidebar._mode_buttons] == [
        "Rendered", "Diff", "Side by side",
    ]
    sidebar._mode_buttons[2].set_active(True)

    assert calls[-1] == (WORKING_COPY, None, "side-by-side")


def test_selecting_a_commit_reports_its_record(repo):
    sha = commit_doc(*repo, "one\n", "First", 1700000000)
    sidebar, calls = load_sidebar(*repo)

    sidebar._list.select_row(sidebar._rows[sha])

    target, base, mode = calls[-1]
    assert target.sha == sha
    assert (base, mode) == (None, "rendered")


def test_select_working_copy_reports_the_marker(repo):
    sha = commit_doc(*repo, "one\n", "First", 1700000000)
    sidebar, calls = load_sidebar(*repo)
    sidebar._list.select_row(sidebar._rows[sha])

    sidebar.select_working_copy()

    assert calls[-1] == (WORKING_COPY, None, "rendered")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/test_app.py tests/test_sidebar.py -v`
Expected: FAIL — `window_titles` missing; `_mode_buttons`/`_rows` missing; callback called with two arguments.

- [ ] **Step 4: Rewrite `mdprev/sidebar.py`**

Replace the file with:

```python
"""Git history sidebar.

The widget owns the commit list and the view toggle and reports selections
through a plain callback.  The window reacts to the callback and does not
reach into the widget's internals.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from . import git_history  # noqa: E402
from .git_history import WORKING_COPY, Commit, Revision, WorkingCopy  # noqa: E402


# The application has no other GTK-level styling; all document styling lives
# inside the WebKit document.  The palette fallbacks come first so that a theme
# without the named colors still renders a colored dot.
_CSS = b"""
.mdprev-dot {
  font-size: 12px;
}
.mdprev-dot-modified {
  color: #e01b24;
  color: @error_color;
}
.mdprev-dot-clean {
  color: #2ec27e;
  color: @success_color;
}
.mdprev-sidebar-message {
  padding: 12px;
}
"""

_CSS_INSTALLED = False

_MODES = (("rendered", "Rendered"), ("diff", "Diff"), ("side-by-side", "Side by side"))


def install_css() -> None:
    """Register the sidebar's style classes once on the default display."""

    global _CSS_INSTALLED
    if _CSS_INSTALLED:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _CSS_INSTALLED = True


def _key(revision: Revision) -> str:
    return "working" if isinstance(revision, WorkingCopy) else revision.sha


class HistorySidebar(Gtk.Box):
    def __init__(self, on_select: Callable[[Revision, Revision | None, str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        install_css()
        self._on_select = on_select
        self._repo = None
        self._path: Path | None = None
        self._limit = 10
        self._commits: list[Commit] = []
        self._cursor = None
        self._truncated = False
        self._message: str | None = None
        self._mode = "rendered"
        self._selected: Revision = WORKING_COPY
        self._rows: dict[str, Gtk.ListBoxRow] = {}
        # Rebuilding the list re-emits row selection; suppress the callback so
        # a refresh never looks like a user choosing a revision.
        self._suppress = False

        self._list = Gtk.ListBox()
        self._list.add_css_class("navigation-sidebar")
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.connect("row-selected", self._row_selected)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self._list)
        self.append(scroller)
        self.append(self._build_mode_switch())

    def _build_mode_switch(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("linked")
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_homogeneous(True)

        self._mode_buttons: list[Gtk.ToggleButton] = []
        for mode, label in _MODES:
            button = Gtk.ToggleButton(label=label)
            if self._mode_buttons:
                button.set_group(self._mode_buttons[0])
            button.set_active(mode == self._mode)
            button.connect("toggled", self._mode_toggled, mode)
            box.append(button)
            self._mode_buttons.append(button)
        return box

    def _mode_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        # Each group change toggles two buttons; only the newly active one counts.
        if not button.get_active() or mode == self._mode:
            return
        self._mode = mode
        self._emit()

    # -- loading ---------------------------------------------------------

    def load(self, repo, path: Path, limit: int) -> None:
        """Query history for path and rebuild the list."""

        self._repo = repo
        self._path = path
        self._limit = limit
        self._commits = []
        self._cursor = None
        self._truncated = False
        self._message = None
        if repo is None:
            self._message = "Not in a git repository"
        elif not git_history.is_tracked(repo, path):
            self._message = "Not tracked in this repository"
        else:
            self._fetch(after=None)
        self._rebuild()

    def _fetch(self, after) -> None:
        try:
            result = git_history.history(
                self._repo, self._path, limit=self._limit, after=after
            )
        except git_history.GitHistoryError as exc:
            self._message = str(exc)
            return
        self._commits.extend(result.commits)
        self._cursor = result.next_cursor
        self._truncated = result.truncated
        if not self._commits and self._message is None:
            if self._repo.head_is_unborn:
                self._message = "No commits yet"
            else:
                self._message = "No history for this file"

    def _load_more(self) -> None:
        self._fetch(after=self._cursor)
        self._rebuild()

    def refresh_status(self) -> None:
        """Update only the working-copy row's dot and label."""

        if self._repo is None or self._path is None:
            return
        modified = git_history.is_modified(self._repo, self._path)
        self._apply_status(modified)

    def _apply_status(self, modified: bool) -> None:
        if not hasattr(self, "_dot_label"):
            return
        self._dot_label.remove_css_class("mdprev-dot-modified")
        self._dot_label.remove_css_class("mdprev-dot-clean")
        self._dot_label.add_css_class(
            "mdprev-dot-modified" if modified else "mdprev-dot-clean"
        )
        text = "Modified" if modified else "Unchanged"
        self._status_label.set_text(text)
        # The dot reinforces the label rather than carrying the state alone.
        self._dot_label.update_property([Gtk.AccessibleProperty.LABEL], [text])

    # -- rows ------------------------------------------------------------

    def _rebuild(self) -> None:
        self._suppress = True
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)
        self._rows = {}

        self._list.append(self._working_row())

        # The selected commit can fall off the currently loaded page (e.g. a
        # deep "Show more" selection, refetched after the sidebar was hidden
        # and reshown). The window is still displaying it, so the list must
        # still visibly indicate it rather than silently falling back to
        # "Working copy" while a historic revision is on screen.
        loaded = {commit.sha for commit in self._commits}
        extras = [
            revision for revision in (self._selected,)
            if isinstance(revision, Commit) and revision.sha not in loaded
        ]
        for commit in extras + self._commits:
            self._list.append(self._commit_row(commit))
        if self._message is not None:
            self._list.append(self._message_row(self._message))
        if self._truncated:
            self._list.append(
                self._message_row(f"History truncated after {git_history.MAX_SCAN} commits")
            )
        if self._cursor is not None:
            self._list.append(self._action_row("Show more", self._load_more))

        self._list.select_row(self._rows.get(_key(self._selected), self._rows["working"]))
        self._suppress = False
        if self._repo is not None and self._path is not None:
            self.refresh_status()

    def _working_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = WORKING_COPY
        row.action = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        title = Gtk.Label(label="Working copy", xalign=0.0)
        title.add_css_class("heading")

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._dot_label = Gtk.Label(label="●")
        self._dot_label.add_css_class("mdprev-dot")
        self._status_label = Gtk.Label(label="Unchanged", xalign=0.0)
        self._status_label.add_css_class("dim-label")
        status_box.append(self._dot_label)
        status_box.append(self._status_label)

        box.append(title)
        box.append(status_box)
        row.set_child(box)
        self._rows["working"] = row
        return row

    def _commit_row(self, commit: Commit) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = commit
        row.action = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sha = Gtk.Label(label=commit.short_sha, xalign=0.0)
        sha.add_css_class("monospace")
        when = Gtk.Label(label=commit.when.strftime("%b %-d, %Y"), xalign=1.0)
        when.add_css_class("dim-label")
        when.set_hexpand(True)
        top.append(sha)
        top.append(when)

        summary = Gtk.Label(label=commit.summary or "(no message)", xalign=0.0)
        summary.set_ellipsize(Pango.EllipsizeMode.END)
        summary.set_tooltip_text(f"{commit.summary}\n{commit.author}")

        box.append(top)
        box.append(summary)
        row.set_child(box)
        self._rows[commit.sha] = row
        return row

    def _message_row(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = None
        row.action = None
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(label=text, xalign=0.0)
        label.set_wrap(True)
        label.add_css_class("dim-label")
        label.add_css_class("mdprev-sidebar-message")
        row.set_child(label)
        return row

    def _action_row(self, text: str, callback) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.revision = None
        row.action = callback
        row.set_selectable(False)
        button = Gtk.Button(label=text)
        button.add_css_class("flat")
        button.connect("clicked", lambda _button: callback())
        row.set_child(button)
        return row

    # -- selection -------------------------------------------------------

    def _row_selected(self, _list, row) -> None:
        if self._suppress or row is None:
            return
        revision = getattr(row, "revision", None)
        if revision is None:
            return
        self._selected = revision
        self._emit()

    def _emit(self) -> None:
        self._on_select(self._selected, None, self._mode)

    def select_working_copy(self) -> None:
        """Return to the working copy, as Escape and sidebar-close do."""

        # No guard on self._selected here: the caller (PreviewWindow) is the
        # authority on whether a historic revision is on screen, and it only
        # calls this when one is. Bailing out early based on self._selected
        # alone would repeat the desync this method exists to correct: this
        # field can legitimately be out of step with what the window is
        # displaying (see _rebuild), and skipping the callback in that case
        # would leave a historic revision on screen with nothing selected.
        self._selected = WORKING_COPY
        self._rebuild()
        self._emit()
```

- [ ] **Step 5: Update `mdprev/app.py`**

Change imports:

```python
from . import git_history  # noqa: E402
from .git_history import WORKING_COPY, Commit, Revision  # noqa: E402
from .preferences import load_preferences, save_preferences  # noqa: E402
from .render import (  # noqa: E402
    RenderError,
    error_document,
    read_source,
    render_comparison,
    render_markdown,
)
```

Add after `choice_row`:

```python
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
```

In `PreviewWindow.__init__` replace `self._revision_commit = None` with:

```python
        # What the sidebar last reported: the version shown, and the version it
        # is compared against (None for its implicit parent / HEAD).
        self._target: Revision = WORKING_COPY
        self._base: Revision | None = None
```

Replace `_history_selected`, `_show_working_copy`, and `_update_titles` with:

```python
    def _history_selected(self, target: Revision, base: Revision | None, mode: str) -> None:
        changed = target != self._target or base != self._base
        self._target = target
        self._base = base
        self._mode = mode
        self._update_titles()
        if changed:
            # A different document: start at the top rather than restoring an
            # offset that means nothing here.
            self.load_document()
        else:
            self.refresh_document()

    def _show_working_copy(self) -> None:
        if self._target == WORKING_COPY:
            return
        self._sidebar.select_working_copy()

    def _update_titles(self) -> None:
        title, subtitle = window_titles(self.path.name, self._target, self._base, self._mode)
        self.set_title(title)
        self._subtitle_label.set_text(subtitle or "")
        self._subtitle_label.set_visible(subtitle is not None)
```

In `_reload_timeout` replace `if self._revision_commit is not None:` with `if self._target != WORKING_COPY:`.

Replace the `try:` block of `load_document` with:

```python
        try:
            if self._mode != "rendered" and self._repo is not None:
                comparison = git_history.compare(
                    self._repo, self.path, self._base, self._target
                )
                html = render_comparison(
                    comparison, self._mode, font=self._font, theme=self._theme
                )
            elif isinstance(self._target, Commit):
                source = git_history.file_at(
                    self._repo, self._target.sha, self._target.path
                )
                html = render_markdown(
                    source, self.path.parent, font=self._font, theme=self._theme
                )
            else:
                source = read_source(self.path)
                html = render_markdown(
                    source, self.path.parent, font=self._font, theme=self._theme
                )
        except (RenderError, git_history.GitHistoryError) as exc:
            html = error_document(str(exc), font=self._font, theme=self._theme)
```

Run `grep -n "_revision_commit\|render_diff" mdprev/app.py` — expected: no output.

- [ ] **Step 6: Run the full suite and lint**

Run: `/usr/bin/python3 -m pytest -v && ruff check mdprev tests`
Expected: all PASS; "All checks passed!"

- [ ] **Step 7: Smoke-launch the app**

MdPrev is single-instance: if another MdPrev window is open, the launch is forwarded to that (possibly installed, older) process. Check first:

Run: `pgrep -af "python3 -m mdprev"`
Expected: no output. If there is output, ask the user to close MdPrev before continuing; do not kill it.

Run: `timeout 5 /usr/bin/python3 -m mdprev README.md; echo "exit=$?"`
Expected: no traceback on stderr; `exit=124` (killed by timeout while running).

- [ ] **Step 8: Commit**

```bash
git add mdprev/sidebar.py mdprev/app.py tests/conftest.py tests/test_sidebar.py tests/test_app.py
git commit -m "Report selections as target and base, with a side-by-side mode

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

---

### Task 6: Pins, stats labels, two-step Escape, and live reload for comparisons

**Files:**
- Modify: `mdprev/sidebar.py`, `mdprev/app.py`
- Test: `tests/test_sidebar.py`

**Interfaces:**
- Consumes: Task 5's sidebar (`_rows`, `_emit`, `_key`, `_rebuild`, `_working_row`, `_commit_row`, `refresh_status`); `diffmodel.format_stats`, `pins_available`, `FileStats`; `git_history.revision_stats`.
- Produces:
  - `HistorySidebar.clear_pin() -> bool`
  - `HistorySidebar._pin_buttons: dict[str, Gtk.Button]`, `HistorySidebar._pinned: Revision | None`, `HistorySidebar._stats_labels: dict[str, Gtk.Label]` (used by tests)
  - Pinned button carries CSS class `mdprev-pin-active`; every pin button carries `mdprev-pin`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sidebar.py`:

```python
def visible_pins(sidebar):
    return {key for key, button in sidebar._pin_buttons.items() if button.get_visible()}


def test_no_pins_for_one_commit_and_a_clean_copy(repo):
    commit_doc(*repo, "one\n", "First", 1700000000)

    sidebar, _calls = load_sidebar(*repo)

    assert visible_pins(sidebar) == set()


def test_uncommitted_changes_make_both_rows_pinnable(repo):
    repo_obj, workdir = repo
    sha = commit_doc(repo_obj, workdir, "one\n", "First", 1700000000)
    (workdir / "doc.md").write_text("changed\n", encoding="utf-8")

    sidebar, _calls = load_sidebar(repo_obj, workdir)

    assert visible_pins(sidebar) == {"working", sha}


def test_clean_copy_row_is_not_pinnable_among_commits(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)

    sidebar, _calls = load_sidebar(*repo)

    assert visible_pins(sidebar) == {first, second}


def test_pinning_alone_reports_nothing(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)

    sidebar._pin_buttons[first].emit("clicked")

    assert calls == []
    assert sidebar._pin_buttons[first].has_css_class("mdprev-pin-active")
    assert sidebar._pinned.sha == first


def test_selecting_another_row_compares_against_the_pin(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)
    sidebar._pin_buttons[first].emit("clicked")

    sidebar._list.select_row(sidebar._rows[second])

    target, base, _mode = calls[-1]
    assert (target.sha, base.sha) == (second, first)


def test_selecting_the_pinned_row_uses_the_implicit_base(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)
    sidebar._pin_buttons[first].emit("clicked")

    sidebar._list.select_row(sidebar._rows[first])

    target, base, _mode = calls[-1]
    assert (target.sha, base) == (first, None)


def test_moving_the_pin_keeps_one_pin(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, _calls = load_sidebar(*repo)

    sidebar._pin_buttons[first].emit("clicked")
    sidebar._pin_buttons[second].emit("clicked")

    active = {k for k, b in sidebar._pin_buttons.items() if b.has_css_class("mdprev-pin-active")}
    assert active == {second}


def test_unpinning_the_base_on_screen_rerenders_without_it(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)
    sidebar._pin_buttons[first].emit("clicked")
    sidebar._list.select_row(sidebar._rows[second])

    sidebar._pin_buttons[first].emit("clicked")

    target, base, _mode = calls[-1]
    assert (target.sha, base) == (second, None)
    assert sidebar._pinned is None


def test_unpinning_an_unused_pin_reports_nothing(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)

    sidebar._pin_buttons[first].emit("clicked")
    sidebar._pin_buttons[first].emit("clicked")

    assert calls == []


def test_clear_pin(repo):
    first = commit_doc(*repo, "one\n", "First", 1700000000)
    second = commit_doc(*repo, "two\n", "Second", 1700000100)
    sidebar, calls = load_sidebar(*repo)

    assert sidebar.clear_pin() is False

    sidebar._pin_buttons[first].emit("clicked")
    sidebar._list.select_row(sidebar._rows[second])
    assert sidebar.clear_pin() is True
    assert calls[-1][1] is None
    assert sidebar._pinned is None


def test_working_copy_pin_clears_when_the_file_matches_head_again(repo):
    repo_obj, workdir = repo
    sha = commit_doc(repo_obj, workdir, "one\n", "First", 1700000000)
    (workdir / "doc.md").write_text("changed\n", encoding="utf-8")
    sidebar, calls = load_sidebar(repo_obj, workdir)
    sidebar._pin_buttons["working"].emit("clicked")
    sidebar._list.select_row(sidebar._rows[sha])
    assert calls[-1][1] == WORKING_COPY

    (workdir / "doc.md").write_text("one\n", encoding="utf-8")
    sidebar.refresh_status()

    assert sidebar._pinned is None
    assert calls[-1][1] is None
    assert visible_pins(sidebar) == set()


def test_rows_show_stats(repo):
    repo_obj, workdir = repo
    sha = commit_doc(repo_obj, workdir, "one two\n", "First", 1700000000)
    (workdir / "doc.md").write_text("one two three\n", encoding="utf-8")

    sidebar, _calls = load_sidebar(repo_obj, workdir)

    assert sidebar._stats_labels[sha].get_text() == "8 B · 1 line · 2 words"
    assert sidebar._stats_labels["working"].get_text() == "14 B · 1 line · 3 words"


def test_stats_label_hidden_for_binary_content(repo):
    repo_obj, workdir = repo
    (workdir / "doc.md").write_bytes(b"\x00binary")
    repo_obj.index.add("doc.md")
    repo_obj.index.write()
    tree = repo_obj.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000000, 0)
    sha = str(repo_obj.create_commit("HEAD", signature, signature, "Bin", tree, []))

    sidebar, _calls = load_sidebar(repo_obj, workdir)

    assert sidebar._stats_labels[sha].get_visible() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/usr/bin/python3 -m pytest tests/test_sidebar.py -v`
Expected: new tests FAIL with `AttributeError: 'HistorySidebar' object has no attribute '_pin_buttons'` (or `_stats_labels`, `clear_pin`).

- [ ] **Step 3: Add pin styling, imports, and state**

In `mdprev/sidebar.py`:

Add to the imports:

```python
from .diffmodel import FileStats, format_stats, pins_available  # noqa: E402
```

Append to `_CSS` (inside the bytes literal, before the closing `"""`):

```css
.mdprev-pin {
  min-height: 0;
  min-width: 0;
  padding: 2px;
  opacity: 0.45;
}
.mdprev-pin-active {
  opacity: 1;
  color: #3584e4;
  color: @accent_color;
}
```

In `__init__`, after `self._rows: dict[str, Gtk.ListBoxRow] = {}` add:

```python
        # The pin is what the reader chose to compare from; the shown base is
        # what the window was last told, which lags while a new pin awaits a
        # selection (pinning alone never changes the view).
        self._pinned: Revision | None = None
        self._shown_base: Revision | None = None
        self._modified = False
        self._pin_buttons: dict[str, Gtk.Button] = {}
        self._stats_labels: dict[str, Gtk.Label] = {}
        # Commits are immutable, so their stats never need recomputing.
        self._stats_cache: dict[tuple[str, str], FileStats | None] = {}
```

- [ ] **Step 4: Add pins and stats to the rows**

In `_rebuild`, reset the new dictionaries next to `self._rows = {}`:

```python
        self._rows = {}
        self._pin_buttons = {}
        self._stats_labels = {}
```

Replace the `extras` computation so a pinned off-page commit is kept too:

```python
        loaded = {commit.sha for commit in self._commits}
        extras: list[Commit] = []
        for revision in (self._selected, self._pinned):
            if (
                isinstance(revision, Commit)
                and revision.sha not in loaded
                and revision not in extras
            ):
                extras.append(revision)
```

Replace the tail of `_rebuild` (from `self._suppress = False`) with:

```python
        self._suppress = False
        if self._repo is not None and self._path is not None:
            self.refresh_status()
        else:
            self._update_pins()
```

In `_working_row`, replace the `title` creation and the `box.append(title)` line so the title shares a line with the pin, and add the stats label:

```python
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Working copy", xalign=0.0)
        title.add_css_class("heading")
        title.set_hexpand(True)
        top.append(title)
        top.append(self._pin_button(WORKING_COPY))
```

```python
        box.append(top)
        box.append(status_box)
        box.append(self._stats_label("working", None))
```

(The working-copy stats are filled in by `refresh_status`, which `_rebuild` calls.)

In `_commit_row`, append the pin after `top.append(when)` and the stats label after `box.append(summary)`:

```python
        top.append(self._pin_button(commit))
```

```python
        box.append(self._stats_label(commit.sha, self._commit_stats(commit)))
```

Add these methods in the `# -- rows` section:

```python
    def _pin_button(self, revision: Revision) -> Gtk.Button:
        button = Gtk.Button(icon_name="view-pin-symbolic")
        button.add_css_class("flat")
        button.add_css_class("mdprev-pin")
        button.set_valign(Gtk.Align.CENTER)
        # Hidden until _update_pins decides there is something to compare.
        button.set_visible(False)
        button.connect("clicked", lambda _button: self._pin_clicked(revision))
        self._pin_buttons[_key(revision)] = button
        return button

    def _stats_label(self, key: str, stats: FileStats | None) -> Gtk.Label:
        label = Gtk.Label(xalign=0.0)
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        self._set_stats(label, stats)
        self._stats_labels[key] = label
        return label

    @staticmethod
    def _set_stats(label: Gtk.Label, stats: FileStats | None) -> None:
        # Binary or undecodable content has no meaningful counts; omit the line.
        label.set_visible(stats is not None)
        label.set_text(format_stats(stats) if stats is not None else "")

    def _commit_stats(self, commit: Commit) -> FileStats | None:
        key = (commit.sha, commit.path)
        if key not in self._stats_cache:
            self._stats_cache[key] = git_history.revision_stats(
                self._repo, self._path, commit
            )
        return self._stats_cache[key]
```

- [ ] **Step 5: Add the pin logic**

Replace `refresh_status` with:

```python
    def refresh_status(self) -> None:
        """Update the working-copy row's dot, label, stats, and pin."""

        if self._repo is None or self._path is None:
            return
        self._modified = git_history.is_modified(self._repo, self._path)
        self._apply_status(self._modified)
        working_stats = self._stats_labels.get("working")
        if working_stats is not None:
            self._set_stats(
                working_stats,
                git_history.revision_stats(self._repo, self._path, WORKING_COPY),
            )
        self._update_pins()
```

Replace `_emit` with, and add after it:

```python
    def _emit(self) -> None:
        pinned = self._pinned
        base = pinned if pinned is not None and pinned != self._selected else None
        self._shown_base = base
        self._on_select(self._selected, base, self._mode)

    def _pin_clicked(self, revision: Revision) -> None:
        self._pinned = None if self._pinned == revision else revision
        self._update_pins()
        self._base_changed()

    def _update_pins(self) -> None:
        """Show pins only where a comparison is possible; drop an invalid pin."""

        available = pins_available(
            len(self._commits), self._cursor is not None, self._modified
        )
        pinned = self._pinned
        if pinned is not None and (
            not available or (isinstance(pinned, WorkingCopy) and not self._modified)
        ):
            self._pinned = pinned = None
        pinned_key = _key(pinned) if pinned is not None else None
        for key, button in self._pin_buttons.items():
            button.set_visible(available and (key != "working" or self._modified))
            active = key == pinned_key
            if active:
                button.add_css_class("mdprev-pin-active")
            else:
                button.remove_css_class("mdprev-pin-active")
            text = (
                "Stop comparing from this version" if active
                else "Compare from this version"
            )
            button.set_tooltip_text(text)
            button.update_property([Gtk.AccessibleProperty.LABEL], [text])
        self._base_changed()

    def _base_changed(self) -> None:
        # Pinning alone never changes the view, but a comparison on screen
        # whose base was unpinned must not keep showing that base.
        if self._pinned is None and self._shown_base is not None and not self._suppress:
            self._emit()

    def clear_pin(self) -> bool:
        """Unpin the base, as Escape does; report whether there was one."""

        if self._pinned is None:
            return False
        self._pinned = None
        self._update_pins()
        return True
```

- [ ] **Step 6: Run sidebar tests**

Run: `/usr/bin/python3 -m pytest tests/test_sidebar.py -v`
Expected: all PASS.

- [ ] **Step 7: Wire Escape and live reload in `mdprev/app.py`**

Replace `_show_working_copy` with:

```python
    def _show_working_copy(self) -> None:
        """Escape: close the options popover, else unpin, else leave history."""

        # The popover's grab normally keeps Escape from reaching this window
        # shortcut; this guards the case where focus ended up outside it.
        if self._popover.get_visible():
            self._popover.popdown()
            return
        if self._sidebar.clear_pin():
            return
        if self._target == WORKING_COPY:
            return
        self._sidebar.select_working_copy()
```

In `_reload_timeout`, replace:

```python
        if self._sidebar_visible:
            self._sidebar.refresh_status()
        if self._target != WORKING_COPY:
            # A historic revision is on screen.  Saving the file must not swap
            # it out; only the working-copy row's status may change.
            return GLib.SOURCE_REMOVE
```

with:

```python
        if self._repo is not None:
            # Also clears a working-copy pin the save made meaningless, even
            # while the sidebar is hidden.
            self._sidebar.refresh_status()
        if WORKING_COPY not in (self._target, self._base):
            # Only historic revisions are on screen.  Saving the file must not
            # swap them out; only the working-copy row's status may change.
            return GLib.SOURCE_REMOVE
```

- [ ] **Step 8: Run the full suite and lint**

Run: `/usr/bin/python3 -m pytest -v && ruff check mdprev tests`
Expected: all PASS; "All checks passed!"

- [ ] **Step 9: Smoke-launch the app**

Run: `pgrep -af "python3 -m mdprev"` — expected: no output (otherwise ask the user to close MdPrev; do not kill it).
Run: `timeout 5 /usr/bin/python3 -m mdprev README.md; echo "exit=$?"`
Expected: no traceback; `exit=124`.

- [ ] **Step 10: Commit**

```bash
git add mdprev/sidebar.py mdprev/app.py tests/test_sidebar.py
git commit -m "Pin a base version to compare, with per-version stats

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

---

### Task 7: Requirements, README, and handoff verification

**Files:**
- Modify: `FEATURE_REQUIREMENTS.md`, `README.md`, `AGENTS.md`

**Interfaces:**
- Consumes: the behavior delivered by Tasks 1-6.
- Produces: documentation only.

- [ ] **Step 1: Add MVP 5 to `FEATURE_REQUIREMENTS.md`**

Insert before `## 7. Deferred features`, and renumber `## 7. Deferred features` → `## 8.` and `## 8. Non-goals and quality priorities` → `## 9.` (and any later top-level sections by one):

```markdown
## 7. MVP 5: revision comparison

### 7.1 Required behavior

- Every version row in the history sidebar carries a pin button. Pinning a
  row makes it the base of a comparison; clicking the pin again unpins it. At
  most one row is pinned. Pinning alone never changes the displayed document.
- Pins are shown only when at least two versions exist: the loaded commits,
  plus the working copy when it has uncommitted changes (an unloaded page of
  history counts as at least one more commit). The working-copy row carries a
  pin only while it is modified.
- With a pin set, selecting another row shows base → target; selecting the
  pinned row shows it as if nothing were pinned. Without a pin, a commit is
  compared with its first parent and the working copy with HEAD.
- The view switch offers Rendered, Diff (unified), and Side by side.
- Side by side shows base and target in two columns of one table that scroll
  together without JavaScript, wraps long lines, pairs removed and added
  lines, highlights changed words in similar lines, and folds unchanged
  stretches.
- Every version row shows its size, line count, and word count, omitted for
  binary or non-UTF-8 content. Both diff views open with a header naming both
  versions and the size, line, and word changes between them.
- Escape closes an open display-options popover; otherwise it clears the pin;
  otherwise it returns to the working copy.
- Unpinning the base of the comparison on screen re-renders it against the
  implicit base. A working-copy pin is cleared when a save makes the file
  match HEAD.
- Live reload stays active whenever the working copy is either side of the
  comparison on screen.
- Historic content remains untrusted: all diff text is escaped and never
  parsed as Markdown.

### 7.2 MVP 5 acceptance criteria

1. Pins appear exactly per 7.1 and update when a save changes the working
   copy's modified state.
2. With a pin set, both diff modes show base → target; selecting the pinned
   row shows its unpinned behavior.
3. Pinning alone never changes the displayed document.
4. Side by side scrolls as one, wraps long lines, and pairs, folds, and
   word-highlights changes.
5. Unified and side-by-side views of the same comparison report the same
   added and removed line counts.
6. Every version row shows size, lines, and words, or omits them for binary /
   non-UTF-8 content.
7. Both diff views open with the stats header.
8. Live reload updates the view when the working copy is on either side.
9. Escape closes an open display-options popover without touching the pin;
   otherwise it clears the pin before returning to the working copy.
10. All new views are legible in Light, Dark, Sepia, and System themes.
11. The source file and the repository are never written.
12. MVP 1-4 acceptance criteria continue to pass, including behavior without
    python3-pygit2.
```

In the Deferred features section, change `The following are outside MVP 1, MVP 2, MVP 3, and MVP 4:` to `The following are outside MVP 1 through MVP 5:`, and change the bullet `- Branch, tag, or ref browsing; blame; side-by-side or rendered-prose diffs` to `- Branch, tag, or ref browsing; blame; rendered-prose diffs`.

Run: `grep -n "§7\|§8\|section 7\|section 8" FEATURE_REQUIREMENTS.md README.md AGENTS.md`
Expected: no output (nothing refers to the renumbered sections by number). Fix any hit.

- [ ] **Step 2: Update `README.md`**

In the git history paragraph, replace the sentence `Selecting a commit shows that version of the document; the Rendered/Diff switch alternates between the formatted document and the unified diff of its Markdown source.` with:

```markdown
Selecting a commit shows that version of the document; the Rendered / Diff /
Side by side switch alternates between the formatted document, the unified
diff of its Markdown source, and the same diff in two columns. Each entry shows
the file's size, line count, and word count at that version.

To compare any two versions, click the pin on one entry to make it the base,
then select another; both diff views then show base → selected, headed by the
size, line, and word changes between them. Pins appear once there are two
versions to compare — two commits, or a commit plus uncommitted changes.
```

Replace the sentence beginning `` `Escape` returns to the working copy at any time a commit is selected`` through `...even though there is no menu item or button for it.` with:

```markdown
`Escape` first clears a pin, then returns to the working copy at any time a
commit is selected, whether or not the sidebar is open — this is the only way
back once the sidebar is closed, so it is worth knowing even though there is no
menu item or button for it. Live reload stays on while the working copy is
either side of a comparison.
```

- [ ] **Step 3: Update `AGENTS.md`**

After the line `- \`python3-pygit2\` only in MVP 4, and only for the git history sidebar` add:

```markdown
- MVP 5 (revision comparison) adds no dependencies; word-level diffing uses
  the standard library's `difflib`
```

- [ ] **Step 4: Full verification**

Run: `/usr/bin/python3 -m pytest -v && ruff check mdprev tests`
Expected: all PASS; "All checks passed!"

- [ ] **Step 5: Commit**

```bash
git add FEATURE_REQUIREMENTS.md README.md AGENTS.md
git commit -m "Document revision comparison as MVP 5

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RngnRC1W5ZwsiNo21TrVik"
```

- [ ] **Step 6: Hand off manual GNOME verification**

The agent cannot click in the GUI. Report to the user that these checks from spec §9.2 remain for them, run from the repo with MdPrev closed first (`cd ~/git/mdprev && /usr/bin/python3 -m mdprev <file>`):

1. A file with one commit and no changes shows no pins; editing and saving it makes pins appear on both rows.
2. Pin an old commit, select a newer one: both diff modes show old → new with a correct stats line; the subtitle shows `old → new`.
3. Pin the modified working copy, select a commit: the diff reads working copy → commit. Undo the edits and save: the pin clears.
4. Pin a commit, select the working copy, edit and save: the diff and stats update live.
5. Escape clears the pin, then returns to the working copy. With the display-options popover open, Escape only closes it and the pin survives.
6. Side by side is legible in Light, Dark, Sepia, and System, at 50% and 200% zoom, with a long unbroken line.
7. A file renamed in history: comparing across the rename shows the "Renamed" line.
8. The three-button mode switch fits at the minimum sidebar width (180 px).
9. With python3-pygit2 absent, MdPrev behaves as MVP 3.
```
