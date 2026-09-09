# AGENTS.md

## Project purpose

MdPrev is a small, read-only Markdown preview application for Ubuntu 26.04 LTS
GNOME. Keep the application focused, native-looking, and easy to install from
Ubuntu packages. Do not add cross-platform abstractions.

Read `FEATURE_REQUIREMENTS.md` before changing application behavior. Implement
MVP 1 before starting MVP 2.

## Supported environment

- Ubuntu 26.04 LTS (Resolute)
- GNOME 50 on Wayland
- System packages rather than vendored dependencies
- Python 3 with PyGObject
- GTK 4
- WebKitGTK 6.0 (the GTK 4 API; do not use the GTK 3 `WebKit2 4.1` API)
- `cmark-gfm` for Markdown-to-HTML conversion
- `python3-pygments` only in MVP 2
- `python3-pygit2` only in MVP 4, and only for the git history sidebar

Do not introduce Qt, Electron, Tauri, Node.js, a JavaScript framework, a Python
virtual environment, or a bundled web server.

## Product constraints

- The application is a viewer, not an editor.
- Open one document per window.
- Opening another document through GNOME should create/present the appropriate
  window in the existing `Gtk.Application` process.
- The interface should contain only what is needed to read the document.
- Prefer GNOME/GTK behavior and system settings over custom controls.
- JavaScript must remain disabled.
- Raw HTML from Markdown must not execute or render in MVP 1 or MVP 2.
- Remote resources must not load automatically.
- Local relative images may load from the opened document's directory.
- External web links must open in the user's default browser.
- Never modify the Markdown file.
- The git integration is strictly read-only. Never check out, restore, stash,
  or commit, and never write to the repository.
- All settings are global. Do not add per-file preferences.

## Implementation guidance

- Use `Gtk.Application` with `Gio.ApplicationFlags.HANDLES_OPEN` for file-open
  requests from the command line and Files (Nautilus).
- Use `Gio.FileMonitor` for live reload and debounce bursts of filesystem
  events. Editors commonly save by replacing or renaming a file, so monitoring
  must recover from replacement.
- Invoke `cmark-gfm` without a shell. Pass arguments as an array and send source
  through standard input. Enable the GFM table, task-list, strikethrough, and
  autolink extensions explicitly.
- Generate a complete HTML document using application-owned CSS. Treat all
  Markdown input as untrusted.
- Preserve the approximate vertical reading position across automatic reloads.
- Escape all application-generated error text before placing it in HTML.
- Keep rendering logic separate from GTK window/application code so it can be
  unit tested without a display server.
- Avoid broad exception handling. Convert expected I/O, decoding, parser, and
  subprocess failures into concise user-facing errors and useful diagnostics.
- Use UTF-8. Report invalid input cleanly; do not silently rewrite it.
- Use `pathlib` for filesystem paths.
- Do not use shell interpolation for filenames or URLs.

## Desktop integration

- Provide a freedesktop `.desktop` entry using `%f`, not a hand-built argument
  string.
- Advertise `text/markdown` and `text/x-markdown`.
- Provide an SVG application icon.
- Provide user-local `install.sh` and `uninstall.sh` scripts.
- Installation should target the applicable XDG user directories and must not
  require `sudo` except for installing missing Ubuntu packages.
- Setting MdPrev as the default Markdown handler must be explicit and reversible.
- Keep the application ID and desktop-file basename identical. Use
  `io.github.yzhang.mdprev` provisionally unless the maintainer changes it
  before release.

## Scope discipline

Do not implement deferred features merely because a library makes them easy.
In particular, do not add editing, tabs, preferences, raw HTML, remote images,
JavaScript, diagrams, math rendering, PDF export, custom CSS, plugins,
per-file preferences, or git write operations.

MVP 2 adds syntax highlighting only after MVP 1 acceptance criteria pass. It
must use Pygments on the Python side, allow only the documented language set,
and render unknown languages as plain code.

## Tests and verification

For every behavior change:

1. Run unit tests for rendering, URL decisions, and path handling.
2. Run syntax/static checks configured by the repository.
3. Launch the application on Ubuntu 26.04 when display integration changes.
4. Test a filename containing spaces and non-ASCII characters.
5. Test an untrusted document containing raw HTML, JavaScript URLs, remote
   images, and malformed Markdown.
6. Test a save performed by in-place writing and one performed by atomic file
   replacement.

Do not claim GNOME integration is verified unless opening from Files and the
MIME association have actually been tested. If GUI verification is unavailable,
state that limitation in the handoff.

## Change style

- Prefer small modules and straightforward code over frameworks or elaborate
  abstractions.
- Keep dependencies minimal and document every runtime dependency.
- Update `FEATURE_REQUIREMENTS.md` when an agreed product requirement changes.
- Preserve unrelated user changes in the worktree.
- Include tests with fixes where practical.
