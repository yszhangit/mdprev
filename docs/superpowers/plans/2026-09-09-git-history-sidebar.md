# Git History Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable sidebar to MdPrev that lists the git commits touching the open Markdown document, and renders any revision either as formatted Markdown or as a highlighted unified diff.

**Architecture:** A new display-free module `mdprev/git_history.py` wraps pygit2 and returns plain dataclasses; it never writes. A new GTK widget `mdprev/sidebar.py` owns the commit list and view toggle and reports selections through a callback. `mdprev/app.py` hosts both in a `Gtk.Paned` and gains revision state that governs which source feeds the existing render pipeline. Historic content flows through the same sanitizer as the live file.

**Tech Stack:** Python 3, PyGObject, GTK 4, WebKitGTK 6.0, pygit2 1.19 (libgit2), Pygments, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-09-git-history-design.md`

## Global Constraints

- Target platform is Ubuntu 26.04 LTS (Resolute), GNOME 50, Wayland. No cross-platform abstractions.
- System packages only. Do not add a virtualenv, vendored dependency, Node.js, or a bundled web server.
- pygit2 is a **soft** dependency: `git_history.AVAILABLE` is `False` when it cannot be imported, and MdPrev must then behave exactly as it does today.
- The application never writes the Markdown source file and never writes the repository. No checkout, restore, stash, or commit.
- WebKit JavaScript stays disabled except around the trusted scroll expressions already present in `app.py`.
- Raw HTML from any source, historic revisions included, is never rendered. Historic content is untrusted and passes through `sanitize_fragment` exactly as the live file does.
- No broad `except Exception`. Convert expected pygit2, I/O, and decoding failures into `GitHistoryError` with concise user-facing text.
- Use `pathlib` for filesystem paths. No shell interpolation anywhere.
- All settings are global. Per-file preferences are a non-goal (spec §2).
- **Use `/usr/bin/python3` for every test run.** A conda Python 3.13 shadows
  `python3` on PATH in this environment and has neither `gi` nor `pygit2`, so a
  bare `python3 -m pytest` would silently skip every `importorskip("pygit2")`
  test and report green. The system Python 3.14 has pytest, pygments, gi, and
  pygit2 1.19.1, and is what `bin/mdprev` executes.
- Every task ends with `/usr/bin/python3 -m pytest` and `ruff check .` passing before the commit.

## Deviations from the spec, resolved here

Three interface details in the spec do not survive implementation. The spec has been amended to match; they are restated here because they change signatures used across tasks.

1. **`History.next_cursor` is a `Cursor`, not a `str`.** Resuming a walk needs the tracked path as of the cursor revision, not just its sha — after a rename, older commits live under a different name, and a bare sha loses that. `Cursor` carries `sha` and `path`.
2. **`git_history.is_tracked()` is added.** Spec §7.5 distinguishes "Not tracked in this repository" from "No history for this file". Nothing in the original interface list could tell those apart.
3. **The sidebar callback passes a `Commit`, not a sha.** Rendering a revision needs `Commit.path` (the name in force at that commit) as well as the sha, and the header-bar subtitle needs the date. Passing the record avoids a redundant lookup.

---

### Task 1: Dependency, module skeleton, and API probe

pygit2 is not installed in this checkout. Install it first, then confirm the API surface this plan assumes before writing code against it.

**Files:**
- Create: `mdprev/git_history.py`
- Create: `tests/test_git_history.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `git_history.AVAILABLE: bool`, `git_history.GitHistoryError`, `git_history.Commit`, `git_history.Cursor`, `git_history.History`, `git_history.MAX_SCAN`.

- [x] **Step 1: Install pygit2** — ALREADY DONE

`python3-pygit2` 1.19.1-1build1 is installed for `/usr/bin/python3` (3.14).
Do not re-install. Verify with:

```bash
/usr/bin/python3 -c "import pygit2; print(pygit2.__version__)"
```

Expected: `1.19.1`

- [ ] **Step 2: Probe the API surface this plan assumes**

The remaining tasks assume specific pygit2 names. Verify them now rather than discovering a mismatch in Task 3.

```bash
python3 - <<'PROBE'
import inspect
import pygit2
from pygit2.enums import DeltaStatus, FileStatus, SortMode
print("pygit2", pygit2.__version__, "libgit2", pygit2.LIBGIT2_VERSION)
print("SortMode.TOPOLOGICAL|TIME", SortMode.TOPOLOGICAL | SortMode.TIME)
print("DeltaStatus.RENAMED", DeltaStatus.RENAMED)
print("FileStatus.CURRENT/IGNORED/WT_MODIFIED",
      FileStatus.CURRENT, FileStatus.IGNORED, FileStatus.WT_MODIFIED)
print("discover_repository", inspect.signature(pygit2.discover_repository))
print("Patch.create_from", inspect.signature(pygit2.Patch.create_from))
print("init_repository", inspect.signature(pygit2.init_repository))
print("Signature", inspect.signature(pygit2.Signature.__init__))
for name in ("walk", "diff", "status_file", "create_commit", "head_is_unborn", "workdir", "index"):
    print("Repository." + name, "OK" if hasattr(pygit2.Repository, name) else "MISSING")
for name in ("find_similar", "patch"):
    print("Diff." + name, "OK" if hasattr(pygit2.Diff, name) else "MISSING")
PROBE
```

**This probe has already been run against pygit2 1.19.1 / libgit2 1.9.1, and every
call the plan makes is confirmed working.** Do not re-run it. Verified results:

- `SortMode.TOPOLOGICAL | SortMode.TIME`, `DeltaStatus.RENAMED`,
  `FileStatus.CURRENT` (0) and `FileStatus.IGNORED` all exist in `pygit2.enums`.
- Nested tree lookup segment-by-segment (`node = node[part]`) returns a `Blob`
  with working `.is_binary` and `.data`.
- `repo.revparse_single("not-a-sha")` raises `KeyError`.
- `repo.status_file()` returns `0` for a clean file, `256` (`WT_MODIFIED`) when
  edited, and raises `KeyError` for an absent path. `"path" in repo.index` works.
- `Patch.create_from` works in all three forms the plan uses — blob to blob,
  `None` to blob (root commit, emits `new file mode`), and blob to `bytes`
  (working copy) — and returns `''` for identical blobs, so `patch.text or ""`
  is correct.
- `diff.find_similar()` then `delta.status == DeltaStatus.RENAMED` correctly
  reports `old.md -> new.md`.
- Real `patch.text` begins `diff --git a/... b/...`, then an `index` line, then
  `--- a/...`, `+++ b/...`, then `@@` hunks. The Task 6 assertions match this.

- [ ] **Step 3: Write the failing test**

```python
"""Repository history queries, tested against real temporary repositories."""

import pytest

pygit2 = pytest.importorskip("pygit2")

from mdprev import git_history


def test_module_reports_pygit2_available():
    assert git_history.AVAILABLE is True


def test_git_history_error_is_a_runtime_error():
    assert issubclass(git_history.GitHistoryError, RuntimeError)


def test_commit_record_is_frozen():
    commit = git_history.Commit(
        sha="0" * 40,
        short_sha="0" * 7,
        summary="Subject",
        author="Test Author",
        when=None,
        path="doc.md",
    )
    with pytest.raises(Exception):
        commit.sha = "1" * 40


def test_history_defaults_to_no_cursor():
    history = git_history.History(commits=[], truncated=False, next_cursor=None)
    assert history.commits == []
    assert history.truncated is False
    assert history.next_cursor is None


def test_max_scan_is_bounded():
    assert git_history.MAX_SCAN == 2000
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mdprev.git_history'`

- [ ] **Step 5: Write the module skeleton**

Create `mdprev/git_history.py`:

