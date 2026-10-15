#!/usr/bin/env bash
# Cut the Sea-to-Sky map tiles from Protomaps' daily OpenStreetMap build.
# Only the byte ranges for this area are downloaded, not the whole planet.
#
#   deploy/tiles/build.sh [output.pmtiles]
#
# Needs the pmtiles CLI (https://github.com/protomaps/go-pmtiles/releases),
# on PATH or in $PMTILES. Rebuild every month or two to pick up map edits.
set -euo pipefail

OUT=${1:-/srv/transitlive/tiles/sea-to-sky.pmtiles}
PMTILES=${PMTILES:-pmtiles}
# West, south, east, north: Horseshoe Bay to beyond Pemberton
BBOX=${BBOX:--123.45,49.55,-122.55,50.45}
MAXZOOM=${MAXZOOM:-15}

# Find the newest daily build (they appear a day or two behind)
for days_ago in 0 1 2 3 4 5 6 7 8 9 10; do
  day=$(date -u -v-"${days_ago}"d +%Y%m%d 2>/dev/null || date -u -d "-${days_ago} days" +%Y%m%d)
  url="https://build.protomaps.com/${day}.pmtiles"
  if curl -sfI "$url" >/dev/null; then break; fi
  url=""
done
[[ -n "$url" ]] || { echo "no Protomaps build found in the last 10 days" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
echo "extracting $BBOX (zoom 0-$MAXZOOM) from $url"
"$PMTILES" extract "$url" "$OUT.tmp" --bbox="$BBOX" --maxzoom="$MAXZOOM"
mv "$OUT.tmp" "$OUT"
"$PMTILES" show "$OUT" | head -12
