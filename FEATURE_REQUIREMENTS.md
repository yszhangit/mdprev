# MdPrev Feature Requirements

Status: approved implementation plan  
Target: Ubuntu 26.04 LTS (Resolute), GNOME 50, Wayland; macOS 26 on Apple
silicon (planned, see section 10)  
Product type: local, read-only Markdown previewer

## 1. Product goal

MdPrev lets a user open a Markdown file from GNOME Files or the terminal and
read a clean rendered preview that updates when the source file is saved.

The product is intentionally narrow. It is not a Markdown editor, document
manager, or browser. It supports exactly two platforms, Ubuntu GNOME and macOS,
each through a native front end over one shared core (section 10); no other
platform is in scope.

## 2. Runtime architecture

The code is split into a toolkit-neutral core and one front end per platform:

- `mdprev/core`: reading, rendering, sanitizing, highlighting, git history,
  comparison, preferences, navigation policy, and window/sidebar state. It
  never imports a GUI toolkit, and a test enforces that.
- `mdprev/gtk`: the Linux front end described below.
- `mdprev/macos`: the macOS front end (section 10).

The Linux runtime stack is:

- Python 3
- GTK 4 via PyGObject for the application and window
- WebKitGTK 6.0 for displaying application-generated HTML and CSS
- `cmark-gfm` for CommonMark and GitHub Flavored Markdown rendering
- `Gio.FileMonitor` for filesystem change notifications
- Pygments in MVP 2 only
- `pygit2` in MVP 4 only, and optional even there: it powers the git history
  sidebar, and MdPrev runs without it exactly as it did before MVP 4

Expected MVP 1 Ubuntu packages:

```text
python3
python3-gi
gir1.2-gtk-4.0
gir1.2-webkit-6.0
cmark-gfm
```

MVP 2 additionally requires:

```text
python3-pygments
```

MVP 4 additionally requires:

```text
python3-pygit2
```

MdPrev runs without it; the git history sidebar is simply unavailable.

## 3. MVP 1: basic Markdown display

### 3.1 Opening documents

The application must:

- Accept one or more local Markdown files through GTK/GIO open requests.
- Support invocation as `mdprev FILE`.
- Register as a handler for `.md` and `.markdown` files in GNOME.
- Appear in the Files “Open With” application list.
- Allow the user to make it the default Markdown handler.
- Open each requested document in its own window.
- Reuse the running `Gtk.Application` instance when GNOME sends later open
  requests.

The application does not control whether Files uses single-click or
double-click activation; it participates through the standard MIME association.

### 3.2 Markdown syntax

MVP 1 must render:

- Headings
- Paragraphs, soft breaks, and hard breaks
- Emphasis and strong emphasis
- Ordered, unordered, and nested lists
- Block quotes
- Inline code
- Indented and fenced code blocks
- Links and reference links
- Local images
- Horizontal rules
- Backslash escapes and character entities
- GFM tables
- GFM task lists with non-interactive checkboxes
- GFM strikethrough
- GFM extended autolinks

Fenced code blocks must be legible but do not receive syntax highlighting in
MVP 1.

### 3.3 Preview behavior

The preview must:

- Render a document immediately after it is opened.
- Reload automatically after the source file is saved.
- Debounce duplicate filesystem events.
- Continue monitoring after an editor atomically replaces the source file.
- Preserve the approximate vertical scroll position during automatic reload.
- Resolve relative image paths from the Markdown document's directory.
- Scale oversized images to fit the content width.
- Give wide tables and code blocks usable horizontal overflow behavior.
- Navigate valid in-document heading anchors.
- Open allowed external links with the system default browser.
- Follow the GNOME light/dark preference without requiring an app setting.
- Display an informative non-crashing error for missing, deleted, unreadable,
  invalidly encoded, or unrenderable files.
- Use the document filename in the window title.

### 3.4 Safety

Markdown files are untrusted input. MVP 1 must:

- Keep WebKit JavaScript disabled.
- Leave raw embedded HTML disabled in `cmark-gfm`.
- Prevent `javascript:`, `data:`, and other unapproved link schemes from being
  launched.
- Prevent remote HTTP/HTTPS images and other remote subresources from loading.
- Permit only the local resources required for document-relative images.
- Escape application-generated error content.
- Avoid shell execution and shell-expanded filenames.
- Never write to the source document.

The link schemes allowed for external launching in MVP 1 are `http`, `https`,
and `mailto`. Local Markdown links may open another document through the
application; other local file types should be handed to the desktop only if the
behavior is explicitly implemented and tested.

### 3.5 Desktop installation

The repository must provide:

- A launcher/entry point named `mdprev`.
- A valid `.desktop` entry with a `%f` argument.
- MIME declarations for `text/markdown` and `text/x-markdown`.
- An SVG application icon.
- A user-local installation script.
- A matching uninstall script.
- Instructions for installing required Ubuntu packages.
- An explicit option or documented command for setting MdPrev as the default
  Markdown application.

