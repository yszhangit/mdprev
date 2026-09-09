# MdPrev Feature Requirements

Status: approved implementation plan  
Target: Ubuntu 26.04 LTS (Resolute), GNOME 50, Wayland  
Product type: local, read-only Markdown previewer

## 1. Product goal

MdPrev lets a user open a Markdown file from GNOME Files or the terminal and
read a clean rendered preview that updates when the source file is saved.

The product is intentionally narrow. It is not a Markdown editor, document
manager, browser, or cross-platform application.

## 2. Runtime architecture

The planned runtime stack is:

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

## 7. Deferred features

The following are outside MVP 1, MVP 2, MVP 3, and MVP 4:

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
- Generated table of contents
- Wiki links and file includes
- Custom arbitrary user CSS upload
- Interactive task-list editing
- Audio and video embeds
- Printing or PDF export
- Browser navigation
- Plugins
- Packaging for non-Ubuntu Linux distributions
- Windows or macOS support
- Per-file preferences or per-document state restoration
- Repository mutation of any kind: checkout, restore, stash, commit
- Remote git information: fetch, upstream tracking, ahead/behind
- Branch, tag, or ref browsing; blame; side-by-side or rendered-prose diffs

Deferred features require an explicit requirements change before implementation.

## 8. Non-goals and quality priorities

When tradeoffs arise, prioritize in this order:

1. Safe handling of untrusted Markdown
2. Correct and predictable preview behavior
3. Native Ubuntu GNOME integration
4. Low dependency and maintenance cost
5. Startup and reload performance
6. Additional features

The application should remain small enough for a new GUI developer to
understand and maintain.

