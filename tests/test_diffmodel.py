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
    assert stats_for(b"a b\r\nc\r\n") == FileStats(size=9, lines=2, words=3)


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
