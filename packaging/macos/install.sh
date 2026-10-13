#!/bin/sh
# Build View Markdown.app on this Mac and install it for the current user.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
app_home=${VIEW_MARKDOWN_APP_DIR:-"$HOME/Applications"}
app_name="View Markdown.app"
brew_python=/opt/homebrew/bin/python3.12
python="$repo_dir/venv/bin/python"
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

if [ "$(uname -sm)" != "Darwin arm64" ]; then
  echo "View Markdown supports macOS on Apple silicon only." >&2
  exit 1
fi
if ! command -v cmark-gfm >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/cmark-gfm ]; then
  echo "cmark-gfm is missing. Install it with: brew install cmark-gfm" >&2
  exit 1
fi

if [ ! -x "$python" ]; then
  if [ ! -x "$brew_python" ]; then
    echo "Python 3.12 is missing. Install it with: brew install python@3.12" >&2
    exit 1
  fi
  echo "Creating the virtual environment in venv/ ..."
  "$brew_python" -m venv "$repo_dir/venv"
  "$python" -m pip install --quiet -r "$script_dir/requirements.txt"
fi

build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT

# The icon is drawn from the same SVG the Linux install uses.
iconset="$build_dir/icon.iconset"
mkdir "$iconset"
for size in 16 32 128 256 512; do
  for scale in 1 2; do
    pixels=$((size * scale))
    suffix=""
    [ "$scale" -eq 2 ] && suffix="@2x"
    sips -s format png -z "$pixels" "$pixels" \
      "$repo_dir/packaging/io.github.fixed-42.view-markdown.svg" \
      --out "$iconset/icon_${size}x${size}${suffix}.png" >/dev/null
  done
done
iconutil -c icns "$iconset" -o "$build_dir/icon.icns"

echo "Building $app_name ..."
(cd "$build_dir" && "$python" "$script_dir/setup.py" py2app \
  --iconfile "$build_dir/icon.icns" >"$build_dir/build.log" 2>&1) || {
  tail -n 30 "$build_dir/build.log" >&2
  echo "The build failed." >&2
  exit 1
}

# py2app's launcher is built against an old macOS SDK, which makes AppKit
# draw the window in its pre-26 compatibility style.  Mark it as built for
# macOS 26, as Homebrew's Python is, and sign the changed bundle ad hoc.
built="$build_dir/dist/$app_name"
launcher="$built/Contents/MacOS/View Markdown"
if xcrun -f vtool >/dev/null 2>&1; then
  xcrun vtool -set-build-version macos 26.0 26.0 -replace \
    -output "$launcher.new" "$launcher" 2>/dev/null
  mv "$launcher.new" "$launcher"
  chmod 755 "$launcher"
  codesign --force --sign - "$built" 2>/dev/null
fi

mkdir -p "$app_home"
rm -rf "$app_home/$app_name"
ditto "$built" "$app_home/$app_name"
"$lsregister" -f "$app_home/$app_name"

echo "View Markdown installed in $app_home."
echo "It is available in Finder's Open With menu for Markdown files."
echo "To make it the default: select a Markdown file in Finder, choose"
echo "File > Get Info, pick View Markdown under Open with, then Change All."
