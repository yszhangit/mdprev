#!/bin/sh
set -eu

data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
bin_home=${XDG_BIN_HOME:-"$HOME/.local/bin"}
app_home="$data_home/mdprev"
desktop_home="$data_home/applications"
icon_home="$data_home/icons/hicolor/scalable/apps"

rm -f "$bin_home/mdprev" \
  "$desktop_home/io.github.yzhang.mdprev.desktop" \
  "$icon_home/io.github.yzhang.mdprev.svg"
rm -rf "$app_home"
update-desktop-database "$desktop_home" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
echo "MdPrev uninstalled. Any default MIME association is left unchanged; choose a new default in Files."
