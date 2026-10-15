# Runbook

For volunteers running the service. One small server, Docker Compose, a CDN in
front, and long-term storage in S3 and/or on a NAS at home.

## Server

- A small instance is enough, e.g. an AWS EC2 `t4g.micro` (arm64) with about
  20 GB of disk for `/srv/transitlive`. Raw snapshots are kept locally for
  only a few days and the database for about 90 days, so the data stays at a
  few GB; daily bundles add about 1–1.5 GB a year (docs/DATA.md).
- Docker with the Compose plugin.
- Optional: an S3 bucket, a NAS on Tailscale, or both, for the bundles.
- DNS for your domain through Cloudflare (proxied), pointing at the server.

## First deploy

```bash
git clone https://github.com/<owner>/sea-to-sky-transit /opt/sea-to-sky-transit
cd /opt/sea-to-sky-transit
cp deploy/.env.example deploy/.env    # set DOMAIN, POSTGRES_PASSWORD, GITHUB_OWNER, IMAGE_TAG
sudo mkdir -p /srv/transitlive/{postgres,archive,backups,tiles}
sudo chown 10001 /srv/transitlive/archive
deploy/tiles/build.sh            # map tiles (~20 MB); needs the pmtiles CLI
docker compose -f deploy/compose.yml --env-file deploy/.env up -d
```

Requests to BC Transit carry `contact@squamishbuses.ca` in their
`User-Agent` (`config/systems.toml`). Keep that mailbox monitored, and update
it there if it ever changes.

Check it: `curl https://$DOMAIN/api/health` returns `"ok": true` within a
minute or two.

## Updating

```bash
# set IMAGE_TAG in deploy/.env to the new release, then:
docker compose -f deploy/compose.yml --env-file deploy/.env pull
docker compose -f deploy/compose.yml --env-file deploy/.env up -d
```

Migrations run automatically (`migrate` runs before the collector and API start).

Refresh the map tiles every month or two with `deploy/tiles/build.sh`.

Images from the release workflow link to their source code in the footer, as
the AGPL requires. If you build the web image yourself, pass
`--build-arg SOURCE_URL=https://github.com/<owner>/sea-to-sky-transit`.

## Monitoring

Point an uptime checker (healthchecks.io, UptimeRobot) at `/api/health`. It
returns 503 when any realtime feed hasn't been fetched successfully for 2
minutes, and lists each feed's age and each system's timetable expiry.

```bash
docker compose -f deploy/compose.yml logs -f collector   # what the collector is doing
```

## Long-term storage and backups

What needs keeping, and where it lives:

| Data | Rebuildable? | Kept on the server | Off the server |
| --- | --- | --- | --- |
| Daily bundles `archive/bundles/` | no: the source of truth | all of them (~1–1.5 GB a year) | S3 (uploaded by the collector) and/or NAS (rsync) |
| Snapshot files `archive/{system}/{feed}/` | yes, they're in the bundles | 3 days | — |
| `vehicle_positions`, `stop_predictions` | yes, by replaying bundles | 90 days | — |
| Everything else in PostgreSQL (`feed_fetches`, timetables, alerts) | no | always | nightly dump from `deploy/backup.sh` |

Retention settings are in the `[archive]` section of `config/systems.toml`
(docs/DATA.md explains the rules). The collector logs a summary of each
nightly run: `docker compose -f deploy/compose.yml logs collector | grep archive`.

### S3 (optional)

The collector uploads each bundle with the instance's IAM role; no keys go in
any config file.

1. Create a private bucket in the same region as the instance (all public
   access blocked; the default SSE-S3 encryption is fine):

   ```bash
   aws s3api create-bucket --bucket layover-archive --region ca-central-1 \
     --create-bucket-configuration LocationConstraint=ca-central-1
   aws s3api put-public-access-block --bucket layover-archive \
     --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

2. Give the instance a role with only this policy (replace the bucket and
   prefix). `ListBucket` is there so a check for a missing bundle returns 404
   rather than 403; `GetObject` covers that check, and restores.

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject"],
         "Resource": "arn:aws:s3:::layover-archive/bundles/*"
       },
       {
         "Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::layover-archive",
         "Condition": { "StringLike": { "s3:prefix": "bundles/*" } }
       }
     ]
   }
   ```

   Leave out `s3:DeleteObject`, so a compromised server can't delete the
   archive; turning on bucket versioning also protects against overwrites.
   If the bucket uses SSE-KMS, the role also needs `kms:GenerateDataKey` on
   that key.

3. Containers reach the instance's credentials through the metadata service,
   one network hop further than the host, so allow two hops:

   ```bash
   aws ec2 modify-instance-metadata-options --instance-id i-0123456789abcdef0 \
     --http-tokens required --http-put-response-hop-limit 2
   ```

