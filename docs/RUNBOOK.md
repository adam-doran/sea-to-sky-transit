# Runbook

For volunteers running the service. One VPS, Docker Compose, a CDN in front.

## Server

- About 2 vCPU, 4 GB RAM, and an 80–100 GB volume mounted at `/srv/transitlive`
  (about $6–12 a month at Hetzner or DigitalOcean).
- Docker with the Compose plugin; `rclone` for offsite backups.
- DNS for your domain through Cloudflare (proxied), pointing at the server.

## First deploy

```bash
git clone https://github.com/<owner>/sea-to-sky-transit /opt/sea-to-sky-transit
cd /opt/sea-to-sky-transit
cp deploy/.env.example deploy/.env    # set DOMAIN, POSTGRES_PASSWORD, GITHUB_OWNER, IMAGE_TAG
sudo mkdir -p /srv/transitlive/{postgres,archive,backups,web,tiles}
sudo chown 10001 /srv/transitlive/archive
docker compose -f deploy/compose.yml --env-file deploy/.env up -d
```

Set the contact details in `config/systems.toml` (`user_agent`) before the
first deploy, so BC Transit can reach the operators.

Check it: `curl https://$DOMAIN/api/health` returns `"ok": true` within a
minute or two.

## Updating

```bash
# set IMAGE_TAG in deploy/.env to the new release, then:
docker compose -f deploy/compose.yml --env-file deploy/.env pull
docker compose -f deploy/compose.yml --env-file deploy/.env up -d
```

Migrations run automatically (`migrate` runs before the collector and API start).

## Monitoring

Point an uptime checker (healthchecks.io, UptimeRobot) at `/api/health`. It
returns 503 when any realtime feed hasn't been fetched successfully for 2
minutes, and lists each feed's age and each system's timetable expiry.

```bash
docker compose -f deploy/compose.yml logs -f collector   # what the collector is doing
```

## Backups

Add `deploy/backup.sh` to cron (see the comment at the top of the script). It
dumps the database nightly and copies dumps and the raw archive to
`RCLONE_REMOTE`.

## Common problems

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Health shows one feed stale | BC Transit outage | Nothing; the collector backs off and recovers. Check `feed_fetches.error`. |
| All feeds stale | Collector stopped | `docker compose ... ps`, then `logs collector`. |
| App shows "timetable out of date" | BC Transit changed trip IDs | The collector syncs automatically; check its logs for "activated timetable". |
| Disk filling | Growth over time | Check `du -sh /srv/transitlive/*`; old archive months are safe to move offsite once backed up. |

## Rebuilding the database from the archive

```bash
docker compose -f deploy/compose.yml stop collector
docker compose -f deploy/compose.yml run --rm -v /srv/transitlive/archive:/archive collector replay /archive --speed 0
docker compose -f deploy/compose.yml start collector
```
