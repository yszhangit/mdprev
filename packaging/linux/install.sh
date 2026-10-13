#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
bin_home=${XDG_BIN_HOME:-"$HOME/.local/bin"}
app_home="$data_home/view-markdown"
desktop_home="$data_home/applications"
icon_home="$data_home/icons/hicolor/scalable/apps"

mkdir -p "$app_home" "$bin_home" "$desktop_home" "$icon_home"
rm -rf "$app_home/view_markdown"
cp -R "$repo_dir/view_markdown" "$app_home/view_markdown"
cp "$repo_dir/packaging/io.github.fixed-42.view-markdown.svg" "$icon_home/io.github.fixed-42.view-markdown.svg"
cp "$script_dir/bin/view-markdown" "$bin_home/view-markdown"
chmod 755 "$bin_home/view-markdown"

# Use the concrete user-local launcher path: desktop environments do not all
# include ~/.local/bin in PATH when starting an application.
sed "s|^Exec=.*|Exec=$bin_home/view-markdown %f|" \
  "$script_dir/io.github.fixed-42.view-markdown.desktop" > "$desktop_home/io.github.fixed-42.view-markdown.desktop"
update-desktop-database "$desktop_home" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true

echo "View Markdown installed for this user."
echo "It is available in Files' Open With menu for Markdown files."
echo "To make it the default: xdg-mime default io.github.fixed-42.view-markdown.desktop text/markdown"
