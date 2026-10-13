#!/bin/sh
set -eu

app="${VIEW_MARKDOWN_APP_DIR:-"$HOME/Applications"}/View Markdown.app"
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

if [ -d "$app" ]; then
  "$lsregister" -u "$app" >/dev/null 2>&1 || true
  rm -rf "$app"
fi
echo "View Markdown uninstalled. Preferences in ~/Library/Application Support/View Markdown and any default application choice are left unchanged."