```python
"""Read-only git history queries for the open document.

The module is deliberately free of GTK so that it can be unit tested without a
display server, matching the arrangement already used by render.py.  Nothing
here writes to the repository or to the filesystem.

pygit2 is an optional dependency.  When it is missing the application must
behave exactly as it did before the history sidebar existed, so every entry
point is guarded by AVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import pygit2
    from pygit2.enums import DeltaStatus, FileStatus, SortMode

    AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where pygit2 is absent
    pygit2 = None
    DeltaStatus = FileStatus = SortMode = None
    AVAILABLE = False


# A walk is bounded by work rather than by a clock: running in-process there is
# no subprocess timeout to fall back on, and a scanned-revision ceiling is
# deterministic and testable.
MAX_SCAN = 2000


class GitHistoryError(RuntimeError):
    """An expected error while reading repository history."""


@dataclass(frozen=True)
class Commit:
    sha: str
    short_sha: str
    summary: str
    author: str
    when: datetime
    path: str


@dataclass(frozen=True)
class Cursor:
    """Where to resume a walk.

    The tracked path travels with the sha because a resumed walk continues
    below a rename, where older revisions carry a different name.
    """

    sha: str
    path: str


@dataclass(frozen=True)
class History:
    commits: list[Commit]
    truncated: bool
    next_cursor: Cursor | None
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 5 passed

- [ ] **Step 7: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 8: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Add git history module skeleton and record types"
```

---

### Task 2: Repository discovery and path resolution

**Files:**
- Modify: `mdprev/git_history.py`
- Modify: `tests/test_git_history.py`

**Interfaces:**
- Consumes: `GitHistoryError` from Task 1.
- Produces: `find_repository(path: Path) -> pygit2.Repository | None`, `is_tracked(repo, path: Path) -> bool`, and the private `_relative_path(repo, path: Path) -> str` used by every later working-tree function.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_git_history.py`. The two fixtures are used by every later task.

```python
@pytest.fixture
def repo_factory(tmp_path):
    """Build real temporary repositories; libgit2 behavior is what we test."""

    def make(name="repo"):
        workdir = tmp_path / name
        workdir.mkdir()
        repo = pygit2.init_repository(str(workdir))
        return repo, workdir

    return make


def commit_file(repo, workdir, relpath, content, message, when=1700000000):
    """Write, stage, and commit one file. Returns the new commit's sha."""
    file_path = workdir / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    repo.index.add(relpath)
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    oid = repo.create_commit("HEAD", signature, signature, message, tree, parents)
    return str(oid)


def test_find_repository_locates_the_enclosing_repository(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "# Title\n", "Add doc")

    found = git_history.find_repository(workdir / "doc.md")

    assert found is not None
    assert Path(found.workdir).resolve() == workdir.resolve()


def test_find_repository_locates_from_a_subdirectory(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "docs/doc.md", "# Title\n", "Add doc")

    found = git_history.find_repository(workdir / "docs" / "doc.md")

    assert found is not None


def test_find_repository_returns_none_outside_a_repository(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "doc.md").write_text("# Title\n", encoding="utf-8")

    assert git_history.find_repository(loose / "doc.md") is None


def test_relative_path_is_repo_relative_and_posix(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "docs/doc.md", "# Title\n", "Add doc")

    assert git_history._relative_path(repo, workdir / "docs" / "doc.md") == "docs/doc.md"


def test_relative_path_rejects_a_path_outside_the_repository(repo_factory, tmp_path):
    repo, _workdir = repo_factory()
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# Title\n", encoding="utf-8")

    with pytest.raises(git_history.GitHistoryError):
        git_history._relative_path(repo, outside)


def test_is_tracked_distinguishes_tracked_from_untracked(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "# Title\n", "Add doc")
    (workdir / "scratch.md").write_text("# Scratch\n", encoding="utf-8")

    assert git_history.is_tracked(repo, workdir / "doc.md") is True
    assert git_history.is_tracked(repo, workdir / "scratch.md") is False
```

Add `from pathlib import Path` to the test module's imports.

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: FAIL with `AttributeError: module 'mdprev.git_history' has no attribute 'find_repository'`

- [ ] **Step 3: Write the implementation**

Append to `mdprev/git_history.py`:

```python
def find_repository(path: Path) -> "pygit2.Repository | None":
    """Return the repository containing path, or None when there is none."""

    if not AVAILABLE:
        return None
    try:
        discovered = pygit2.discover_repository(str(Path(path).parent))
    except pygit2.GitError:
        return None
    if discovered is None:
        return None
    try:
        repo = pygit2.Repository(discovered)
    except pygit2.GitError:
        return None
    # A bare repository has no working tree, so no document can live inside it.
    if repo.is_bare or repo.workdir is None:
        return None
    return repo


def _relative_path(repo, path: Path) -> str:
    """Return path as a repo-relative POSIX string."""

    workdir = Path(repo.workdir).resolve()
    try:
        relative = Path(path).resolve().relative_to(workdir)
    except ValueError as exc:
        raise GitHistoryError(
            f"{Path(path).name} is outside this repository"
        ) from exc
    return relative.as_posix()


def is_tracked(repo, path: Path) -> bool:
    """Report whether the file is in the index at all."""

    try:
        relative = _relative_path(repo, path)
    except GitHistoryError:
        return False
    return relative in repo.index
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 11 passed

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Add repository discovery and path resolution"
```

---

### Task 3: Walking history for one file

The walk compares blob OIDs between a commit and its first parent — two tree lookups per revision, no diff computed. Rename detection is Task 4.

**Files:**
- Modify: `mdprev/git_history.py`
- Modify: `tests/test_git_history.py`

**Interfaces:**
- Consumes: `_relative_path`, `Commit`, `Cursor`, `History`, `MAX_SCAN`.
- Produces: `history(repo, path: Path, limit: int = 10, after: Cursor | None = None) -> History`, and the private `_entry(tree, relpath) -> pygit2.Blob | None`.

- [ ] **Step 1: Write the failing test**

```python
def test_history_returns_commits_newest_first(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "two\n", "Second", when=1700000100)

    result = git_history.history(repo, workdir / "doc.md")

    assert [c.summary for c in result.commits] == ["Second", "First"]
    assert result.truncated is False
    assert result.next_cursor is None


def test_history_records_commit_metadata(repo_factory):
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", "one\n", "Subject line\n\nBody\n")

    commit = git_history.history(repo, workdir / "doc.md").commits[0]

    assert commit.sha == sha
    assert commit.short_sha == sha[:7]
    assert commit.summary == "Subject line"
    assert commit.author == "Test Author"
    assert commit.path == "doc.md"
    assert commit.when.year == 2023


def test_history_skips_commits_that_do_not_touch_the_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Touches doc")
    commit_file(repo, workdir, "other.md", "x\n", "Touches other")

    result = git_history.history(repo, workdir / "doc.md")

    assert [c.summary for c in result.commits] == ["Touches doc"]


def test_history_includes_the_commit_that_deletes_the_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Add doc")
    (workdir / "doc.md").unlink()
    repo.index.remove("doc.md")
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000200, 0)
    repo.create_commit("HEAD", signature, signature, "Delete doc", tree, [repo.head.target])

    result = git_history.history(repo, workdir / "doc.md")

    assert [c.summary for c in result.commits] == ["Delete doc", "Add doc"]


def test_history_is_empty_for_an_unborn_head(repo_factory):
    repo, workdir = repo_factory()
    (workdir / "doc.md").write_text("# Title\n", encoding="utf-8")

    result = git_history.history(repo, workdir / "doc.md")

    assert result.commits == []
    assert result.next_cursor is None


def test_history_is_empty_for_an_untracked_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Add doc")
    (workdir / "scratch.md").write_text("# Scratch\n", encoding="utf-8")

    assert git_history.history(repo, workdir / "scratch.md").commits == []


def test_history_honors_the_limit_and_reports_a_cursor(repo_factory):
    repo, workdir = repo_factory()
    for index in range(5):
        commit_file(repo, workdir, "doc.md", f"line {index}\n", f"Commit {index}",
                    when=1700000000 + index)

    result = git_history.history(repo, workdir / "doc.md", limit=2)

    assert [c.summary for c in result.commits] == ["Commit 4", "Commit 3"]
    assert result.next_cursor is not None
    assert result.next_cursor.sha == result.commits[-1].sha
    assert result.next_cursor.path == "doc.md"


