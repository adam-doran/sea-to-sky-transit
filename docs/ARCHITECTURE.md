# Architecture

## Components

| Component | Runs | Does |
| --- | --- | --- |
| collector | `transitlive collect` | The only thing that contacts BC Transit. Polls, archives, stores, builds documents. |
| PostgreSQL 16 | `db` | History, timetable versions, the fetch log, and the pre-built documents. |
| API | `transitlive api` | Serves the documents. Never contacts BC Transit. |
| Caddy | `caddy` | TLS, compression, the web app and map tiles, proxy to the API. |
| CDN | Cloudflare (free) | Caches the API for 5–300 s, so traffic spikes never reach the server. |

## Polling

Per system (`config/systems.toml`):

| Feed | Interval | Requests/min |
| --- | --- | --- |
| `vehicleupdates.pb` | 10 s | 6 |
| `tripupdates.pb` | 30 s | 2 |
| `alerts.pb` | 60 s | 1 |
| static timetable zip | 6 h | — |

Three systems give 27 requests a minute in total. After a failure the next
attempt for that feed waits with exponential backoff and jitter, capped at
5 minutes. Requests identify the project in their `User-Agent`.

## What happens on each fetch

1. The request is logged in `feed_fetches`: status, size, hash, latency, error.
2. If the body differs from the last fetch, it's decoded and:
   - written to the raw archive (`archive/{system}/{feed}/{date}/{ts}.pb.zst`),
   - applied to the system's runtime (`live/runtime.py`),
   - stored as history (`vehicle_positions`, `stop_predictions`, `alerts`).
3. The affected documents are rebuilt and saved to `live_documents`. That also
   happens when the data is unchanged, because times move on ("due in 3 min").

## Documents

| Document | Rebuilt | Cache-Control | Size (gzip) |
| --- | --- | --- | --- |
| `static` | timetable change | 300 s | 10–20 KB |
| `live` | every vehicle fetch | 5 s | ~1 KB |
| `departures` | every trip-update fetch | 15 s | 1–6 KB |

Responses have ETags, so unchanged data returns 304.

`departures` covers every stop in a system. The web app picks the stops near
you on the device, so no request ever reveals a user's location.

## Logic on the server

The hard parts run once, in tested Python (`domain/`), not in every browser:

- **Waiting to depart:** stationary, and either the trip hasn't started or the
  bus is still at its first stop.
- **Schedule check:** trips that should be running but no bus is reporting
  (allowing for a bus already on the next trip of its block), cancelled trips,
  and extra trips missing from the timetable.
- **Next departure per route:** a bus still waiting stays the next departure
  after its scheduled time passes.
- **Shape tracking:** each bus's distance along its trip's own shape, moving
  forward only, so the map can glide it along the route line. Distances on
  closed loops keep counting past the end ("unwrapped").
- **Shared-road runs:** road segments grouped by the routes that use them.

## Timetable sync

Every 6 hours the collector downloads each system's timetable zip. Its content
hash ignores `feed_info.txt`, which changes on every daily export, so only real
changes create a new version. A new version is stored in full and becomes
active once its calendar covers today.

If more than 20% of reporting buses run trips the active timetable doesn't
know, three checks in a row, the collector syncs immediately (at most every
15 minutes), and the `live` document's `timetable.out_of_date` flag tells the
app to show a warning.

## Restarts and rebuilds

On start the collector restores each system's active timetable from the
archive, so it doesn't depend on BC Transit being reachable. The whole
database can be rebuilt from the raw archive with `transitlive replay`;
inserts are idempotent.