Uninstallation must remove only files installed by MdPrev. Changing the default
association must be reversible without overwriting unrelated MIME preferences.

### 3.6 MVP 1 acceptance criteria

MVP 1 is complete when, on Ubuntu 26.04 GNOME:

1. A Markdown file can be opened from the terminal and Files.
2. The complete MVP 1 syntax fixture renders correctly.
3. Saving the file refreshes the preview without reopening the window.
4. Scroll position remains reasonably stable after reload.
5. A relative local image renders and a remote image does not load.
6. An external HTTPS link opens in the default browser after user activation.
7. Raw HTML and JavaScript do not execute.
8. Light/dark appearance tracks GNOME.
9. Installation and uninstallation work at user scope.
10. Automated rendering and safety tests pass.

## 4. MVP 2: selected-language syntax highlighting

MVP 2 begins only after MVP 1 satisfies its acceptance criteria.

### 4.1 Required behavior

- Highlight fenced code blocks when their language tag is supported.
- Perform highlighting before loading HTML into WebKit.
- Keep JavaScript disabled.
- Preserve the original code text exactly.
- Render missing, empty, or unknown language tags as plain code.
- Provide readable palettes for both light and dark GNOME appearances.
- Keep live reload and scroll preservation working.
- Treat language tags as untrusted input and never use them in shell commands.

### 4.2 Initially supported language tags

- Bash and shell
- Python
- JavaScript
- TypeScript
- JSON
- YAML
- HTML
- CSS
- C
- C++
- Rust
- Go
- SQL
- Markdown
- Diff

Common aliases such as `sh`, `bash`, `py`, `js`, `ts`, `yml`, `html`, `cpp`,
`rs`, and `md` should map to a controlled internal lexer allowlist.

### 4.3 MVP 2 acceptance criteria

1. Every supported language has a test fixture and renders highlighted output.
2. Aliases select the expected lexer.
3. Unknown and malicious language strings fall back to plain escaped code.
4. Highlighted output is readable in light and dark appearances.
5. Code content cannot inject HTML or script behavior.
6. MVP 1 acceptance criteria continue to pass.

## 5. MVP 3: reader display controls (fonts and themes)

### 5.1 Required behavior

- Allow the user to adjust font family from preinstalled Ubuntu GNOME system fonts.
  Supported font families:
  - System default (`system-ui, sans-serif`)
  - Ubuntu / Cantarell (Sans)
  - Serif (e.g. `DejaVu Serif, serif`)
  - Monospace (e.g. `Ubuntu Sans Mono, DejaVu Sans Mono, monospace`)
- Increase, decrease, and reset text zoom/font size (e.g. via keyboard shortcuts
  `Ctrl`+`+`, `Ctrl`+`-`, `Ctrl`+`0` and/or headerbar reader controls).
- Switch document color themes:
  - System (tracks GNOME light/dark preference automatically)
  - Light
  - Dark
  - Sepia (warm paper-like reader theme)
- Preserve reader preferences (font family, color theme, zoom level/font size, and window geometry) across application sessions and reloads in XDG user config.
- Preserve vertical reading position during font or theme adjustments.
- Maintain no-JavaScript and strict HTML sanitization constraints.

### 5.2 MVP 3 acceptance criteria

1. Changing font selection updates rendered document typography cleanly.
2. Increasing, decreasing, and resetting font size changes magnification as expected.
3. Theme switcher cleanly switches between System, Light, Dark, and Sepia palettes.
4. All syntax highlighting remains legible across Light, Dark, and Sepia themes.
5. Auto-reload and scroll preservation continue to work under custom font/theme settings.
6. MVP 1 and MVP 2 acceptance criteria continue to pass.

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

## 7a. MVP 6: heading outline

### 7a.1 Required behavior

- A left-hand outline pane lists the document's headings (H1 to H6) as a
  collapsible tree, nested by level; a skipped level nests under the nearest
  higher heading.
- Headings above level 2 start expanded, so H1 and H2 are visible by default.
  The level is the global `outline_expand_level` preference (1 to 6, default
  2); it has no control yet.
- Expanding or collapsing a heading is kept across reloads of the document,
  but is not saved between sessions (no per-file state).
- Choosing a heading scrolls the preview to it. Anchors come from the
  sanitized, displayed HTML, so every entry is a real target.
- The outline follows the displayed revision in the Rendered view. The Diff
  and Side by side views have no document headings; the pane says so.
- The pane is toggled from the header bar/toolbar and a shortcut; its
  visibility and width are global preferences. The git history pane moves to
  the right so both can be open at once.

### 7a.2 MVP 6 acceptance criteria

