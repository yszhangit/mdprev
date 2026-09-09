# MdPrev Git History Sidebar — Design

Status: approved design, pending implementation plan
Date: 2026-09-09
Target: Ubuntu 26.04 LTS (Resolute), GNOME 50, Wayland
Scope: MVP 4 of `FEATURE_REQUIREMENTS.md`

## 1. Goal

When an open Markdown document lives inside a local git repository, MdPrev
offers a sidebar listing the commits that touched that file. Selecting a
revision shows either the document as it was rendered at that commit, or the
unified diff of its Markdown source against the previous version.

The feature preserves every existing product constraint. MdPrev remains a
read-only viewer: it never writes the source file, never writes the
repository, and never executes JavaScript or raw HTML from any source,
historic content included.

## 2. Non-goals

- No checkout, restore, stash, commit, or any other repository mutation.
- No remote information: no fetch, no upstream tracking, no ahead/behind.
- No branch, tag, or ref browsing. History is the first-parent history of one
  file.
- No blame, no per-line attribution.
- No rendered-prose diffing. Diffs are of Markdown source.
- No side-by-side diff.
- No historic image resolution (see §8.2).
- No `.git` directory watching (see §7.4).
- **No per-file preferences.** All settings remain global, as they are today.

  The state worth remembering per document would be the selected revision, and
  restoring it is unsafe here: a window would open showing content from an old
  commit while the reader believes it shows the file, with live reload
  suppressed (§7.4) and only the header-bar SHA to contradict them. A stored
  sha is unstable besides — rebase, amend, gc, or a fresh clone invalidate it,
  and the only sensible fallback is the working copy, which is the default
  anyway. Every document therefore opens at the working copy.

  The remaining candidates do not justify a per-file store. Sidebar visibility
  is a mode the reader is in rather than a property of a document; width is
  layout; the Rendered/Diff mode is flipped constantly while comparing commits.
  A path-keyed store would also grow without bound, requiring an eviction
  policy, and would amount to the recent-file management that
  `FEATURE_REQUIREMENTS.md` defers. `save_preferences()` is additionally a
  read-modify-write over the whole file, so per-file entries would make
  concurrent window closes race where today they write identical values.

  Revisit only if tabs or session restoration are adopted: those bring a
  document registry with a lifecycle and an eviction story, which makes
  per-file state nearly free, and the revision question can then be reopened
  with an explicit "viewing history" banner rather than a subtitle.

## 3. Runtime dependency

The feature requires `python3-pygit2`, available in Ubuntu resolute/universe as
`1.19.1-1build1`. It is a system package, consistent with the project's rule
against vendored dependencies.

The dependency is **soft**. `mdprev/git_history.py` guards its `pygit2` import
and exposes `AVAILABLE: bool`. When pygit2 is absent the sidebar and its
header-bar button do not exist and MdPrev behaves exactly as it does today. An
existing installation that upgrades without installing pygit2 must not break.

Implementation targets the pygit2 1.19 API, which uses `pygit2.enums` rather
than the older `GIT_*` module constants. Exact call signatures are verified
against the installed package during implementation rather than assumed.

### 3.1 Why libgit2 rather than the git CLI

libgit2 does not execute repository-configured external diff drivers, textconv
filters, pagers, aliases, or hooks while reading. A hostile repository
therefore has no code-execution lever, which the `git` CLI would have required
explicit hardening (`--no-ext-diff`, `--no-textconv`, `--no-pager`) to reach.

The cost is that libgit2 provides no `--follow` and no process-level timeout.
Both are addressed in §5.2 and §5.3.

## 4. Architecture

Two modules appear and three change. The existing separation between
display-free logic and GTK code is preserved.

| Module | Role | Imports GTK |
|---|---|---|
| `mdprev/git_history.py` | **New.** Repository queries. Returns plain Python types. | No |
| `mdprev/render.py` | Gains `render_diff()`. Otherwise unchanged. | No |
| `mdprev/sidebar.py` | **New.** `HistorySidebar` widget: list, toggle, empty states. | Yes |
| `mdprev/app.py` | Window layout, revision state, reload interplay. | Yes |
| `mdprev/preferences.py` | Three new validated keys. | No |

