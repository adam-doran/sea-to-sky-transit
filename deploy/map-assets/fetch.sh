#!/bin/sh
# Fetch the basemap's fonts and icons so we serve them ourselves (no requests
# to third parties from visitors' browsers). Pinned to one commit of
# protomaps/basemaps-assets and checked against SHA256SUMS.
#
#   deploy/map-assets/fetch.sh OUTPUT_DIR        e.g. web/public/map-assets
#   deploy/map-assets/fetch.sh --update-sums     after changing COMMIT
#
# Licences: fonts are SIL Open Font License (fonts/OFL.txt); icons derive from
# MIT-licensed tangrams/icons (sprites/LICENSE.md). Both ship with the files.
set -eu

COMMIT=028c18f713baecad011301ff7a69acc39bcc2ae7
FONTS="Noto Sans Regular|Noto Sans Medium|Noto Sans Italic"
THEMES="light dark"
HERE=$(cd "$(dirname "$0")" && pwd)

update_sums=false
if [ "${1:-}" = "--update-sums" ]; then update_sums=true; OUT=$(mktemp -d); else OUT=${1:?usage: fetch.sh OUTPUT_DIR}; fi

if ! $update_sums && [ -f "$OUT/.commit" ] && [ "$(cat "$OUT/.commit")" = "$COMMIT" ]; then
  exit 0  # already fetched
fi

sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
download() { if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"; else wget -qO- "$1"; fi; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "fetching map fonts and icons (basemaps-assets@${COMMIT%"${COMMIT#???????}"})"
download "https://codeload.github.com/protomaps/basemaps-assets/tar.gz/$COMMIT" | tar -xz -C "$tmp"
src="$tmp/basemaps-assets-$COMMIT"

stage="$tmp/out"
mkdir -p "$stage/fonts" "$stage/sprites/v4"
echo "$FONTS" | tr '|' '\n' | while IFS= read -r font; do cp -R "$src/fonts/$font" "$stage/fonts/"; done
cp "$src/fonts/OFL.txt" "$stage/fonts/OFL.txt"
for t in $THEMES; do
  for f in "$t.json" "$t.png" "$t@2x.json" "$t@2x.png"; do cp "$src/sprites/v4/$f" "$stage/sprites/v4/"; done
done
cp "$HERE/ICONS-LICENSE.md" "$stage/sprites/LICENSE.md"

if $update_sums; then
  (cd "$stage" && find . -type f | LC_ALL=C sort | while IFS= read -r f; do sha256 "$f"; done) > "$HERE/SHA256SUMS"
  echo "wrote $(wc -l < "$HERE/SHA256SUMS" | tr -d ' ') checksums to deploy/map-assets/SHA256SUMS"
  exit 0
fi

# Plain -c works with GNU coreutils, BusyBox (Alpine) and macOS shasum; only
# the files that fail are shown.
if ! result=$(cd "$stage" && sha256 -c "$HERE/SHA256SUMS" 2>&1); then
  printf '%s\n' "$result" | grep -v ': OK$' >&2
  echo "map assets failed their checksums" >&2
  exit 1
fi
count=$(find "$stage" -type f | wc -l | tr -d ' ')
expected=$(wc -l < "$HERE/SHA256SUMS" | tr -d ' ')
[ "$count" = "$expected" ] || { echo "expected $expected files, got $count" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$(dirname "$OUT")"
cp -R "$stage" "$OUT"
echo "$COMMIT" > "$OUT/.commit"
echo "map assets ready in $OUT ($(du -sh "$OUT" | cut -f1))"
