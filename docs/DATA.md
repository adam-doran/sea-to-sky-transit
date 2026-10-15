# Data

Everything the collector sees is kept, for future features and research.

## Raw archive

The source of truth: every distinct realtime snapshot and every timetable zip.
The database can be rebuilt from it. All dates are UTC, so daylight saving
never makes a day ambiguous.

```
archive/{system}/{feed}/{YYYY-MM-DD}/{feed_header_timestamp}.pb.zst   snapshots, as fetched
archive/{system}/static/{YYYY-MM-DD}_{sha256-prefix}.zip               timetables
archive/bundles/{system}/{YYYY-MM-DD}.tar.zst                          one bundle per system and day
```

### Daily bundles

The collector writes one small file per snapshot. Shortly after midnight UTC
it packs the previous day of each system into a bundle: a tar file,
compressed with zstd at level 19, of that day's snapshots (uncompressed
inside) and timetable zips:

```
static/{YYYY-MM-DD}_{sha256-prefix}.zip
alerts/{feed_header_timestamp}.pb
tripupdates/{feed_header_timestamp}.pb
vehicleupdates/{feed_header_timestamp}.pb
```

Consecutive snapshots are nearly identical, so compressing a whole day
together works far better than compressing each file. On live Sea-to-Sky data,
a bundle is about 35 times smaller than the raw snapshots and 8 times smaller
than the individual `.pb.zst` files. Expect about 4 MB of bundles a day, or
roughly 1–1.5 GB a year for all three systems.

The nightly run is safe to repeat (the same code runs as
`transitlive bundle [--date YYYY-MM-DD]`, which defaults to yesterday, UTC):

1. **Bundle** every finished day that still has files. Each bundle is
   decompressed and checked against the source files (member count and each
   member's sha256) before it replaces the old one atomically. A bundle that
   already holds every file of its day is left alone. If late files turn up,
   the bundle is rebuilt with them, keeping members whose files are already
   gone.
2. **Upload** it to S3, if `[archive] s3_bucket` is set in
   `config/systems.toml` (or `TRANSITLIVE_S3_BUCKET` is), at
   `s3://{bucket}/{prefix}{system}/{YYYY-MM-DD}.tar.zst`. An object that
   already exists with the same size and sha256 (object metadata `sha256`) is
   skipped. Without a bucket, bundles stay local for a NAS to pull.
3. **Delete** a day's snapshot files once the day is more than
   `keep_snapshot_days` (default 3) old, only if its bundle holds every one of
   them byte for byte and, with S3, the bucket has that exact bundle. A day
   without a verified bundle is never deleted. Timetable zips and bundles are
   kept locally: the collector reads the zips on restart, and a NAS pulls the
   bundles.

Read a bundle with standard tools:

```bash
tar --zstd -tvf archive/bundles/squamish/2026-10-15.tar.zst      # or: zstd -dc FILE | tar tv
```

Or in Python, from files and bundles alike:

```python
from transitlive.collector.archive import Archive
from transitlive.collector.realtime import decode
for ts, data in Archive("archive").snapshots("squamish", "vehicleupdates"):
    snapshot = decode("vehicleupdates", data)
```

## PostgreSQL

All times are `timestamptz` (UTC). System IDs are BC Transit operator IDs
(43 Squamish, 44 Whistler, 50 Pemberton Valley).

| Table | One row per |
| --- | --- |
| `systems` | transit system |
| `feed_fetches` | request to BC Transit, including failures (`error`), and whether the content was new |
| `feed_versions` | distinct timetable; `active` marks the one in use |
| `gtfs_routes`, `gtfs_stops`, `gtfs_trips`, `gtfs_stop_times`, `gtfs_shapes`, `gtfs_calendar`, `gtfs_calendar_dates` | timetable rows, keyed by `feed_version_id` |
| `vehicle_positions` | vehicle report (deduplicated on the vehicle's own timestamp), with `shape_index` and `distance_along` |
| `stop_predictions` | change in a predicted arrival or departure for a trip at a stop: the first prediction seen, then whenever a time moves by at least `prediction_threshold_seconds` (default 30) or a stop or trip is skipped, cancelled, etc. |
| `alerts` | distinct version of an alert, with when it was first and last seen |
| `live_documents` | current API document per system and kind (gzipped JSON) |

`vehicle_positions` and `stop_predictions` are partitioned by month; the
collector creates partitions ahead of time. They are the bulk of the database
and can be rebuilt from the archive, so the database keeps only recent
history: each night the collector drops a monthly partition once the whole
month is more than `database_days` (default 90) old, but only if every day of
that month has bundles for every system (empty partitions go regardless). It
logs each partition it drops or keeps. The `_default` partitions and all other
tables, including `feed_fetches` (which the archive can't rebuild), are never
dropped. To query older history, replay the bundles you need into a database
(see the runbook).

Example: how late was each Squamish trip at each stop today?

```sql
SELECT trip_id, stop_id, max(delay) / 60.0 AS worst_delay_min
FROM stop_predictions
WHERE system_id = 43 AND observed_at >= date_trunc('day', now())
GROUP BY trip_id, stop_id
ORDER BY worst_delay_min DESC;
```

## Licence

Transit data is BC Transit's, published as open data; check its terms before
redistributing. Public exports (e.g. Parquet) are a planned follow-up.
