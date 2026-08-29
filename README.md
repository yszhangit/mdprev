# MdPrev

MdPrev is a small, read-only Markdown previewer for Ubuntu 26.04 GNOME. It
uses the system GTK 4, WebKitGTK 6.0, and cmark-gfm packages.

## Install

Install the Ubuntu runtime packages:

```sh
sudo apt install cmark-gfm gir1.2-gtk-4.0 gir1.2-webkit-6.0
```

Then install MdPrev for the current user:

```sh
./install.sh
```

Open a Markdown file from Files' **Open With** menu, or run:

```sh
mdprev path/to/document.md
```

To explicitly make it the default Markdown handler:

```sh
xdg-mime default io.github.yzhang.mdprev.desktop text/markdown
xdg-mime default io.github.yzhang.mdprev.desktop text/x-markdown
```

The previous default can be restored with `xdg-mime default
<previous-desktop-file> <mime-type>`. Uninstalling leaves MIME defaults
untouched so unrelated preferences are not overwritten.

## MVP 1 behavior

CommonMark and GFM tables, task lists, strikethrough, and autolinks are
supported. The preview reloads after saves and permits document-relative local
images. JavaScript, raw HTML, remote images, and unsafe links are disabled.
The source file is never modified.

## Uninstall

```sh
./uninstall.sh
```

## License

MdPrev is available under the [MIT License](LICENSE).
