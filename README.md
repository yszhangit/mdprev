# View Markdown

View Markdown is a small, read-only Markdown previewer for macOS and Ubuntu
GNOME. Open a `.md` file from Finder or Files and read a clean rendered page
that refreshes whenever the file is saved.

- CommonMark and GitHub Flavored Markdown: tables, task lists, strikethrough,
  and autolinks, with syntax highlighting for common languages.
- An outline pane listing the document's headings as a collapsible tree.
- A git history pane: read any earlier version of the file, or compare two
  versions as a unified or side-by-side diff.
- Light, dark, and sepia themes, a choice of fonts, and zoom.
- Safe with untrusted files: JavaScript, raw HTML, remote images, and unsafe
  links are disabled. The source file is never modified.

It is a viewer only. There is no editing, and each document opens in its own
window.

## Install

Both installs are for the current user only and need no `sudo`, apart from
installing the system packages.

### macOS

Requires macOS 26 on Apple silicon and [Homebrew](https://brew.sh).

```sh
brew install cmark-gfm python@3.12
git clone https://github.com/fixed-42/view-markdown.git
cd view-markdown
packaging/macos/install.sh
```

The script builds `View Markdown.app` on your Mac and installs it in
`~/Applications`. The first run downloads the Python dependencies into a
`venv/` folder inside the checkout.

To open a document, right-click a Markdown file in Finder and choose
**Open With > View Markdown**, or run:

```sh
open -a "View Markdown" path/to/document.md
```

To make it the default for Markdown files, select one in Finder, choose
**File > Get Info**, pick View Markdown under **Open with**, and click
**Change All**. Choose another application the same way to undo it.

After updating the checkout (`git pull`), run `packaging/macos/install.sh`
again to rebuild the app.

### Ubuntu

Requires Ubuntu 26.04 with GNOME.

```sh
sudo apt install git cmark-gfm python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0 python3-pygments python3-pygit2
git clone https://github.com/fixed-42/view-markdown.git
cd view-markdown
packaging/linux/install.sh
```

To open a document, right-click a Markdown file in Files and choose
**Open With > View Markdown**, or run:

```sh
view-markdown path/to/document.md
```

If the `view-markdown` command is not found, log out and back in: Ubuntu adds
`~/.local/bin` to `PATH` at login, once the folder exists. Opening from Files
works straight away.

After updating the checkout (`git pull`), run `packaging/linux/install.sh`
again.

To make it the default Markdown handler:

```sh
xdg-mime default io.github.fixed-42.view-markdown.desktop text/markdown
xdg-mime default io.github.fixed-42.view-markdown.desktop text/x-markdown
```

The previous default can be restored with `xdg-mime default
<previous-desktop-file> <mime-type>`.

`python3-pygit2` is optional. Without it View Markdown works the same, minus
the git history pane.

### Uninstall

```sh
packaging/macos/uninstall.sh    # macOS
packaging/linux/uninstall.sh    # Ubuntu
```

Uninstalling removes only what the install script added. Your preferences and
any default-application choice are left untouched.

## Using it

| Action | macOS | Ubuntu |
|---|---|---|
| Open another file | `Cmd`+`O` | Files, or `view-markdown FILE` |
| Zoom in / out / reset | `Cmd`+`=` / `Cmd`+`-` / `Cmd`+`0` | `Ctrl`+`+` / `Ctrl`+`-` / `Ctrl`+`0` |
| Font and theme | **View** menu | Header bar menu |
| Show or hide the outline | Toolbar button or `Ctrl`+`Cmd`+`S` | Header bar button or `F9` |
| Show or hide git history | Toolbar button or `Ctrl`+`Cmd`+`H` | Header bar button or `Ctrl`+`H` |
| Clear a pin, or return to the working copy | `Escape` | `Escape` |

Font, theme, zoom, window size, and pane widths are remembered across
sessions. All settings are global; nothing is stored per file.

### Outline

The outline pane on the left lists the document's headings as a tree. H1 and
H2 are shown at first; expand a heading to see its subheadings, and choose one
to scroll to it. The outline is available in the Rendered view.

### Git history

When the open document is inside a git repository, a history button appears.
The history pane on the right lists the commits that touch the file, with a
"Working copy" entry on top: a red dot when the file has uncommitted changes,
a green dot when it matches HEAD. Each entry shows the file's size, line
count, and word count at that version. Renames are followed.

Selecting a commit shows that version of the document. The Rendered / Diff /
Side by side switch alternates between the formatted document, the unified
diff of its Markdown source, and the same diff in two columns.

To compare any two versions, click the pin on one entry to make it the base,
then select another; both diff views then show base → selected, headed by the
size, line, and word changes between them. Pins appear once there are two
versions to compare: two commits, or a commit plus uncommitted changes.

`Escape` first clears a pin, then returns to the working copy. It works
whether or not the history pane is open, and is the only way back once the
pane is closed. On macOS the same action is **View > Back to Working Copy**.

Live reload pauses while a historic version is shown and resumes on returning
to the working copy. It stays on while the working copy is either side of a
comparison.

The repository is only ever read: View Markdown never checks out, stashes, or
commits.

### Limitations

- The commit list refreshes when the history pane is opened, so a commit made
  elsewhere while the window is open appears the next time the pane is opened.
- Relative images in a historic version resolve against the current working
  tree, so an image deleted since that commit will not load.

## Development

On macOS, set up the environment once and run from the checkout:

```sh
brew install cmark-gfm python@3.12
/opt/homebrew/bin/python3.12 -m venv venv
venv/bin/pip install -r packaging/macos/requirements.txt
venv/bin/python -m view_markdown path/to/document.md
```

Run the tests with `venv/bin/pytest` on macOS and `python3 -m pytest` on
Ubuntu. Each platform runs the shared core tests plus its own front end's.

Preferences are stored in `~/Library/Application Support/View Markdown` on
macOS and `~/.config/view-markdown` on Ubuntu.

## License

View Markdown is available under the [MIT License](LICENSE).
