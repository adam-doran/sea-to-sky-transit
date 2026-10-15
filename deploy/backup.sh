#!/usr/bin/env bash
# Nightly backup: a database dump plus the raw archive, copied offsite.
# Install with cron on the host, e.g.:
#   15 3 * * * /opt/sea-to-sky-transit/deploy/backup.sh >> /var/log/transitlive-backup.log 2>&1
# The raw archive alone is enough to rebuild the database (transitlive replay).
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a

BACKUPS=/srv/transitlive/backups
mkdir -p "$BACKUPS"
stamp=$(date -u +%Y-%m-%d)

docker compose -f compose.yml exec -T db pg_dump -U transitlive -Fc transitlive > "$BACKUPS/transitlive-$stamp.dump"
find "$BACKUPS" -name 'transitlive-*.dump' -mtime +14 -delete   # keep two weeks locally

if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  rclone copy "$BACKUPS" "$RCLONE_REMOTE/backups" --max-age 48h
  rclone copy /srv/transitlive/archive "$RCLONE_REMOTE/archive" --max-age 72h   # append-only: only new files
fi
echo "$(date -u +%FT%TZ) backup ok: transitlive-$stamp.dump"
