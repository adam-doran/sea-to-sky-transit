# Data

Everything the collector sees is kept, for future features and research.

## Raw archive

The source of truth. Every distinct realtime snapshot, zstd-compressed, and
every timetable zip:

```
archive/{system}/{feed}/{YYYY-MM-DD}/{feed_header_timestamp}.pb.zst   (dates in UTC)
archive/{system}/static/{YYYY-MM-DD}_{sha256-prefix}.zip
```

Read a snapshot with `zstd -d` and any GTFS-Realtime decoder, or in Python:

```python
from transitlive.collector.archive import Archive
from transitlive.collector.realtime import decode
snapshot = decode("vehicleupdates", Archive.read(path))
```

For Sea-to-Sky, expect roughly 30–40 MB a day.

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
| `stop_predictions` | change in a predicted arrival or departure for a trip at a stop |
| `alerts` | distinct version of an alert, with when it was first and last seen |
| `live_documents` | current API document per system and kind (gzipped JSON) |

`vehicle_positions` and `stop_predictions` are partitioned by month; the
collector creates partitions ahead of time.

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
