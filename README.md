# MdPrev

MdPrev is a small, read-only Markdown previewer for Ubuntu 26.04 GNOME. It
uses the system GTK 4, WebKitGTK 6.0, and cmark-gfm packages. A native macOS
version (AppKit and WKWebView over the same core) is in progress; see
[macOS development](#macos-development).

## Install

Install the Ubuntu runtime packages:

```sh
sudo apt install cmark-gfm gir1.2-gtk-4.0 gir1.2-webkit-6.0 python3-pygments python3-pygit2
```

Then install MdPrev for the current user:

```sh
packaging/linux/install.sh
```

Open a Markdown file from Files' **Open With** menu, or run:

```sh
mdprev path/to/document.md
```

To explicitly make it the default Markdown handler:

```sh
xdg-mime default io.github.yszhangit.mdprev.desktop text/markdown
xdg-mime default io.github.yszhangit.mdprev.desktop text/x-markdown
```

The previous default can be restored with `xdg-mime default
<previous-desktop-file> <mime-type>`. Uninstalling leaves MIME defaults
untouched so unrelated preferences are not overwritten.

## Behavior

CommonMark and GFM tables, task lists, strikethrough, and autolinks are
supported. The preview reloads after saves and permits document-relative local
images. JavaScript, raw HTML, remote images, and unsafe links are disabled.
Selected fenced-code languages are highlighted by Pygments using light and
dark palettes; missing or unknown language tags remain plain code.

Reader display options (font family and color theme) can be changed via the
header bar menu. Zoom level can be adjusted with `Ctrl`+`+` (zoom in),
`Ctrl`+`-` (zoom out), and `Ctrl`+`0` (reset zoom). Reader preferences (font family, theme,
zoom level, and window size) are saved globally across sessions. The source file is never modified.

When the open document is inside a git repository, a sidebar button appears in
the header bar (`Ctrl`+`H`). The sidebar lists the commits that touch the file
and pins a "Working copy" entry on top, marked with a red dot when the file has
uncommitted changes and a green dot when it matches HEAD. Selecting a commit shows that version of the document; the Rendered / Diff /
Side by side switch alternates between the formatted document, the unified
diff of its Markdown source, and the same diff in two columns. Each entry shows
the file's size, line count, and word count at that version.

To compare any two versions, click the pin on one entry to make it the base,
then select another; both diff views then show base → selected, headed by the
size, line, and word changes between them. Pins appear once there are two
versions to compare — two commits, or a commit plus uncommitted changes.

Renames are followed. Live reload pauses while a historic revision is shown and
resumes on returning to the working copy.

`Escape` first clears a pin, then returns to the working copy at any time a
commit is selected, whether or not the sidebar is open — this is the only way
back once the sidebar is closed, so it is worth knowing even though there is no
menu item or button for it. Live reload stays on while the working copy is
either side of a comparison.

Two limitations are worth knowing. The commit list refreshes when the sidebar is
opened, so a commit created elsewhere while the window is open appears the next
time it is opened. Relative images in a historic version resolve against the
current working tree, so an image deleted since that commit will not load.

`python3-pygit2` is optional. Without it MdPrev works exactly as before and the
sidebar is unavailable.

## Uninstall

```sh
packaging/linux/uninstall.sh
```

## macOS development

The macOS front end is not usable yet, but the shared core and its tests run
on macOS 26 on Apple silicon:

```sh
brew install cmark-gfm
/opt/homebrew/bin/python3.12 -m venv venv
venv/bin/pip install -r packaging/macos/requirements.txt
venv/bin/pytest
```

The GTK tests are skipped on macOS.

## License

MdPrev is available under the [MIT License](LICENSE).