4. Set `S3_BUCKET=layover-archive`, `S3_PREFIX=bundles/` and
   `AWS_REGION=ca-central-1` in `deploy/.env`, then
   `docker compose -f deploy/compose.yml --env-file deploy/.env up -d collector`.

5. Check it by bundling and uploading yesterday straight away:

   ```bash
   docker compose -f deploy/compose.yml exec collector transitlive bundle --archive /archive
   aws s3 ls s3://layover-archive/bundles/ --recursive | tail
   ```

Snapshot files are only deleted once S3 has the exact bundle, so if uploads
fail (the log says why), files pile up rather than being lost. Bundles are
small, so S3 Standard costs a few cents a month; a lifecycle rule moving
objects older than 30 days to Glacier Instant Retrieval is optional.

### NAS (rsync over Tailscale)

The NAS pulls from the server, so the server never needs credentials for it.

1. Put both machines on your tailnet (`tailscale up` on each; on the server,
   `tailscale up --ssh` lets Tailscale handle SSH access too).
2. On the server, make a read-only account for the NAS:

   ```bash
   sudo useradd --create-home backup
   sudo setfacl -R -m u:backup:rX -m d:u:backup:rX /srv/transitlive/archive/bundles /srv/transitlive/backups
   ```

   (Or use a normal SSH key for `backup` in `~backup/.ssh/authorized_keys`.)
3. On the NAS, schedule (cron, or the NAS's task scheduler) nightly, after
   03:30 UTC so both the bundles and the dump are written:

   ```bash
   rsync -a --partial --exclude '*.tmp' backup@layover:/srv/transitlive/archive/bundles/ /volume1/layover/bundles/
   rsync -a --partial backup@layover:/srv/transitlive/backups/ /volume1/layover/backups/
   ```

   `layover` is the server's Tailscale name. Don't pass `--delete` for the
   bundles: the NAS copy should only ever grow. A bundle that's rebuilt (when
   late files turn up) is simply copied again.

### Database dumps

Add `deploy/backup.sh` to cron on the server (see the comment at the top of the
script). It dumps the database nightly to `/srv/transitlive/backups`, keeping
two weeks, but leaves out the history tables' rows and the cached documents,
which the bundles and collector rebuild; that keeps the dump small. If
`RCLONE_REMOTE` is set it also copies the dumps there.

## Restoring

On a new server, after the first deploy steps (or to recover a broken
database):

```bash
docker compose -f deploy/compose.yml stop collector api
# 1. Bundles: from S3...
aws s3 sync s3://layover-archive/bundles/ /srv/transitlive/archive/bundles/
#    ...or from the NAS (run there, as a user that can write on the server)
rsync -a /volume1/layover/bundles/ admin@layover:/srv/transitlive/archive/bundles/
sudo chown -R 10001 /srv/transitlive/archive
# 2. The latest dump: fetch log, timetables, alerts (and the empty history tables)
docker compose -f deploy/compose.yml exec -T db pg_restore -U transitlive -d transitlive --clean --if-exists \
  < /srv/transitlive/backups/transitlive-YYYY-MM-DD.dump
# 3. History, by replaying the bundles as fast as possible
docker compose -f deploy/compose.yml run --rm -v /srv/transitlive/archive:/archive collector replay /archive --speed 0
docker compose -f deploy/compose.yml start collector api
```

Replay reads snapshot files and bundles alike, so the same command rebuilds
history on the running server after a database problem (step 3 alone). Only
the last 90 days stay in the database, so to save time, copy just the recent
bundles into a scratch archive folder and replay that. The collector drops
older months again on its next nightly run.

To explore older history without touching production, replay any range of
bundles into a local database. Put them in `path/to/archive/bundles/`, then:

```bash
docker compose -f deploy/compose.dev.yml up -d db migrate      # PostgreSQL on localhost:5433
cd backend && TRANSITLIVE_DATABASE_URL=postgresql+psycopg://transitlive:transitlive@localhost:5433/transitlive \
  uv run transitlive replay path/to/archive --speed 0
```

## Common problems

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Health shows one feed stale | BC Transit outage | Nothing; the collector backs off and recovers. Check `feed_fetches.error`. |
| All feeds stale | Collector stopped | `docker compose ... ps`, then `logs collector`. |
| App shows "timetable out of date" | BC Transit changed trip IDs | The collector syncs automatically; check its logs for "activated timetable". |
| Disk filling | Snapshot files not being deleted | `du -sh /srv/transitlive/*`; check the collector log for "keeping ... files" (usually S3 uploads failing: IAM policy or the metadata hop limit). |
| History older than 90 days still in the database | A day without bundles in that month | The collector logs "keeping ...: N days have no bundles". If those days genuinely had no data (collector down), drop the partition by hand once you're sure. |
