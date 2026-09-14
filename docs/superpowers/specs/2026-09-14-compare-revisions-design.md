# MdPrev Revision Comparison — Design

Status: approved design, pending implementation plan
Date: 2026-09-14
Target: Ubuntu 26.04 LTS (Resolute), GNOME 50, Wayland
Scope: MVP 5 of `FEATURE_REQUIREMENTS.md` (builds on the MVP 4 git history
sidebar, `2026-09-09-git-history-design.md`)

## 1. Goal

Let the reader compare **any two versions** of the open document — two
commits, or a commit and the uncommitted working copy — and read the result
either as the existing unified diff or as a new **side-by-side** diff.

Alongside this, every version in the history sidebar shows a small stats line
(file size, line count, word count), and every diff view opens with a stats
line summarizing how size, lines, and words changed between the two versions.

All MVP 4 constraints hold: the git integration is read-only, historic content
is untrusted, JavaScript stays disabled, and nothing is written to the file or
the repository.

## 2. Non-goals

- No rendered-prose diff. Both diff views compare Markdown source.
- No three-way or multi-revision comparison. Exactly one base, one target.
- No word-level highlighting in the unified view; it stays as MVP 4 renders it.
- No persistence of the pinned base. Like the selected revision (MVP 4 §2), a
  pin is session state and every window opens unpinned.
- No stats in the Rendered view beyond the sidebar rows.
- No new preferences keys.

## 3. Terminology

- **Version** — a distinct state of the file that can be compared: each
  commit in the sidebar, plus the working copy **only when it is modified**.
  An unmodified working copy has the same content as the newest commit and is
  not a separate version.
- **Target** — the selected row. Shown on the right in side-by-side, as the
  `+` side in unified.
- **Base** — the pinned row. Shown on the left in side-by-side, as the `-`
  side in unified. When nothing is pinned, the base is implicit: a commit's
  first parent, or HEAD for the working copy — exactly MVP 4's behavior.

The diff always reads **base → target**, whichever of the two is older.

## 4. Interaction

### 4.1 Pinning

Every row that represents a version carries a flat `view-pin-symbolic` button
at the end of its first line.

- The button is dimmed (`.dim-label`) when not pinned and full-strength with
  the `.accent` style class when pinned.
- Clicking it pins that row as the base. Clicking the pinned row's button
  unpins it. Pinning another row moves the pin; there is at most one.
- The button consumes its click, so pinning never changes the selection, and
  **pinning alone never changes the view**. The view changes only when the
  reader selects a row.
- Tooltip and accessible label: "Compare from this version" when unpinned,
  "Stop comparing from this version" when pinned.

### 4.2 When pins are available

Pins are shown only when there are at least two versions to compare:

```
versions = loaded_commits + (1 if working copy is modified else 0)
pins_available = versions >= 2 or (loaded_commits >= 1 and more pages exist)
```

| Situation | Pins |
|---|---|
| 1 commit, working copy unchanged | none |
| 1 commit + uncommitted changes | on both rows |
| 3 commits, working copy unchanged | on the commit rows; not on the working-copy row |
| 3 commits + uncommitted changes | on every row |
| Untracked file, unborn HEAD, no history | none |

The working-copy row never carries a pin while it is unmodified, even when
pins are otherwise available.

The rule is `pins_available()` in `mdprev/diffmodel.py` (§6.1), which has no
GTK or pygit2 import, so it is tested without a display.

### 4.3 Selecting while pinned

| Pinned | Selected | Diff shows |
|---|---|---|
| nothing | commit C | C's first parent → C (MVP 4) |
| nothing | working copy | HEAD → working copy (MVP 4) |
| commit B | commit C | B → C |
| commit B | working copy | B → working copy (file on disk) |
| working copy | commit C | working copy → C |
| X | X itself | as if nothing were pinned |

Selecting the pinned row itself is not an error; it falls back to the
unpinned behavior for that row so the reader can still read it normally.

The working copy may be a **target** even when unmodified (it is then
identical to the newest commit, and B → working copy equals B → newest). It
may only be a **base** when modified, per §4.2.

### 4.4 Clearing the pin

- `Escape` clears the pin first if one is set. A second `Escape` returns to the
  working copy, as in MVP 4. The `win.working-copy` action gains this
  two-step behavior.
- If the working copy is pinned and a save makes it unmodified, the pin is
  cleared and the view re-renders against the implicit base.
- If a re-query (sidebar reopened) makes pins unavailable, the pin is cleared.
- A pinned commit that falls off the loaded page after a re-query is kept and
  shown as an extra row, the same way MVP 4 keeps an off-page selected commit.
