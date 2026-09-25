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
