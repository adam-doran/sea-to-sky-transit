# Sea-to-Sky Transit Live

Live bus locations, departures and service checks for Squamish, Whistler and
Pemberton Valley, built on BC Transit's open data. An independent,
volunteer-run project; not an official BC Transit service.

**Status:** the backend (collector, archive, database and API) is working. The
MapLibre web app is next; the original prototype lives on separately.

## How it works

```
BC Transit ──► collector ──► raw archive (every feed snapshot, compressed)
  27 req/min       │    └──► PostgreSQL (history + every timetable version)
  in total         ▼
               documents ──► API ──► CDN ──► browsers
```

- **One collector talks to BC Transit**, on a fixed schedule: vehicles every
  10 s, trip updates every 30 s, alerts every 60 s, per system. That's 27
  requests a minute in total, however many people use the site.
- **Browsers only ever read our API**, which serves documents the collector has
  already built, with cache headers sized for a CDN.
- **Everything is kept** for future features and research: every distinct
  realtime snapshot in a raw archive, normalised history in PostgreSQL, and
  every version of the timetable.
- **Timetables sync every 6 hours**, and immediately if live trips stop matching
  the timetable.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the details and
[docs/DATA.md](docs/DATA.md) for the database.

## Run it locally

You need [uv](https://docs.astral.sh/uv/) and Docker.

```bash
make setup        # install backend dependencies
make test         # unit tests
make dev-replay   # the full stack, replaying recorded feeds (no network)
make dev          # the full stack, collecting from BC Transit
```

Then open http://localhost:8100/docs for the API. The dev database listens on
port 5433 (`postgresql://transitlive:transitlive@localhost:5433/transitlive`).

## Contributing

Contributions are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains the
layout, the tests and how to add a transit system.

## Data

Transit data © BC Transit, from its [open data](https://www.bctransit.com/open-data/).
For official information always check BC Transit.