- Closing the sidebar keeps both base and target, as MVP 4 keeps the selection.

### 4.5 View modes

The linked toggle at the foot of the sidebar gains a third button:

```
[ Rendered | Diff | Side by side ]
```

- **Rendered** shows the target, ignoring the pin.
- **Diff** shows the unified diff base → target.
- **Side by side** shows the two-column diff base → target.

The mode remains session state and applies with or without a pin.

### 4.6 Header bar

When an explicit comparison is on screen (a pin is set, the selected row is
not the pinned row, and a diff mode is active), the
subtitle reads `a1b2c3d → 9f8e7d6`, with `Working copy` in place of a sha
where applicable, and the window title becomes
`document.md — a1b2c3d → 9f8e7d6`. Otherwise MVP 4's titles are unchanged.

## 5. Stats

### 5.1 Definitions

Computed from the Markdown **source**, never the rendered output:

- **Size** — length of the UTF-8 bytes (for a commit, the blob size).
- **Lines** — `len(text.splitlines())`.
- **Words** — `len(text.split())`, i.e. whitespace-separated tokens, matching
  `wc -w` for ordinary text.

Size is formatted with binary units and one decimal above 1 KB:
`812 B`, `4.2 KB`, `1.3 MB`.

### 5.2 Sidebar rows

Each version row gains a third, dimmed, single-line label:

```
4.2 KB · 118 lines · 812 words
```

- Commit rows: from the blob at that commit, computed when the row is built
  and cached by blob id for the window's lifetime (blobs are immutable). One
  page is `history_limit` rows, 10 by default.
- Working-copy row: from the file on disk, refreshed with the status dot on
  save.
- If the content is binary or not valid UTF-8, or reading fails, the stats
  label is omitted for that row. The row itself still works.

### 5.3 Diff stats line

Both diff views open with a two-line header inside the WebKit document:

```
a1b2c3d  Add install notes   →   9f8e7d6  Fix typo
Size −312 B (4.2 KB → 3.9 KB) · Lines +3 −11 (net −8) · Words −52 (812 → 760)
```

- The first line names both sides: short sha and summary, or `Working copy`,
  or `(none)` when the base does not exist (the target is a root commit).
- When the two sides carry different paths (a rename lies between them), a
  third line reads `Renamed: old.md → new.md`.
- **Lines +a −d** come from the patch's `line_stats` (additions, deletions);
  **net** is `target.lines − base.lines`.
- Size and word deltas are target minus base, with an explicit sign; a zero
  delta is shown as `±0`.
- A missing base counts as zero size, zero lines, zero words.
- If either side's stats are unavailable (binary / not UTF-8), the stats line
  is replaced by "Stats unavailable: <reason>" and the diff still renders
  where possible.

## 6. Architecture

### 6.1 `mdprev/diffmodel.py` — new, pure Python

No GTK, no pygit2. It holds everything that `render.py`, `sidebar.py`, and
`git_history.py` share, so `render.py` stays importable without pygit2 and the
rules are testable without a display.

```python
@dataclass(frozen=True)
class FileStats:
    size: int
    lines: int
    words: int

def stats_for(data: bytes) -> FileStats        # raises UnicodeDecodeError
def format_size(size: int) -> str               # "812 B", "4.2 KB"
def format_delta(value: int) -> str             # "+3", "−11", "±0"
def pins_available(loaded_commits: int, has_more: bool, modified: bool) -> bool
```

`DiffLine`, `Hunk`, `Side`, and `Comparison` (§6.2) are also defined here.

### 6.2 `mdprev/git_history.py` — additions

The dataclasses below are shown here for context but defined in
`diffmodel.py` (§6.1), except `WorkingCopy`, which sits beside `Commit`.

A working-copy marker replaces the MVP 4 convention of `None` meaning "working
copy", because `None` is now also needed to mean "nothing pinned":

```python
@dataclass(frozen=True)
class WorkingCopy:
    pass

WORKING_COPY = WorkingCopy()
Revision = Commit | WorkingCopy

@dataclass(frozen=True)
class DiffLine:
    origin: str          # " ", "+", "-"
    old_lineno: int      # -1 when absent
    new_lineno: int      # -1 when absent
    text: str            # without trailing newline

@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine]

@dataclass(frozen=True)
class Side:
    label: str                   # "a1b2c3d  Add install notes", "Working copy", "(none)"
    path: str | None
    stats: FileStats | None
    stats_error: str | None

@dataclass(frozen=True)
class Comparison:
    base: Side
    target: Side
    patch_text: str              # unified diff, as MVP 4 renders it
    hunks: list[Hunk]            # plain data for the side-by-side renderer
    additions: int
    deletions: int
    binary: bool

def revision_stats(repo, path: Path, revision: Revision) -> FileStats | None
def compare(repo, path: Path, base: Revision | None, target: Revision) -> Comparison
```

