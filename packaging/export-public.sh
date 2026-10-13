#!/bin/sh
# Copy the published files of a commit into the public checkout.
#
#   packaging/export-public.sh [REF] [PUBLIC_DIR]
#
# REF defaults to HEAD and PUBLIC_DIR to ../view-markdown.  The files left
# out are listed in .gitattributes (export-ignore).  Nothing is committed in
# the public checkout; review and commit there separately.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
ref=${1:-HEAD}
public_dir=${2:-"$repo_dir/../view-markdown"}

cd "$repo_dir"
if [ ! -d "$public_dir/.git" ]; then
  echo "$public_dir is not a git checkout." >&2
  exit 1
fi
public_dir=$(CDPATH= cd -- "$public_dir" && pwd)
if [ "$ref" = HEAD ] && [ -n "$(git status --porcelain)" ]; then
  echo "Commit your changes first: only committed files are exported." >&2
  exit 1
fi

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
git archive "$ref" | tar -x -C "$stage"

# The public repository must not identify the maintainer of this one, nor
# name this repository.
for word in "$(git config user.name)" "$(git config user.email)" \
  "$(id -un)" "$HOME" "$(basename "$repo_dir")"; do
  [ -n "$word" ] || continue
  if grep -r -I -i -l -F -e "$word" "$stage"; then
    echo "Not exported: the files above contain \"$word\"." >&2
    exit 1
  fi
done

# Replace the files git tracks there; .git and ignored files are left alone.
(cd "$public_dir" && git ls-files -z | xargs -0 rm -f)
cp -R "$stage"/. "$public_dir"/

echo "Exported $(git rev-parse --short "$ref") to $public_dir."
their_email=$(git -C "$public_dir" config user.email || true)
if [ -z "$their_email" ] || [ "$their_email" = "$(git config user.email)" ]; then
  echo "Warning: that checkout would commit with this repository's identity." >&2
  echo "Set its own user.name and user.email before committing there." >&2
fi
echo "Review it with: git -C \"$public_dir\" status"