1. A document's H1 and H2 headings are listed, nested, on opening the pane.
2. Expanding a heading reveals its subheadings; collapsing hides them.
3. Choosing a heading scrolls the preview so that heading is at the top.
4. Saving the document updates the outline and keeps expanded headings open.
5. Headings in code blocks are not listed.
6. The outline and history panes can be open together, outline on the left.

## 8. Deferred features

The following are outside MVP 1 through MVP 6:

- Markdown editing or split editor/preview
- Tabs, session restoration, and recent-file management
- Preferences dialog window or complex settings sync
- Raw HTML rendering
- JavaScript
- Remote images or embedded remote content
- Mermaid, PlantUML, or other diagrams
- MathJax, KaTeX, or LaTeX math
- Footnotes
- Emoji shortcodes
- YAML front matter presentation
- A table of contents generated inside the document (the outline pane is MVP 6)
- Wiki links and file includes
- Custom arbitrary user CSS upload
- Interactive task-list editing
- Audio and video embeds
- Printing or PDF export
- Browser navigation
- Plugins
- Packaging for non-Ubuntu Linux distributions
- Windows support
- Per-file preferences or per-document state restoration
- Repository mutation of any kind: checkout, restore, stash, commit
- Remote git information: fetch, upstream tracking, ahead/behind
- Branch, tag, or ref browsing; blame; rendered-prose diffs

Deferred features require an explicit requirements change before implementation.

## 9. Non-goals and quality priorities

When tradeoffs arise, prioritize in this order:

1. Safe handling of untrusted Markdown
2. Correct and predictable preview behavior
3. Native integration on each supported platform (Ubuntu GNOME, macOS)
4. Low dependency and maintenance cost
5. Startup and reload performance
6. Additional features

The application should remain small enough for a new GUI developer to
understand and maintain.

## 10. macOS support and platform parity

MdPrev also runs on macOS 26 on Apple silicon (Intel Macs and older macOS
releases are out of scope). The macOS front end is native: AppKit and
`WKWebView` through PyObjC, over the same `mdprev/core` as Linux. Every product
requirement in sections 3 to 7 applies on macOS, with the platform
equivalents below; the safety rules in section 3.4 apply unchanged.

### 10.1 Platform equivalents

| Linux (GNOME) | macOS |
|---|---|
| Files "Open With", `.desktop` entry, MIME types | Finder "Open With", `CFBundleDocumentTypes` for `net.daringfireball.markdown` |
| `xdg-mime default …` | Finder Get Info, "Open with", "Change All…" |
| `Gio.FileMonitor` | kqueue (or FSEvents) with the same debounce and replacement recovery |
| WebKitGTK 6.0, HTML loaded from a string | `WKWebView`, page JavaScript disabled; HTML loaded from a per-window temporary file, because `WKWebView` grants local image access only to file loads |
| Header bar and display-options popover | View menu (Zoom, Font, Theme) and a History toolbar button |
| GNOME light/dark preference | macOS appearance (light/dark) |
| `Ctrl`+`+`/`-`/`0` zoom | `Cmd`+`=`/`-`/`0` |
| `F9` outline (the GNOME sidebar key) | `Ctrl`+`Cmd`+`S` (the macOS sidebar key) |
| `Ctrl`+`H` history | `Ctrl`+`Cmd`+`H` (`Cmd`+`H` hides the app) |
| `Escape` (no menu item) | `Escape`, also View > Back to Working Copy |
| `~/.config/mdprev/preferences.json` | `~/Library/Application Support/MdPrev/preferences.json` |
| Ubuntu packages, `install.sh` | `MdPrev.app` built with py2app; `cmark-gfm` from Homebrew |

### 10.2 Parity rule

New behavior is implemented in `mdprev/core` first, with headless tests, and
each front end only connects widgets to it. A feature is complete when both
front ends provide it, or when the table below records the gap.

| Feature | Linux | macOS |
|---|---|---|
| MVP 1: display, live reload, safety | Done | Done |
| MVP 1: installation, Finder / "Open With" | Done | Planned (needs the app bundle) |
| MVP 2: syntax highlighting | Done | Done |
| MVP 3: font, theme, zoom | Done | Done |
| MVP 4: git history sidebar | Done | Done |
| MVP 5: revision comparison | Done | Done |
| MVP 6: heading outline | Done (verify on Ubuntu) | Done |

### 10.3 macOS acceptance criteria

The macOS front end is complete when, on macOS 26 on Apple silicon, the
acceptance criteria of MVP 1 to MVP 5 pass with the equivalents in 10.1, and:

1. A Markdown file opens from Finder (double-click and "Open With"), the Dock,
   and `open -a MdPrev FILE`.
2. `cmark-gfm` is found when the app is launched from Finder, whose PATH
   excludes Homebrew.
3. The core test suite passes on macOS; the GTK tests are skipped there.
