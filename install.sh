#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
bin_home=${XDG_BIN_HOME:-"$HOME/.local/bin"}
app_home="$data_home/mdprev"
desktop_home="$data_home/applications"
icon_home="$data_home/icons/hicolor/scalable/apps"

mkdir -p "$app_home" "$bin_home" "$desktop_home" "$icon_home"
rm -rf "$app_home/mdprev"
cp -R "$script_dir/mdprev" "$app_home/mdprev"
cp "$script_dir/io.github.yszhangit.mdprev.svg" "$icon_home/io.github.yszhangit.mdprev.svg"
cp "$script_dir/bin/mdprev" "$bin_home/mdprev"
chmod 755 "$bin_home/mdprev"

# Use the concrete user-local launcher path: desktop environments do not all
# include ~/.local/bin in PATH when starting an application.
sed "s|^Exec=.*|Exec=$bin_home/mdprev %f|" \
  "$script_dir/io.github.yszhangit.mdprev.desktop" > "$desktop_home/io.github.yszhangit.mdprev.desktop"
update-desktop-database "$desktop_home" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true

echo "MdPrev installed for this user."
echo "It is available in Files' Open With menu for Markdown files."
echo "To make it the default: xdg-mime default io.github.yszhangit.mdprev.desktop text/markdown"
