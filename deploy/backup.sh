#!/usr/bin/env bash
# Nightly database dump: only what the archive can't rebuild.
# Install with cron on the host, e.g.:
#   15 3 * * * /opt/sea-to-sky-transit/deploy/backup.sh >> /var/log/transitlive-backup.log 2>&1
#
# Left out: the rows of vehicle_positions and stop_predictions (and their
# partitions), which `transitlive replay` rebuilds from the daily bundles, and
# live_documents, which the collector rebuilds within seconds. Their schema is
# still dumped. Everything else is kept: feed_fetches (the fetch log, which no
# archive can rebuild), timetables, alerts and systems.
#
# The bundles themselves go to S3 from the collector and/or are pulled by a NAS
# (docs/RUNBOOK.md), as is this backups folder.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a

BACKUPS=/srv/transitlive/backups
mkdir -p "$BACKUPS"
stamp=$(date -u +%Y-%m-%d)
out="$BACKUPS/transitlive-$stamp.dump"

docker compose -f compose.yml exec -T db pg_dump -U transitlive -Fc \
  --exclude-table-data-and-children=vehicle_positions \
  --exclude-table-data-and-children=stop_predictions \
  --exclude-table-data=live_documents \
  transitlive > "$out.tmp"
mv "$out.tmp" "$out"
find "$BACKUPS" -name 'transitlive-*.dump' -mtime +14 -delete   # keep two weeks locally

if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  rclone copy "$BACKUPS" "$RCLONE_REMOTE/backups" --max-age 48h
fi
echo "$(date -u +%FT%TZ) backup ok: $(basename "$out") ($(du -h "$out" | cut -f1))"