- `compare()` resolves an implicit base when `base is None` (first parent for
  a commit, HEAD for the working copy), loads both sides as blobs or disk
  bytes, and builds **one** `pygit2.Patch` with `Patch.create_from(old, new,
  old_as_path=..., new_as_path=...)`. Both the unified text and the hunks come
  from that single patch, so the two views and the `+a −d` counts can never
  disagree.
- The MVP 4 rename special case (a content-preserving rename yields an empty
  blob patch, so the rename-detecting diff's patch is used) is preserved for
  the implicit-parent case. For an explicit base whose path differs from the
  target's, the header's "Renamed" line carries that information instead.
- `patch_for()` and `working_patch()` become thin wrappers over `compare()` so
  existing callers and tests keep working, or are removed if the plan shows no
  remaining caller.
- `revision_stats()` reads via the same guarded blob access as `file_at()`,
  including its lazy-blob guard, and returns `None` for binary or undecodable
  content.
- All libgit2, `KeyError`, and `OSError` failures convert to
  `GitHistoryError`, following MVP 4 §5.5.

### 6.3 `mdprev/sidebar.py` — changes

- Rows gain the pin button (§4.1) and stats label (§5.2).
- The widget tracks `_selected: Revision` and `_pinned: Revision | None`.
- The callback becomes
  `on_select(target: Revision, base: Revision | None, mode: str)`.
  `base` is `None` when nothing is pinned or when the pinned row is the
  selected row (§4.3).
- Pin visibility calls `diffmodel.pins_available()`.
- `clear_pin() -> bool` returns whether a pin was cleared; the window's
  Escape handler uses it to decide between the two steps of §4.4.
- The mode switch gains the third `Gtk.ToggleButton` in the same group; modes
  are `"rendered"`, `"diff"`, `"side-by-side"`.
- `refresh_status()` also refreshes the working-copy stats, recomputes pin
  availability, and clears a working-copy pin that is no longer modified,
  firing the callback if the view must change.

### 6.4 `mdprev/render.py` — additions

```python
def render_comparison(
    comparison: Comparison, mode: str, font: str = "system", theme: str = "system"
) -> str
```

- Emits the stats header (§5.3) followed by either the existing unified
  rendering (MVP 4 `render_diff`, reused) or the side-by-side table (§7).
- `render.py` imports only `diffmodel.py`, never pygit2 or `git_history.py`.
- Every piece of text — lines, summaries, paths, labels — is escaped.
  `cmark-gfm` is never invoked on diff text.

### 6.5 `mdprev/app.py` — changes

- `_history_selected(target, base, mode)` stores both, and scroll resets when
  either the target or the base changes.
- `load_document()` calls `compare()` and `render_comparison()` for both diff
  modes, and `file_at()` / `read_source()` for Rendered as today.
- **Live reload** is active when either side of the comparison on screen is
  the working copy, so saving updates the diff and its stats. When neither
  side is the working copy, MVP 4's suppression applies.
- `win.working-copy` (Escape) calls `sidebar.clear_pin()` first and falls back
  to returning to the working copy.
- Titles per §4.6.

## 7. Side-by-side rendering

A single `<table class="sbs">` so both columns scroll together without
JavaScript:

```
| old no | old text | new no | new text |
```

- `table-layout: fixed`; the two text columns share the width equally; line
  number columns are narrow, right-aligned, dimmed, and not selectable
  (`user-select: none`), so copying a column yields clean source.
- Text cells use `white-space: pre-wrap` and `overflow-wrap: anywhere`, so
  long lines wrap rather than forcing horizontal scrolling. Zoom applies.
- **Row pairing, per hunk:** context lines occupy both sides. A run of `-`
  lines followed immediately by a run of `+` lines is paired row by row; the
  longer run's surplus rows have an empty cell on the other side. Unpaired
  `-` rows leave the right cell empty and vice versa.
- **Word highlights:** each paired `-`/`+` row is compared with
  `difflib.SequenceMatcher` over whitespace-preserving tokens; differing
  spans are wrapped in `<del>` (left) and `<ins>` (right) with a stronger
  tint. When the ratio is below 0.5 the pair is treated as a full
  replacement and no intra-line spans are emitted, to avoid confetti.
- **Folding:** hunks come from the patch with 3 context lines. Between hunks,
  and before the first / after the last, a full-width row reads
  "⋯ N unchanged lines". Nothing expands; it is a read-only marker.
- **Colors:** new CSS custom properties `--diff-del-bg`, `--diff-add-bg`,
  `--diff-del-word`, `--diff-add-word`, `--diff-fold` defined for Light,
  Dark, Sepia, and System in `_document()`, alongside the existing palette.
- Empty patch: "No changes between these versions." (with a pin) or MVP 4's
  "No changes in this commit." (without).
- Binary content, or a side that is not valid UTF-8: the stats header is still
  shown (with "Stats unavailable" where it applies) and the body reads
  "Side-by-side view needs UTF-8 text on both sides." The unified view shows
  the patch as libgit2 produces it.

## 8. Error and empty states

| Condition | Result |
|---|---|
| Fewer than two versions | No pins (§4.2) |
| Pinned working copy becomes unmodified | Pin cleared, view re-rendered |
| Base is a root commit's parent | Base side `(none)`, zero stats |
| Blob binary / not UTF-8 | Row stats omitted; diff per §7 |
| libgit2 error in `compare()` | `error_document()` with concise message |
| Revision vanished (e.g. rebase, gc) | `error_document()` "Unknown revision …" |

None crashes the application.

## 9. Verification

### 9.1 Automated

- `tests/test_diffmodel.py` (new): the `pins_available` table of §4.2; line/word/size counts including empty text,
  no trailing newline, CRLF, non-ASCII words, invalid UTF-8; `format_size`
  boundaries (1023 B, 1024 B, 1.0 MB); `format_delta` signs and `±0`.
- `tests/test_git_history.py`: `compare()` for commit → commit, newer →
  older (reversed), commit → working copy, working copy → commit, root commit
  with no parent, across a rename (header paths differ), unchanged content
  (empty patch), binary blob; `additions`/`deletions` match the unified text;
  `revision_stats()` for commit, working copy, binary, and invalid UTF-8;
  existing `patch_for`/`working_patch` tests still pass.
- `tests/test_render.py`: side-by-side pairing (equal runs, longer `-` run,
  longer `+` run, pure additions, pure deletions), fold rows with correct
  counts, word spans present for similar lines and absent below the ratio,
  escaping of `<script>` and `&` in lines, summaries, and paths; stats header
  formatting including `(none)` and "Stats unavailable".
- The pygit2-dependent tests stay behind `pytest.importorskip("pygit2")`.

### 9.2 Manual GNOME verification

1. A file with one commit and no changes shows no pins; editing and saving it
   makes pins appear on both rows.
2. Pin an old commit, select a newer one: both diff modes show old → new with
   a correct stats line; the subtitle shows `old → new`.
3. Pin the modified working copy, select a commit: diff reads working copy →
   commit. Undo the edits and save: the pin clears.
4. Pin a commit, select the working copy, edit and save: the diff and stats
   update live.
5. Escape clears the pin, then returns to the working copy.
6. Side by side is legible in Light, Dark, Sepia, and System, at 50% and 200%
   zoom, with a long unbroken line.
7. A file renamed in history: comparing across the rename shows the
   "Renamed" line.
8. With python3-pygit2 absent, MdPrev behaves as MVP 3.

## 10. Documentation changes

- `FEATURE_REQUIREMENTS.md`: add **MVP 5: revision comparison** with the
  behavior of §4–§5 and the acceptance criteria of §11; remove "side-by-side
  … diffs" from §7 Deferred features (rendered-prose diffs stay deferred).
- `README.md`: describe pinning, the three view modes, the stats line, and
  the two-step Escape.
- `AGENTS.md`: note that MVP 5 adds no dependencies.

## 11. Acceptance criteria

1. Pins appear exactly when §4.2 says, and update when a save changes the
   working copy's modified state.
2. With a pin set, selecting another row shows base → target in both diff
   modes; selecting the pinned row shows its unpinned behavior.
3. Pinning alone never changes the displayed document.
4. Side by side scrolls as one, wraps long lines, and pairs, folds, and
   word-highlights per §7.
5. Unified and side-by-side views of the same comparison report the same
   `+a −d` counts.
6. Every version row shows size, lines, and words, or omits the label for
   binary / non-UTF-8 content.
7. Both diff views open with the stats line of §5.3.
8. Live reload updates the view when the working copy is on either side.
9. Escape clears the pin before returning to the working copy.
10. All new views are legible in Light, Dark, Sepia, and System themes.
11. The source file and the repository are never written; all diff text is
    escaped and never parsed as Markdown.
12. MVP 1–4 acceptance criteria continue to pass, including behavior without
    python3-pygit2.