`git_history.py` and `render.py` are unit-testable without a display server,
matching the existing arrangement.

## 5. `mdprev/git_history.py`

### 5.1 Interface

```python
AVAILABLE: bool          # False when pygit2 cannot be imported

class GitHistoryError(RuntimeError):
    """An expected error while reading repository history."""

@dataclass(frozen=True)
class Commit:
    sha: str          # full 40-hex
    short_sha: str    # 7 chars, for display
    summary: str      # first line of the commit message
    author: str       # author name
    when: datetime    # authored time, timezone-aware
    path: str         # the file's repo-relative path AS OF this commit

@dataclass(frozen=True)
class Cursor:
    sha: str    # resume below this revision
    path: str   # the tracked path as of that revision

@dataclass(frozen=True)
class History:
    commits: list[Commit]
    truncated: bool             # the walk hit MAX_SCAN before filling `limit`
    next_cursor: Cursor | None  # where to resume, for "Show more"

def find_repository(path: Path) -> Repository | None
def is_tracked(repo, path: Path) -> bool
def history(repo, path: Path, limit: int = 10, after: Cursor | None = None) -> History
def file_at(repo, sha: str, path: str) -> str
def patch_for(repo, sha: str, path: str) -> str
def working_patch(repo, path: Path) -> str
def is_modified(repo, path: Path) -> bool
```

A resumed walk continues below a rename, where older revisions carry the file
under a different name, so the cursor records the tracked path alongside the
sha. A bare sha would lose that and silently truncate history at the rename.

`is_tracked()` exists so that §7.5 can distinguish "Not tracked in this
repository" from "No history for this file"; nothing else in this interface
separates those two states.

Two path types appear deliberately. `find_repository()`, `history()`,
`working_patch()`, and `is_modified()` take the document's on-disk `Path` and
resolve it against the repository's working directory. `file_at()` and
`patch_for()` take a repo-relative path *string*, which callers supply from
`Commit.path` so that a revision older than a rename is read under its
historic name.

No function in this module writes to the repository or to the filesystem.

### 5.2 Bounding the walk

Running in-process forfeits `subprocess.run(timeout=)`. The walk is bounded by
work rather than by clock, which is deterministic and testable:

- collect at most `limit` matching commits (default 10, from preferences);
- stop unconditionally after scanning `MAX_SCAN = 2000` revisions;
- set `truncated=True` when the ceiling stopped the walk, so the sidebar
  reports the truncation rather than silently showing a short list.

`after` is **exclusive**: the walk resumes at the revision following
`Cursor.sha`, tracking `Cursor.path`.
`next_cursor` is set whenever the walk stopped with history potentially
remaining — whether `limit` was filled or `MAX_SCAN` intervened — so "Show
more" resumes correctly in both cases. It is `None` only when the walk reached
the end of history.

History is queried lazily. Nothing runs until the sidebar is first opened.

### 5.3 Finding commits that touch the file

libgit2 has no `--follow`, so path-following is implemented directly, and
cheaply. For each revision:

1. Look up the tracked path's blob OID in `commit.tree` and in the first
   parent's tree. **Differing OIDs mean the commit touched the file.** This is
   two tree lookups per revision; no diff is computed.
2. Only when the path is present in the commit but absent from the parent is a
   rename-detecting diff (`find_similar()`) computed, to recover the previous
   name. The tracked path is then updated for older revisions, and the
   resulting `Commit.path` records the name in force at that commit.

Merge commits are compared against their first parent only, matching the
semantics of `git log --follow`. Root commits are compared against an empty
tree.

### 5.4 Working-copy status

`is_modified()` returns true for **any** difference from HEAD, staged or
unstaged. `repo.status_file()` reports index and worktree flags separately;
anything that is not `CURRENT` or `IGNORED` counts as modified, so a file that
has been `git add`ed but not committed reports modified.

