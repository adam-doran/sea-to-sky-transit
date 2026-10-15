# Layover (Sea-to-Sky Transit Live)

Live bus locations, departures and service checks for Squamish, Whistler and
Pemberton Valley, built on BC Transit's open data. An independent,
volunteer-run project; not an official BC Transit service.

**Status:** the backend (collector, archive, database and API) and the web app
work locally. Not yet deployed; planned home: squamishbuses.ca.

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

You need [uv](https://docs.astral.sh/uv/), Docker and Node 24.

```bash
make setup        # install backend and web dependencies
make test         # backend unit tests
make dev          # the backend stack, collecting from BC Transit
make tiles        # map tiles for the web app (once; needs the pmtiles CLI)
make web-dev      # the web app: http://localhost:5180
```

`make dev-replay` runs the backend on recorded feeds instead (no network).

Then open http://localhost:8100/docs for the API. The dev database listens on
port 5433 (`postgresql://transitlive:transitlive@localhost:5433/transitlive`).

## Contributing

Contributions are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains the
layout, the tests and how to add a transit system.

## Licence

The code is free software under the [GNU Affero General Public License v3.0](LICENSE)
or any later version. If you run a modified version as a public service, the AGPL
requires you to offer its source code to the people using it; the web app links to
its source (`SOURCE_URL` in `web/src/config.ts`) for that reason.

Transit data, including the recorded feeds in `backend/tests/fixtures`, is
© BC Transit, published as [open data](https://www.bctransit.com/open-data/), and
isn't covered by the AGPL. Map data © OpenStreetMap contributors.
For official transit information always check BC Transit.