def test_history_resumes_after_a_cursor_without_gaps_or_repeats(repo_factory):
    repo, workdir = repo_factory()
    for index in range(5):
        commit_file(repo, workdir, "doc.md", f"line {index}\n", f"Commit {index}",
                    when=1700000000 + index)

    first = git_history.history(repo, workdir / "doc.md", limit=2)
    second = git_history.history(repo, workdir / "doc.md", limit=2, after=first.next_cursor)

    assert [c.summary for c in second.commits] == ["Commit 2", "Commit 1"]
    assert second.next_cursor is not None


def test_history_cursor_is_none_at_the_end_of_history(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Only")

    result = git_history.history(repo, workdir / "doc.md", limit=10)

    assert result.next_cursor is None


def test_history_truncates_at_the_scan_ceiling(repo_factory, monkeypatch):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Touches doc")
    for index in range(4):
        commit_file(repo, workdir, "other.md", f"{index}\n", f"Noise {index}")
    monkeypatch.setattr(git_history, "MAX_SCAN", 3)

    result = git_history.history(repo, workdir / "doc.md")

    assert result.truncated is True
    assert result.commits == []
    # A truncated walk must stay resumable, or "Show more" dead-ends.
    assert result.next_cursor is not None


def test_history_resumes_after_a_truncated_walk(repo_factory, monkeypatch):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "Touches doc", when=1700000000)
    for index in range(4):
        commit_file(repo, workdir, "other.md", f"{index}\n", f"Noise {index}",
                    when=1700000100 + index)
    monkeypatch.setattr(git_history, "MAX_SCAN", 3)

    first = git_history.history(repo, workdir / "doc.md")
    second = git_history.history(repo, workdir / "doc.md", after=first.next_cursor)

    assert [c.summary for c in second.commits] == ["Touches doc"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: FAIL with `AttributeError: module 'mdprev.git_history' has no attribute 'history'`

- [ ] **Step 3: Write the implementation**

Append to `mdprev/git_history.py`:

```python
def _entry(tree, relpath: str):
    """Return the blob at relpath within tree, or None when absent.

    Path segments are walked explicitly so that nested paths behave the same
    way across pygit2 versions.
    """

    node = tree
    for part in relpath.split("/"):
        if not isinstance(node, pygit2.Tree):
            return None
        try:
            node = node[part]
        except KeyError:
            return None
    return node if isinstance(node, pygit2.Blob) else None


def _commit_record(commit, path: str) -> Commit:
    author = commit.author
    when = datetime.fromtimestamp(
        author.time, tz=timezone(timedelta(minutes=author.offset))
    )
    message = commit.message.strip()
    summary = message.splitlines()[0] if message else ""
    sha = str(commit.id)
    return Commit(
        sha=sha,
        short_sha=sha[:7],
        summary=summary,
        author=author.name,
        when=when,
        path=path,
    )


def history(repo, path: Path, limit: int = 10, after: Cursor | None = None) -> History:
    """Return commits touching path, newest first.

    A commit touches the file when the blob recorded at the tracked path
    differs from the one recorded in its first parent.  Merge commits are
    compared against their first parent only, matching git log --follow.
    """

    if repo.head_is_unborn:
        return History(commits=[], truncated=False, next_cursor=None)
    tracked = after.path if after is not None else _relative_path(repo, path)
    skipping = after.sha if after is not None else None

    commits: list[Commit] = []
    scanned = 0
    truncated = False
    next_cursor: Cursor | None = None
    last_seen: str | None = None

    for commit in repo.walk(repo.head.target, SortMode.TOPOLOGICAL | SortMode.TIME):
        if skipping is not None:
            # Revisions above the cursor were reported by an earlier call.
            if str(commit.id) == skipping:
                skipping = None
            continue
        if scanned >= MAX_SCAN:
            # Resume below the last revision actually examined, so that the
            # revision which tripped the ceiling is not skipped.
            truncated = True
            if last_seen is not None:
                next_cursor = Cursor(sha=last_seen, path=tracked)
            break
        scanned += 1
        last_seen = str(commit.id)

        entry = _entry(commit.tree, tracked)
        parent = commit.parents[0] if commit.parents else None
        parent_entry = _entry(parent.tree, tracked) if parent is not None else None
        current_id = str(entry.id) if entry is not None else None
        parent_id = str(parent_entry.id) if parent_entry is not None else None
        if current_id == parent_id:
            continue

        commits.append(_commit_record(commit, tracked))
        if len(commits) >= limit:
            next_cursor = Cursor(sha=str(commit.id), path=tracked)
            break

    return History(commits=commits, truncated=truncated, next_cursor=next_cursor)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 22 passed

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Walk file history by comparing blob OIDs against the first parent"
```

---

### Task 4: Following renames

Rename detection is expensive, so it runs only when the tracked path exists in a commit but is absent from its parent.

**Files:**
- Modify: `mdprev/git_history.py`
- Modify: `tests/test_git_history.py`

**Interfaces:**
- Consumes: `_entry`, `history` from Task 3.
- Produces: `_rename_source(repo, parent, commit, tracked: str) -> str | None`. `history()` now updates its tracked path across renames, and `Commit.path` reports the name in force at each commit.

- [ ] **Step 1: Write the failing test**

```python
def rename_file(repo, workdir, old_relpath, new_relpath, message, when=1700000300):
    """Rename a tracked file and commit the rename."""
    (workdir / old_relpath).rename(workdir / new_relpath)
    repo.index.remove(old_relpath)
    repo.index.add(new_relpath)
    repo.index.write()
    tree = repo.index.write_tree()
    signature = pygit2.Signature("Test Author", "test@example.com", when, 0)
    oid = repo.create_commit("HEAD", signature, signature, message, tree, [repo.head.target])
    return str(oid)


def test_history_follows_a_rename(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)
    commit_file(repo, workdir, "new.md", "shared content\n" * 20 + "more\n", "Edit new",
                when=1700000200)

    result = git_history.history(repo, workdir / "new.md")

    assert [c.summary for c in result.commits] == ["Edit new", "Rename to new", "Add old"]


def test_history_reports_the_path_in_force_at_each_commit(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)

    result = git_history.history(repo, workdir / "new.md")

    by_summary = {c.summary: c.path for c in result.commits}
    assert by_summary["Rename to new"] == "new.md"
    assert by_summary["Add old"] == "old.md"


def test_history_cursor_carries_the_path_across_a_rename(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)

    first = git_history.history(repo, workdir / "new.md", limit=1)

    assert first.next_cursor.path == "old.md"
    second = git_history.history(repo, workdir / "new.md", limit=1, after=first.next_cursor)
    assert [c.summary for c in second.commits] == ["Add old"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -k rename -v`
Expected: FAIL — `test_history_follows_a_rename` reports only `["Edit new", "Rename to new"]` because the walk loses the file at its old name.

- [ ] **Step 3: Write the implementation**

Append `_rename_source` to `mdprev/git_history.py`:

```python
def _rename_source(repo, parent, commit, tracked: str) -> str | None:
    """Return the file's previous name when this commit renamed it.

    Only called when the path exists in the commit and is absent from the
    parent, because computing a rename-detecting diff is far more expensive
    than the tree lookups that drive the walk.
    """

    diff = repo.diff(parent.tree, commit.tree)
    diff.find_similar()
    for patch in diff:
        delta = patch.delta
        if delta.new_file.path == tracked and delta.status == DeltaStatus.RENAMED:
            return delta.old_file.path
    return None
```

In `history()`, replace the block from `commits.append(...)` through the limit check with:

```python
        renamed_from = None
        if entry is not None and parent_entry is None and parent is not None:
            renamed_from = _rename_source(repo, parent, commit, tracked)

        commits.append(_commit_record(commit, tracked))
        if renamed_from is not None:
            # Older revisions carry the file under its previous name.
            tracked = renamed_from
        if len(commits) >= limit:
            next_cursor = Cursor(sha=str(commit.id), path=tracked)
            break
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 25 passed

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Follow renames when walking file history"
```

---

### Task 5: Reading a file at a revision

**Files:**
- Modify: `mdprev/git_history.py`
- Modify: `tests/test_git_history.py`

**Interfaces:**
- Consumes: `_entry`, `GitHistoryError`.
- Produces: `file_at(repo, sha: str, path: str) -> str`. Note `path` is a **repo-relative string** taken from `Commit.path`, not an on-disk `Path`.

- [ ] **Step 1: Write the failing test**

```python
def test_file_at_returns_the_content_of_that_revision(repo_factory):
    repo, workdir = repo_factory()
    first = commit_file(repo, workdir, "doc.md", "# One\n", "First", when=1700000000)
    commit_file(repo, workdir, "doc.md", "# Two\n", "Second", when=1700000100)

    assert git_history.file_at(repo, first, "doc.md") == "# One\n"


def test_file_at_reads_under_the_historic_name(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_file(repo, workdir, "old.md", "new.md", "Rename to new", when=1700000100)

    oldest = git_history.history(repo, workdir / "new.md").commits[-1]

    assert git_history.file_at(repo, oldest.sha, oldest.path).startswith("shared content")


def test_file_at_rejects_a_revision_that_lacks_the_file(repo_factory):
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", "# One\n", "First")

    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(repo, sha, "absent.md")


def test_file_at_rejects_an_unparseable_revision(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "# One\n", "First")

    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(repo, "not-a-sha", "doc.md")


def test_file_at_rejects_content_that_is_not_utf8(repo_factory):
    repo, workdir = repo_factory()
    sha = commit_file(repo, workdir, "doc.md", b"\xff\xfe invalid\n", "Binary")

    with pytest.raises(git_history.GitHistoryError):
        git_history.file_at(repo, sha, "doc.md")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -k file_at -v`
Expected: FAIL with `AttributeError: module 'mdprev.git_history' has no attribute 'file_at'`

- [ ] **Step 3: Write the implementation**

Append to `mdprev/git_history.py`:

```python
def _lookup_commit(repo, sha: str):
    try:
        commit = repo.revparse_single(sha)
    except (KeyError, ValueError, pygit2.GitError) as exc:
        raise GitHistoryError(f"Unknown revision {sha[:7]}") from exc
    if not isinstance(commit, pygit2.Commit):
        raise GitHistoryError(f"{sha[:7]} is not a commit")
    return commit


def file_at(repo, sha: str, path: str) -> str:
    """Return the UTF-8 text of path as recorded at sha."""

    commit = _lookup_commit(repo, sha)
    blob = _entry(commit.tree, path)
    if blob is None:
        raise GitHistoryError(f"{path} does not exist at {sha[:7]}")
    if blob.is_binary:
        raise GitHistoryError(f"Unable to read {path} at {sha[:7]}: the file is binary")
    try:
        return blob.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHistoryError(
            f"Unable to read {path} at {sha[:7]}: the file is not valid UTF-8"
        ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 30 passed

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Read document content at a given revision"
```

---

### Task 6: Producing unified diffs

Patches are built directly from the two blobs with `Patch.create_from` rather than by diffing whole trees, so the work is proportional to the file rather than to the repository.

**Files:**
- Modify: `mdprev/git_history.py`
- Modify: `tests/test_git_history.py`

**Interfaces:**
- Consumes: `_entry`, `_lookup_commit`, `_rename_source`, `_relative_path`.
- Produces: `patch_for(repo, sha: str, path: str) -> str` (repo-relative `path`), `working_patch(repo, path: Path) -> str` (on-disk `Path`).

- [ ] **Step 1: Write the failing test**

```python
def test_patch_for_shows_added_and_removed_lines(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "one\n", "First", when=1700000000)
    second = commit_file(repo, workdir, "doc.md", "two\n", "Second", when=1700000100)

    patch = git_history.patch_for(repo, second, "doc.md")

    assert "@@" in patch
    assert "-one" in patch
    assert "+two" in patch


def test_patch_for_a_root_commit_shows_the_whole_file_as_added(repo_factory):
    repo, workdir = repo_factory()
    first = commit_file(repo, workdir, "doc.md", "one\ntwo\n", "First")

    patch = git_history.patch_for(repo, first, "doc.md")

    assert "+one" in patch
    assert "+two" in patch
    assert "-one" not in patch


def test_patch_for_a_rename_diffs_against_the_old_name(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "old.md", "shared content\n" * 20, "Add old",
                when=1700000000)
    rename_sha = rename_file(repo, workdir, "old.md", "new.md", "Rename", when=1700000100)

    patch = git_history.patch_for(repo, rename_sha, "new.md")

    assert "old.md" in patch


def test_patch_for_a_merge_uses_the_first_parent(repo_factory):
    repo, workdir = repo_factory()
    base = commit_file(repo, workdir, "doc.md", "base\n", "Base", when=1700000000)
    repo.branches.local.create("side", repo[base])
    commit_file(repo, workdir, "doc.md", "main\n", "Main edit", when=1700000100)
    main_tip = repo.head.target
    side_tip = repo.branches.local["side"].target
    signature = pygit2.Signature("Test Author", "test@example.com", 1700000200, 0)
    merge_sha = str(repo.create_commit(
        "HEAD", signature, signature, "Merge", repo[main_tip].tree_id,
        [main_tip, side_tip],
    ))

    patch = git_history.patch_for(repo, merge_sha, "doc.md")

    assert patch == ""


def test_working_patch_shows_uncommitted_changes(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").write_text("edited\n", encoding="utf-8")

    patch = git_history.working_patch(repo, workdir / "doc.md")

    assert "-committed" in patch
    assert "+edited" in patch


def test_working_patch_is_empty_for_a_clean_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")

    assert git_history.working_patch(repo, workdir / "doc.md") == ""


def test_working_patch_reports_an_unreadable_file(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").unlink()

    with pytest.raises(git_history.GitHistoryError):
        git_history.working_patch(repo, workdir / "doc.md")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -k patch -v`
Expected: FAIL with `AttributeError: module 'mdprev.git_history' has no attribute 'patch_for'`

- [ ] **Step 3: Write the implementation**

Append to `mdprev/git_history.py`:

```python
def patch_for(repo, sha: str, path: str) -> str:
    """Return the unified diff of path at sha against its first parent."""

    commit = _lookup_commit(repo, sha)
    new_blob = _entry(commit.tree, path)
    parent = commit.parents[0] if commit.parents else None
    old_path = path
    old_blob = None
    if parent is not None:
        old_blob = _entry(parent.tree, path)
        if new_blob is not None and old_blob is None:
            source = _rename_source(repo, parent, commit, path)
            if source is not None:
                old_path = source
                old_blob = _entry(parent.tree, source)
    if old_blob is None and new_blob is None:
        return ""
    patch = pygit2.Patch.create_from(
        old_blob,
        new_blob,
        old_as_path=old_path,
        new_as_path=path,
    )
    return patch.text or ""


def working_patch(repo, path: Path) -> str:
    """Return the unified diff of the file on disk against HEAD."""

    relative = _relative_path(repo, path)
    old_blob = None
    if not repo.head_is_unborn:
        old_blob = _entry(repo[repo.head.target].tree, relative)
    try:
        new_data = Path(path).read_bytes()
    except OSError as exc:
        raise GitHistoryError(
            f"Unable to read {Path(path).name}: {exc.strerror or exc}"
        ) from exc
    if old_blob is None and not new_data:
        return ""
    patch = pygit2.Patch.create_from(
        old_blob,
        new_data,
        old_as_path=relative,
        new_as_path=relative,
    )
    return patch.text or ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 37 passed

If `Patch.create_from` produced different header text than the assertions expect, adjust the **assertions** to the real output — but only assertions about header formatting. The `@@`, `+line`, and `-line` assertions pin behavior that must hold.

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Produce unified diffs for revisions and the working copy"
```

---

### Task 7: Working-copy status

**Files:**
- Modify: `mdprev/git_history.py`
- Modify: `tests/test_git_history.py`

**Interfaces:**
- Consumes: `_relative_path`.
- Produces: `is_modified(repo, path: Path) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
def test_is_modified_is_false_on_a_clean_checkout(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")

    assert git_history.is_modified(repo, workdir / "doc.md") is False


def test_is_modified_is_true_for_an_unstaged_edit(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").write_text("edited\n", encoding="utf-8")

    assert git_history.is_modified(repo, workdir / "doc.md") is True


def test_is_modified_is_true_for_a_staged_but_uncommitted_edit(repo_factory):
    repo, workdir = repo_factory()
    commit_file(repo, workdir, "doc.md", "committed\n", "First")
    (workdir / "doc.md").write_text("staged\n", encoding="utf-8")
    repo.index.add("doc.md")
    repo.index.write()

    assert git_history.is_modified(repo, workdir / "doc.md") is True


def test_is_modified_is_false_for_a_path_outside_the_repository(repo_factory, tmp_path):
    repo, _workdir = repo_factory()
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# Title\n", encoding="utf-8")

    assert git_history.is_modified(repo, outside) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -k is_modified -v`
Expected: FAIL with `AttributeError: module 'mdprev.git_history' has no attribute 'is_modified'`

- [ ] **Step 3: Write the implementation**

Append to `mdprev/git_history.py`:

```python
def is_modified(repo, path: Path) -> bool:
    """Report whether the file differs from HEAD, staged or unstaged.

    Local status only: no remote, upstream, or ahead/behind information is
    consulted.
    """

    try:
        relative = _relative_path(repo, path)
    except GitHistoryError:
        return False
    try:
        status = repo.status_file(relative)
    except KeyError:
        return False
    if status & FileStatus.IGNORED:
        return False
    return status != FileStatus.CURRENT
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_git_history.py -v`
Expected: 41 passed

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/git_history.py tests/test_git_history.py
git commit -m "Report whether the working copy differs from HEAD"
```

---

### Task 8: Rendering diffs

**Files:**
- Modify: `mdprev/render.py`
- Modify: `tests/test_render.py`

**Interfaces:**
- Consumes: the existing private `_document`, `_LEXERS`, and the Pygments imports in `render.py`.
- Produces: `render.render_diff(patch: str, font: str = "system", theme: str = "system") -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
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
```

Ensure `tests/test_render.py` imports `re` and `from html import unescape`; add them if absent.

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_render.py -k render_diff -v`
Expected: FAIL with `AttributeError: module 'mdprev.render' has no attribute 'render_diff'`

- [ ] **Step 3: Write the implementation**

Add to `mdprev/render.py`, after `error_document`:

```python
def render_diff(patch: str, font: str = "system", theme: str = "system") -> str:
    """Return a complete HTML document showing a unified diff.

    cmark is deliberately not involved: a patch must never be parsed as
    Markdown.  Highlighting reuses the DiffLexer already available for fenced
    code blocks, so themes and palettes apply unchanged.
    """

    if not patch.strip():
        return _document(
            '<p class="empty">No changes in this commit.</p>', font=font, theme=theme
        )
    highlighted = highlight(patch, DiffLexer(), HtmlFormatter(nowrap=True))
    # The formatter must never be allowed to change the patch text.
    rendered_text = unescape(re.sub(r"<[^>]+>", "", highlighted))
    if rendered_text.rstrip("\n") != patch.rstrip("\n"):
        return _document(
            f'<pre><code class="language-diff">{escape(patch)}</code></pre>',
            font=font,
            theme=theme,
        )
    return _document(
        f'<pre><code class="highlight language-diff">{highlighted}</code></pre>',
        font=font,
        theme=theme,
    )
```

Add the `.empty` rule to the stylesheet in `_document`, next to the existing `.error` rule:

```
.empty {{ color: var(--quote-color); }}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_render.py -v`
Expected: all existing tests plus 6 new ones pass

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/render.py tests/test_render.py
git commit -m "Render unified diffs through the existing highlight pipeline"
```

---

### Task 9: Sidebar preferences

**Files:**
- Modify: `mdprev/preferences.py`
- Modify: `tests/test_preferences.py`

**Interfaces:**
- Consumes: existing `load_preferences` / `save_preferences`.
- Produces: `sidebar_visible: bool`, `sidebar_width: int`, `history_limit: int` in the preferences dict and as keyword arguments to `save_preferences`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_preferences.py`:

```python
def test_defaults_include_sidebar_and_history_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    prefs = preferences.load_preferences()

    assert prefs["sidebar_visible"] is False
    assert prefs["sidebar_width"] == 280
    assert prefs["history_limit"] == 10


def test_sidebar_and_history_values_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    preferences.save_preferences(sidebar_visible=True, sidebar_width=340, history_limit=25)
    prefs = preferences.load_preferences()

    assert prefs["sidebar_visible"] is True
    assert prefs["sidebar_width"] == 340
    assert prefs["history_limit"] == 25


def test_out_of_range_sidebar_width_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    preferences.save_preferences(sidebar_width=10_000)

    assert preferences.load_preferences()["sidebar_width"] == 280


def test_out_of_range_history_limit_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    preferences.save_preferences(history_limit=0)

    assert preferences.load_preferences()["history_limit"] == 10


def test_wrongly_typed_sidebar_values_fall_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config = tmp_path / "mdprev" / "preferences.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"sidebar_visible": "yes", "sidebar_width": "wide", "history_limit": 1.5}',
        encoding="utf-8",
    )

    prefs = preferences.load_preferences()

    assert prefs["sidebar_visible"] is False
    assert prefs["sidebar_width"] == 280
    assert prefs["history_limit"] == 10
```

Match the existing module's import style in `tests/test_preferences.py` when referring to `preferences`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_preferences.py -v`
Expected: FAIL with `KeyError: 'sidebar_visible'`

- [ ] **Step 3: Write the implementation**

Add constants beside the existing ones in `mdprev/preferences.py`:

```python
DEFAULT_SIDEBAR_VISIBLE = False
DEFAULT_SIDEBAR_WIDTH = 280
DEFAULT_HISTORY_LIMIT = 10

MIN_SIDEBAR_WIDTH = 180
MAX_SIDEBAR_WIDTH = 600
MIN_HISTORY_LIMIT = 1
MAX_HISTORY_LIMIT = 500
```

Add to the defaults dict in `load_preferences`:

```python
        "sidebar_visible": DEFAULT_SIDEBAR_VISIBLE,
        "sidebar_width": DEFAULT_SIDEBAR_WIDTH,
        "history_limit": DEFAULT_HISTORY_LIMIT,
```

Add to the validation block in `load_preferences`, following the existing style:

```python
            sidebar_visible = data.get("sidebar_visible")
            if isinstance(sidebar_visible, bool):
                prefs["sidebar_visible"] = sidebar_visible

            sidebar_width = data.get("sidebar_width")
            if (
                isinstance(sidebar_width, int)
                and not isinstance(sidebar_width, bool)
                and MIN_SIDEBAR_WIDTH <= sidebar_width <= MAX_SIDEBAR_WIDTH
            ):
                prefs["sidebar_width"] = sidebar_width

            history_limit = data.get("history_limit")
            if (
                isinstance(history_limit, int)
                and not isinstance(history_limit, bool)
                and MIN_HISTORY_LIMIT <= history_limit <= MAX_HISTORY_LIMIT
            ):
                prefs["history_limit"] = history_limit
```

Extend the `save_preferences` signature with `sidebar_visible: bool | None = None`, `sidebar_width: int | None = None`, `history_limit: int | None = None`, and add the matching guarded assignments before the file is written:

```python
    if sidebar_visible is not None and isinstance(sidebar_visible, bool):
        current["sidebar_visible"] = sidebar_visible
    if (
        sidebar_width is not None
        and isinstance(sidebar_width, int)
        and not isinstance(sidebar_width, bool)
        and MIN_SIDEBAR_WIDTH <= sidebar_width <= MAX_SIDEBAR_WIDTH
    ):
        current["sidebar_width"] = sidebar_width
    if (
        history_limit is not None
        and isinstance(history_limit, int)
        and not isinstance(history_limit, bool)
        and MIN_HISTORY_LIMIT <= history_limit <= MAX_HISTORY_LIMIT
    ):
        current["history_limit"] = history_limit
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_preferences.py -v`
Expected: all existing tests plus 5 new ones pass

- [ ] **Step 5: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add mdprev/preferences.py tests/test_preferences.py
git commit -m "Persist sidebar visibility, width, and history limit"
```

---

### Task 10: The sidebar widget

**Files:**
- Create: `mdprev/sidebar.py`

**Interfaces:**
- Consumes: `git_history.Commit`, `git_history.Cursor`, `git_history.History`, `git_history.history`, `git_history.is_modified`, `git_history.is_tracked`, `git_history.GitHistoryError`.
- Produces: `sidebar.HistorySidebar(on_select: Callable[[Commit | None, str], None])` with methods `load(repo, path: Path, limit: int) -> None`, `refresh_status() -> None`, and `install_css() -> None`. The callback receives `None` for the working copy or a `Commit`, plus the mode string `"rendered"` or `"diff"`.

This task has no automated test: it is a GTK widget requiring a display server, and the repository's existing convention (`tests/test_app.py`) is to leave widget construction to manual verification. Task 14 covers it.

- [ ] **Step 1: Write the widget**

Create `mdprev/sidebar.py`:

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
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import git_history
from .git_history import Commit  # noqa: E402


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


class HistorySidebar(Gtk.Box):
    def __init__(self, on_select: Callable[[Commit | None, str], None]):
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
        self._selected: Commit | None = None
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

        self._rendered_button = Gtk.ToggleButton(label="Rendered")
        self._rendered_button.set_active(True)
        self._diff_button = Gtk.ToggleButton(label="Diff")
        self._diff_button.set_group(self._rendered_button)
        self._rendered_button.connect("toggled", self._mode_toggled)

        box.append(self._rendered_button)
        box.append(self._diff_button)
        return box

    def _mode_toggled(self, button: Gtk.ToggleButton) -> None:
        mode = "rendered" if button.get_active() else "diff"
        if mode == self._mode:
            return
        self._mode = mode
        self._on_select(self._selected, self._mode)

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

        working = self._working_row()
        self._list.append(working)
        for commit in self._commits:
            self._list.append(self._commit_row(commit))
        if self._message is not None:
            self._list.append(self._message_row(self._message))
        if self._truncated:
            self._list.append(
                self._message_row(f"History truncated after {git_history.MAX_SCAN} commits")
            )
        if self._cursor is not None:
            self._list.append(self._action_row("Show more", self._load_more))

        selected_row = working
        if self._selected is not None:
            for row in self._iter_rows():
                if getattr(row, "commit", None) is not None and row.commit.sha == self._selected.sha:
                    selected_row = row
                    break
        self._list.select_row(selected_row)
        self._suppress = False
        if self._repo is not None and self._path is not None:
            self.refresh_status()

    def _iter_rows(self):
        row = self._list.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

    def _working_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = None
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
        return row

    def _commit_row(self, commit: Commit) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = commit
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
        summary.set_ellipsize(3)  # Pango.EllipsizeMode.END
        summary.set_tooltip_text(f"{commit.summary}\n{commit.author}")

        box.append(top)
        box.append(summary)
        row.set_child(box)
        return row

    def _message_row(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.commit = None
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
        row.commit = None
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
        if getattr(row, "action", None) is not None:
            return
        self._selected = getattr(row, "commit", None)
        self._on_select(self._selected, self._mode)

    def select_working_copy(self) -> None:
        """Return to the working copy, as Escape and sidebar-close do."""

        if self._selected is None:
            return
        self._selected = None
        self._rebuild()
        self._on_select(None, self._mode)
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `/usr/bin/python3 -c "import mdprev.sidebar; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Confirm the existing suite still passes**

Run: `/usr/bin/python3 -m pytest`
Expected: all tests pass

- [ ] **Step 4: Run ruff**

Run: `ruff check .`
Expected: no findings

- [ ] **Step 5: Commit**

```bash
git add mdprev/sidebar.py
git commit -m "Add the git history sidebar widget"
```

---

### Task 11: Wiring the sidebar into the window

**Files:**
- Modify: `mdprev/app.py`

**Interfaces:**
- Consumes: `sidebar.HistorySidebar`, `git_history.find_repository`, `render.render_diff`, the new preference keys.
- Produces: `PreviewWindow._revision_commit`, `PreviewWindow._mode`, `PreviewWindow._repo`, and a `load_document` that selects its source from that state. Task 12 makes reload and scroll revision-aware.

- [ ] **Step 1: Add imports and window state**

In `mdprev/app.py`, extend the render import and add the two new modules:

```python
from . import git_history
from .preferences import load_preferences, save_preferences
from .render import (  # noqa: E402
    RenderError,
    error_document,
    read_source,
    render_diff,
    render_markdown,
)
from .sidebar import HistorySidebar  # noqa: E402
```

In `PreviewWindow.__init__`, after the existing preference reads, add:

```python
        self._sidebar_width: int = prefs.get("sidebar_width", 280)
        self._history_limit: int = prefs.get("history_limit", 10)
        self._sidebar_visible: bool = prefs.get("sidebar_visible", False)
        self._repo = git_history.find_repository(path) if git_history.AVAILABLE else None
        # None means the working copy; a Commit means a historic revision.
        self._revision_commit = None
        self._mode = "rendered"
```

- [ ] **Step 2: Build the paned layout**

In `_setup_ui`, replace the final `self.set_child(self._webview)` with:

```python
        self._sidebar = HistorySidebar(self._history_selected)
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_start_child(self._sidebar)
        self._paned.set_end_child(self._webview)
        self._paned.set_resize_start_child(False)
        self._paned.set_shrink_start_child(False)
        self._paned.set_position(self._sidebar_width)
        self.set_child(self._paned)

        if self._repo is not None:
            self._sidebar_button = Gtk.ToggleButton()
            self._sidebar_button.set_icon_name("view-sidebar-start-symbolic")
            self._sidebar_button.set_tooltip_text("Git history (Ctrl+H)")
            self._sidebar_button.set_active(self._sidebar_visible)
            self._sidebar_button.connect("toggled", self._sidebar_toggled)
            header_bar.pack_start(self._sidebar_button)
        else:
            self._sidebar_button = None
            self._sidebar_visible = False
        self._sidebar.set_visible(self._sidebar_visible)
        if self._sidebar_visible:
            self._sidebar.load(self._repo, self.path, self._history_limit)
```

Move `self.set_child(...)` to the end of `_setup_ui` so `header_bar` is still in scope.

- [ ] **Step 3: Add the toggle, selection, and title handlers**

Add these methods to `PreviewWindow`:

```python
    def _sidebar_toggled(self, button: Gtk.ToggleButton) -> None:
        self._set_sidebar_visible(button.get_active())

    def _set_sidebar_visible(self, visible: bool) -> None:
        if self._repo is None:
            return
        self._sidebar_visible = visible
        self._sidebar.set_visible(visible)
        if self._sidebar_button is not None and self._sidebar_button.get_active() != visible:
            self._sidebar_button.set_active(visible)
        if visible:
            # Re-query on open: the .git directory is not watched, so a commit
            # made externally appears the next time the sidebar is opened.
            self._sidebar.load(self._repo, self.path, self._history_limit)
        save_preferences(sidebar_visible=visible)

    def _history_selected(self, commit, mode: str) -> None:
        changed_revision = (
            (commit.sha if commit else None)
            != (self._revision_commit.sha if self._revision_commit else None)
        )
        self._revision_commit = commit
        self._mode = mode
        self._update_titles()
        if changed_revision:
            # A different document: start at the top rather than restoring an
            # offset that means nothing here.
            self.load_document()
        else:
            self.refresh_document()

    def _show_working_copy(self) -> None:
        if self._revision_commit is None:
            return
        self._sidebar.select_working_copy()

    def _update_titles(self) -> None:
        if self._revision_commit is None:
            self.set_title(self.path.name)
            self._subtitle_label.set_visible(False)
            return
        short = self._revision_commit.short_sha
        self.set_title(f"{self.path.name} — {short}")
        self._subtitle_label.set_text(
            f"{short} · {self._revision_commit.when.strftime('%b %-d, %Y')}"
        )
        self._subtitle_label.set_visible(True)
```

- [ ] **Step 4: Give the header bar a title widget that can carry a subtitle**

In `_setup_ui`, immediately after `header_bar = Gtk.HeaderBar()`, add:

```python
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_box.set_valign(Gtk.Align.CENTER)
        self._title_label = Gtk.Label(label=self.path.name)
        self._title_label.add_css_class("title")
        self._subtitle_label = Gtk.Label(label="")
        self._subtitle_label.add_css_class("subtitle")
        self._subtitle_label.set_visible(False)
        title_box.append(self._title_label)
        title_box.append(self._subtitle_label)
        header_bar.set_title_widget(title_box)
```

In `load_document`, replace `self.set_title(self.path.name)` with `self._title_label.set_text(self.path.name)` followed by `self._update_titles()`.

- [ ] **Step 5: Select the document source from revision state**

Replace the body of `load_document` between `def load_document(...)` and `base_uri = ...` with:

```python
        try:
            if self._mode == "diff":
                if self._revision_commit is None:
                    patch = git_history.working_patch(self._repo, self.path)
                else:
                    patch = git_history.patch_for(
                        self._repo, self._revision_commit.sha, self._revision_commit.path
                    )
                html = render_diff(patch, font=self._font, theme=self._theme)
            elif self._revision_commit is None:
                source = read_source(self.path)
                html = render_markdown(
                    source, self.path.parent, font=self._font, theme=self._theme
                )
            else:
                source = git_history.file_at(
                    self._repo, self._revision_commit.sha, self._revision_commit.path
                )
                html = render_markdown(
                    source, self.path.parent, font=self._font, theme=self._theme
                )
        except (RenderError, git_history.GitHistoryError) as exc:
            html = error_document(str(exc), font=self._font, theme=self._theme)
```

- [ ] **Step 6: Register the actions and accelerators**

In `_setup_actions`, add:

```python
        action_toggle_sidebar = Gio.SimpleAction.new("toggle-sidebar", None)
        action_toggle_sidebar.connect(
            "activate", lambda *_: self._set_sidebar_visible(not self._sidebar_visible)
        )
        self.add_action(action_toggle_sidebar)

        action_working_copy = Gio.SimpleAction.new("working-copy", None)
        action_working_copy.connect("activate", lambda *_: self._show_working_copy())
        self.add_action(action_working_copy)
```

In `MdPrevApplication.do_startup`, add:

```python
        self.set_accels_for_action("win.toggle-sidebar", ["<Ctrl>h"])
        self.set_accels_for_action("win.working-copy", ["Escape"])
```

- [ ] **Step 7: Persist the pane width on close**

In `close_request`, inside the existing `try` block, add `sidebar_width` to the `save_preferences` call:

```python
            save_preferences(
                window_width=width,
                window_height=height,
                window_maximized=is_max,
                sidebar_width=self._paned.get_position(),
            )
```

- [ ] **Step 8: Verify the module imports and the suite passes**

Run: `/usr/bin/python3 -c "import mdprev.app; print('ok')" && python3 -m pytest && ruff check .`
Expected: `ok`, all tests pass, no ruff findings

- [ ] **Step 9: Commit**

```bash
git add mdprev/app.py
git commit -m "Host the history sidebar and select the document source by revision"
```

---

### Task 12: Revision-aware reload and scroll

Live reload must never replace a historic revision on screen, and scroll restoration must not carry an offset from one document into another.

**Files:**
- Modify: `mdprev/app.py`

**Interfaces:**
- Consumes: `PreviewWindow._revision_commit`, `HistorySidebar.refresh_status`.
- Produces: no new names. `_reload_timeout` becomes revision-aware.

- [ ] **Step 1: Make the reload path respect the selected revision**

Replace the body of `_reload_timeout` with:

```python
    def _reload_timeout(self) -> bool:
        self._reload_source = 0
        self._monitor_path()  # reconnect after atomic replacement
        if self._revision_commit is not None:
            # A historic revision is on screen.  Saving the file must not swap
            # it out; only the working-copy row's status can change.
            if self._sidebar_visible:
                self._sidebar.refresh_status()
            return GLib.SOURCE_REMOVE
        # WebKit's page JavaScript remains disabled.  Code explicitly evaluated
        # by the host application lets us preserve the reading position.  The
        # setting is enabled only around this trusted expression; rendered HTML
        # is sanitized and contains no scripts.
        script = "window.scrollY"
        self._webview.get_settings().set_enable_javascript(True)
        self._webview.evaluate_javascript(
            script, len(script), None, None, None, self._scroll_captured, None
        )
        return GLib.SOURCE_REMOVE
```

- [ ] **Step 2: Refresh the status dot when a diff of the working copy is on screen**

Still inside `_reload_timeout`, the working-copy branch also needs the dot updated, because saving changes whether the file differs from HEAD. Insert immediately before the `script = "window.scrollY"` line:

```python
        if self._sidebar_visible:
            self._sidebar.refresh_status()
```

- [ ] **Step 3: Verify manually that font and theme changes keep the revision**

`refresh_document` captures the scroll offset and calls `load_document` through `_scroll_captured`, and `load_document` now reads `self._revision_commit`. No change is required — confirm by reading the two methods that a font change while a commit is selected re-renders that commit rather than the live file.

- [ ] **Step 4: Verify the suite still passes**

Run: `/usr/bin/python3 -m pytest && ruff check .`
Expected: all tests pass, no ruff findings

- [ ] **Step 5: Commit**

```bash
git add mdprev/app.py
git commit -m "Keep live reload from replacing a historic revision"
```

---

### Task 13: Documentation

**Files:**
- Modify: `FEATURE_REQUIREMENTS.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Add the runtime dependency to FEATURE_REQUIREMENTS.md §2**

After the MVP 2 package block, add:

```markdown
MVP 4 additionally requires:

```text
python3-pygit2
```

MdPrev runs without it; the git history sidebar is simply unavailable.
```

- [ ] **Step 2: Insert MVP 4 as a new §6 in FEATURE_REQUIREMENTS.md**

Place it after §5 (MVP 3) and before the deferred-features section:

```markdown
## 6. MVP 4: git history sidebar

### 6.1 Required behavior

- When the open document is inside a local git repository, offer a sidebar
  listing the commits that touch that file, newest first.
- Show a pinned "Working copy" entry above the commits, selected by default,
  carrying a red dot and "Modified" when the file differs from HEAD (staged or
  unstaged) and a green dot and "Unchanged" otherwise.
- Follow renames, so history continues past a rename.
- Render a selected revision either as formatted Markdown or as the
  highlighted unified diff of its Markdown source against the previous
  version.
- Bound each query by a configurable commit limit (default 10) and by a
  scanned-revision ceiling, and offer paging beyond the limit.
- Treat historic content as untrusted: sanitize it exactly as the live file is
  sanitized, and never render raw HTML or execute JavaScript.
- Never write the source file and never write the repository.
- Suppress live reload while a historic revision is displayed, updating only
  the working-copy status indicator.
- Persist sidebar visibility and width across sessions.
- Behave exactly as MVP 3 did when pygit2 is not installed.

### 6.2 MVP 4 acceptance criteria

1. A document inside a repository shows a sidebar button; one outside a
   repository does not.
2. The sidebar lists commits touching the file, honoring the configured limit,
   with paging beyond it.
3. A renamed file's history continues past the rename.
4. Selecting a commit renders that version with current font, theme, and
   highlighting settings.
5. The diff view is legible in Light, Dark, Sepia, and System themes.
6. The working-copy indicator reflects staged and unstaged differences.
7. Saving the file while a commit is selected leaves the preview untouched and
   updates the indicator.
8. Selecting the working copy restores live reload.
9. Sidebar visibility and width persist across sessions.
10. The source file and the repository are never written.
11. MVP 1, MVP 2, and MVP 3 acceptance criteria continue to pass.
12. With python3-pygit2 absent, the application behaves as it did before MVP 4.
```

Renumber the former §6 (deferred features) to §7 and the former §7 (non-goals) to §8.

- [ ] **Step 3: Narrow the deferred entry**

In the renumbered §7, replace the line `- Generated table of contents/sidebar` with:

```markdown
- Generated table of contents
```

A sidebar is what MVP 4 adds; a generated table of contents remains deferred.

Also add these lines to §7, recording the decisions this design settled:

```markdown
- Per-file preferences or per-document state restoration
- Repository mutation of any kind: checkout, restore, stash, commit
- Remote git information: fetch, upstream tracking, ahead/behind
- Branch, tag, or ref browsing; blame; side-by-side or rendered-prose diffs
```

- [ ] **Step 4: Update AGENTS.md**

In "Supported environment", after the Pygments line, add:

```markdown
- `python3-pygit2` only in MVP 4, and only for the git history sidebar
```

In "Product constraints", add:

```markdown
- The git integration is strictly read-only. Never check out, restore, stash,
  or commit, and never write to the repository.
- All settings are global. Do not add per-file preferences.
```

In "Scope discipline", add `per-file preferences` and `git write operations` to the list of things not to implement.

- [ ] **Step 5: Update README.md**

Change the install command to:

```sh
sudo apt install cmark-gfm gir1.2-gtk-4.0 gir1.2-webkit-6.0 python3-pygments python3-pygit2
```

Add to the "Behavior" section:

```markdown
When the open document is inside a git repository, a sidebar button appears in
the header bar (`Ctrl`+`H`). The sidebar lists the commits that touch the file
and pins a "Working copy" entry on top, marked with a red dot when the file has
uncommitted changes and a green dot when it matches HEAD. Selecting a commit
shows that version of the document; the Rendered/Diff switch alternates between
the formatted document and the unified diff of its Markdown source. Renames are
followed. Live reload pauses while a historic revision is shown and resumes on
returning to the working copy.

Two limitations are worth knowing. The commit list refreshes when the sidebar is
opened, so a commit created elsewhere while the window is open appears the next
time it is opened. Relative images in a historic version resolve against the
current working tree, so an image deleted since that commit will not load.

`python3-pygit2` is optional. Without it MdPrev works exactly as before and the
sidebar is unavailable.
```

- [ ] **Step 6: Verify the suite still passes**

Run: `/usr/bin/python3 -m pytest && ruff check .`
Expected: all tests pass, no ruff findings

- [ ] **Step 7: Commit**

```bash
git add FEATURE_REQUIREMENTS.md AGENTS.md README.md
git commit -m "Document the git history sidebar as MVP 4"
```

---

### Task 14: Manual GNOME verification

`AGENTS.md` forbids claiming GNOME integration works without testing it. These checks require a display server; if one is unavailable, state that limitation in the handoff rather than marking the steps done.

**Files:** none modified.

- [ ] **Step 1: Prepare fixtures**

```bash
mkdir -p /tmp/mdprev-check/repo && cd /tmp/mdprev-check/repo && git init -q
printf '# Title\n\nFirst version.\n' > "doc with spaces ünïcode.md"
git add . && git -c user.email=t@example.com -c user.name=Test commit -qm "First"
printf '# Title\n\nSecond version.\n\n```python\nprint("hi")\n```\n' > "doc with spaces ünïcode.md"
git add . && git -c user.email=t@example.com -c user.name=Test commit -qm "Second"
mkdir -p /tmp/mdprev-check/loose
printf '# Outside git\n' > /tmp/mdprev-check/loose/plain.md
```

- [ ] **Step 2: Run the checks**

Launch with `python3 -m mdprev "<file>"` from the repository root for each case.

- [ ] The repository document shows the sidebar button; `/tmp/mdprev-check/loose/plain.md` shows none.
- [ ] The button and `Ctrl`+`H` both toggle the sidebar; the width drags and the reading column absorbs window resizing.
- [ ] Closing and reopening the application restores sidebar visibility and width.
- [ ] Selecting "Second" renders that version; the header bar shows the short SHA and date and the window title shows the SHA.
- [ ] The Diff switch shows the highlighted patch; check it in Light, Dark, Sepia, and System themes and confirm the code block scrolls horizontally rather than the page.
- [ ] Selecting "First" renders the earlier version; the fenced Python block is absent there.
- [ ] With a commit selected, edit and save the file in another editor: the preview does not change, and the working-copy dot turns red with the label "Modified".
- [ ] Select "Working copy": the edit appears and live reload resumes on the next save.
- [ ] `git add` the file without committing: the dot stays red.
- [ ] `git checkout -- .`: the dot returns to green and "Unchanged".
- [ ] `Escape` returns to the working copy from a selected commit.
- [ ] Closing the sidebar while a commit is selected keeps that revision on screen, with the SHA still in the title.
- [ ] Open from GNOME Files via "Open With" and confirm the sidebar works there too.
- [ ] Change font and theme while a commit is selected: the commit re-renders, not the live file.
- [ ] Uninstall pygit2 (`sudo apt remove python3-pygit2`), relaunch, and confirm no sidebar button appears and the application behaves as before. Reinstall afterwards.

- [ ] **Step 3: Record the result**

Note in the handoff which checks passed and any that could not be run.

---

## Self-Review

**Spec coverage.** §3 dependency → Task 1. §3.1 rationale → no code. §4 module table → Tasks 1, 8, 10, 11. §5.1 interface → Tasks 1–7. §5.2 bounding → Task 3. §5.3 path following → Tasks 3, 4. §5.4 status → Task 7. §5.5 error conversion → Tasks 2, 5, 6, 7. §6.1 historic render → Task 11 step 5. §6.2 diff render → Task 8. §7.1 layout → Task 11 steps 2, 3. §7.2 list and dots → Task 10. §7.3 controls → Task 11 steps 3, 4, 6. §7.4 reload → Task 12. §7.5 empty states → Task 10 `load`/`_fetch`, Task 11 step 5. §8 limitations → Task 13 README. §9 preferences → Task 9. §10.1 automated tests → Tasks 1–9. §10.2 manual → Task 14. §11 docs → Task 13. §12 acceptance → Task 14.

**Placeholder scan.** No TBD, TODO, "handle edge cases", or "similar to Task N". Every code step carries the code. Task 10 states plainly why it has no unit test rather than implying one exists.

**Type consistency.** `file_at(repo, sha, path)` and `patch_for(repo, sha, path)` take repo-relative strings throughout, sourced from `Commit.path`; `history`, `working_patch`, `is_modified`, `is_tracked`, and `find_repository` take on-disk `Path` objects. `Cursor` is used consistently in Tasks 3, 4, and 10. The sidebar callback is `(Commit | None, str)` in Tasks 10 and 11. `render_diff` keeps the `(patch, font, theme)` signature in Tasks 8 and 11. `_entry` returns a `Blob | None` in Tasks 3, 5, and 6.