Status is local only. No remote, upstream, or ahead/behind information is
consulted or displayed.

### 5.5 Error conversion

`pygit2.GitError`, `KeyError`, and `OSError` raised by libgit2 are converted to
`GitHistoryError` with a concise user-facing message. Broad `except Exception`
is not used, per `AGENTS.md`.

A blob that is binary or not valid UTF-8 raises `GitHistoryError` with the same
message shape as `read_source()` uses for the live file.

## 6. Rendering

### 6.1 Historic rendered view

`file_at()` returns the blob text, which is passed to the existing
`render_markdown(source, self.path.parent, font, theme)`. Historic content is
untrusted input and receives the identical treatment as the live file: the same
`sanitize_fragment` allowlist, the same Pygments highlighting, the same four
themes. No new rendering path is introduced.

### 6.2 Diff view

`patch_for()` and `working_patch()` return unified diff text, which is passed
to a new function in `render.py`:

```python
def render_diff(patch: str, font: str = "system", theme: str = "system") -> str
```

It escapes the patch, highlights it with the `DiffLexer` and
`HtmlFormatter(nowrap=True)` already present in `render.py`, wraps the result
in `<pre><code class="highlight language-diff">`, and reuses `_document()` so
that fonts, themes, and the existing light/dark highlight palettes apply
unchanged.

**`cmark-gfm` is never invoked on diff text.** A patch must not be parsed as
Markdown.

An empty patch — a mode-only change, for instance — renders as "No changes in
this commit", not a blank page.

## 7. User interface

### 7.1 Window layout

`PreviewWindow._setup_ui()` currently ends with `self.set_child(self._webview)`.
That becomes a `Gtk.Paned(orientation=HORIZONTAL)` with the sidebar as start
child and the webview as end child:

- `set_resize_start_child(False)` — the reading column absorbs window resizing.
- `set_shrink_start_child(False)` — the sidebar cannot be crushed to nothing.
- Position restored from `sidebar_width`; changes persisted on window close.

The sidebar lives in `mdprev/sidebar.py` rather than in `app.py`. `app.py` is
already 379 lines, and the list, its rows, the view toggle, and the empty
states would push the window class past readability. `HistorySidebar(Gtk.Box)`
owns the list and the toggle and accepts a plain
`on_select(commit: Commit | None, mode: str)` callback — no custom GObject
signals. The record travels rather than a bare sha because rendering the
revision needs `Commit.path`, the name in force at that commit, and the
header-bar subtitle needs `Commit.when`. The window reacts to the callback and
does not reach into the widget's internals.

### 7.2 The commit list

A `Gtk.ListBox` with the `.navigation-sidebar` style class, which inherits
GNOME sidebar styling. `Gtk.ListView` is not used: at a default limit of 10
rows its model ceremony buys nothing.

Rows carry two lines — short SHA and authored date on the first, ellipsized
summary on the second.

**The working-copy row** is pinned above the commits, selected by default, and
shows a colored status dot followed by a text label:

- **Red dot** (`@error_color`, fallback `#e01b24`) and "Modified" when
  `is_modified()` is true.
- **Green dot** (`@success_color`, fallback `#2ec27e`) and "Unchanged"
  otherwise.

The text label is retained deliberately. Red and green are the one color pair a
meaningful proportion of users cannot distinguish; the dot reinforces the label
rather than being the sole carrier of the state. The dot is also given an
accessible label matching the text.

Commit rows carry no dot; a commit is immutable by definition.

Colored dots require GTK-level CSS, which the application does not currently
have — all present styling lives inside the WebKit document. A small
`Gtk.CssProvider` defining two style classes is registered once on the default
display. Named GTK theme colors are used with GNOME palette fallbacks so the
dots track the user's light/dark GTK theme.

When `next_cursor` is set, the list ends with a **"Show more"** row that loads
another `history_limit` batch. Paging is session-only and is not persisted.

### 7.3 Controls

- A `view-sidebar-start-symbolic` toggle button is packed at the start of the
  header bar **only when `find_repository()` finds a repository**, so no dead
  control appears for files outside git.
- `Ctrl`+`H` toggles the sidebar via a `win.toggle-sidebar` action.
- `Escape` returns to the working copy when a commit is selected, whether or
  not the sidebar is open.
- Closing the sidebar **retains** the selected revision rather than snapping
  back to the working copy, so a historic version can be read at full width.
  The header-bar subtitle and window title continue to show the SHA, so the
  state stays visible with the sidebar hidden.
- A linked pair of `Gtk.ToggleButton`s at the foot of the sidebar switches
  between **Rendered** and **Diff**. The mode applies to whichever revision is
  selected, including the working copy, whose diff is its uncommitted changes
  against HEAD. The mode is session state and is not persisted.
- When a commit is selected, the header bar shows the filename with
  `2f08c39 · Sep 9` as a subtitle, and the window title becomes
  `document.md — 2f08c39`, so reading the past is never ambiguous.

### 7.4 Live reload and revision state

- **Working copy selected:** today's behavior, unchanged. The monitor fires,
  the 180 ms debounce runs, scroll position is captured, the document reloads.
  This path must not regress.
- **A commit selected:** the preview is never replaced. The file monitor stays
  connected, but a change event refreshes only the working-copy row's status
  dot and label. The historic document remains on screen.
- **Scroll:** `load_document()` takes a revision parameter. Scroll position is
  restored only when the revision is unchanged — a font change, a theme change,
  or a live reload of the working copy. Switching revisions scrolls to the top,
  because restoring an offset into a different document is meaningless.
- **Font and theme changes** while a commit is selected re-render *that
  commit*. `refresh_document()` becomes revision-aware.
- The commit list is re-queried when the sidebar is opened and on debounced
  file-change events. The `.git` directory is **not** watched: a commit created
  externally appears the next time the sidebar is opened. This is an accepted
  limitation and is documented in the README.

### 7.5 Empty and error states

Each is a sidebar row or a rendered message. None crashes the application.

| Condition | Result |
|---|---|
| `pygit2` not importable | No sidebar, no button; MdPrev behaves as today |
| File not inside a repository | No button |
| Inside a repository, file untracked | "Not tracked in this repository" |
| Repository with unborn HEAD | "No commits yet" |
| No commits touch the file | "No history for this file" |
| Walk hit `MAX_SCAN` | List shown, with a note that history was truncated |
| Blob binary or not valid UTF-8 | `error_document()`, matching existing decode errors |
| libgit2 error | `error_document()` with a concise message |
| Empty patch | "No changes in this commit" |

## 8. Accepted limitations

### 8.1 Externally created commits

Covered in §7.4: the commit list refreshes on sidebar open, not on repository
mutation.

### 8.2 Images in historic versions

The WebKit base URI remains the document's directory, so relative image paths
in a historic version resolve against *today's* working tree. An image added
after the selected commit will render; one deleted since will not load. Serving
historic image blobs would require a custom WebKit URI scheme handler and is
out of scope.

## 9. Preferences

Three keys added to `preferences.py`, following the existing
validate-on-load and validate-on-save pattern:

| Key | Type | Default | Constraint |
|---|---|---|---|
| `sidebar_visible` | bool | `False` | — |
| `sidebar_width` | int | 280 | 180–600 |
| `history_limit` | int | 10 | 1–500 |

`history_limit` is configured through the preferences file only. The
display-options popover concerns display, and history depth is not a display
setting. The "Show more" row of §7.2 makes the default of 10 comfortable
without adding a control.

## 10. Verification

### 10.1 Automated

`tests/test_git_history.py` — new. Repositories are built in temporary
directories using pygit2 itself. The whole file sits behind
`pytest.importorskip("pygit2")` so the suite still passes where pygit2 is
absent, consistent with the soft dependency.

1. Linear history returns commits newest first, with correct SHA, summary,
   author, and authored time.
2. A rename (`old.md` → `new.md`) is followed, and `Commit.path` reports the
   name in force at each commit.
3. A merge commit is evaluated against its first parent only.
4. A root commit is diffed against the empty tree and reports the whole file as
   added.
5. An untracked file inside a repository yields empty history without error.
6. A repository with unborn HEAD yields empty history without error.
7. A non-UTF-8 blob raises `GitHistoryError`.
8. `limit` and `after` page correctly, and `next_cursor` resumes without gaps
   or repeats.
9. `MAX_SCAN` truncation sets `truncated=True`.
10. `is_modified()` is false on a clean checkout, true for an unstaged edit, and
    true for a staged-but-uncommitted edit.
11. `find_repository()` returns `None` outside a repository.

`tests/test_render.py` — additions:

12. `render_diff()` escapes a `<script>` tag appearing in patch text.
13. Output carries `class="highlight language-diff"`.
14. Font and theme parameters are honored.
15. `cmark-gfm` is not invoked for diff rendering.

`tests/test_preferences.py` — additions:

16. The three new keys load with defaults, validate types, and clamp
    out-of-range values like the existing keys.

`ruff` passes across the repository.

### 10.2 Manual GNOME verification

Required by `AGENTS.md` before claiming desktop integration works:

1. Open a Markdown file inside a git repository from Files; the sidebar button
   appears.
2. Open a Markdown file outside any repository; no button appears.
3. Toggle the sidebar with the button and with `Ctrl`+`H`; width and visibility
   survive a restart.
4. Select a commit; the rendered historic version appears, and the header bar
   and window title show the SHA.
5. Flip Rendered/Diff; the highlighted patch is legible in Light, Dark, Sepia,
   and System themes.
6. Edit and save the file while a commit is selected; the preview does not
   change, and the working-copy dot turns red.
7. Select the working copy; live reload resumes normally.
8. Repeat with a filename containing spaces and non-ASCII characters.

## 11. Documentation changes

`FEATURE_REQUIREMENTS.md`:

- Add `python3-pygit2` to the runtime packages in §2.
- Add a new §6, "MVP 4: git history sidebar", carrying the required behavior of
  this design and its acceptance criteria.
- **Narrow the deferred entry "Generated table of contents/sidebar" to
  "Generated table of contents".** A sidebar is precisely what this design
  adds; a generated table of contents remains deferred.
- Renumber the deferred-features section to §7 and non-goals to §8.

`AGENTS.md`:

- Add pygit2 to the supported environment, noting it is required only for the
  git history sidebar.
- Add a scope line stating that the git integration is strictly read-only: no
  checkout, no restore, no writes of any kind.

`README.md`:

- Add `python3-pygit2` to the install command.
- Describe the sidebar, the Rendered/Diff toggle, the working-copy status dot,
  and the two accepted limitations of §8.

`install.sh` requires no change; it performs no dependency checking.

## 12. Acceptance criteria

MVP 4 is complete when, on Ubuntu 26.04 GNOME:

1. A document inside a git repository shows a sidebar button; one outside a
   repository does not.
2. The sidebar lists commits touching the file, newest first, honoring
   `history_limit`, with "Show more" paging beyond it.
3. A renamed file's history continues past the rename.
4. Selecting a commit renders that version of the document with current font,
   theme, and highlighting settings.
5. The Diff view shows the highlighted unified diff of the Markdown source,
   legible in all four themes.
6. The working-copy row shows a red dot and "Modified" when the file differs
   from HEAD, staged or unstaged, and a green dot and "Unchanged" otherwise.
7. Saving the file while a commit is selected leaves the preview untouched and
   updates the status dot.
8. Selecting the working copy restores live reload.
9. Sidebar visibility and width persist across sessions.
10. Every empty and error state of §7.5 is reached without a crash.
11. The source file and the repository are never written.
12. MVP 1, MVP 2, and MVP 3 acceptance criteria continue to pass.
13. With `python3-pygit2` absent, the application behaves exactly as it did
    before MVP 4.
