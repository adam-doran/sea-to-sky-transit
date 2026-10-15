# Contributing

Thanks for helping. This project is run by volunteers for people who ride the
bus, so changes need to keep it reliable and cheap to run.

## Set up

You need [uv](https://docs.astral.sh/uv/), Docker and Node 24.

```bash
make setup
make test               # unit tests, a second or two, no Docker
make test-integration   # collector -> PostgreSQL -> API, starts a throwaway database
make lint
```

`make test-all` runs everything CI runs. Pull requests need it to pass.

## Where things live

```
config/systems.toml        transit systems and polling intervals
backend/src/transitlive/
  domain/                  pure logic, no I/O: service days, departures, waiting buses,
                           schedule check, shape tracking, shared-road runs
  gtfs/                    read and compile static timetables
  collector/               fetch, decode, archive, ingest; replay and capture
  live/runtime.py          per-system state -> the documents the API serves
  db/                      tables, migrations, queries
  api/                     FastAPI app and response schemas (the web app's contract)
backend/tests/
  unit/                    fast tests; builders.py makes tiny GTFS feeds in memory
  integration/             needs Docker
  fixtures/archive/        recorded real feeds, replayed by tests and make dev-replay
web/src/
  lib/                     pure, tested helpers: gliding along shapes, nearby stops, formatting
  map/                     MapLibre: basemap, route lines, stops, bus markers
  ui/                      the panel: near you, routes, schedule check, stop and bus details
  api/                     client, plus types generated from the backend (make api-types)
web/tests/                 Vitest unit tests
deploy/                    Docker Compose, Caddy, backups, map tiles
docs/                      architecture, data, runbook
```

## Tests

- **Logic goes in `domain/`** and gets unit tests. `make test` fails if domain
  coverage drops below 90%.
- **Edge cases are built by hand** with `tests/builders.py`: daylight-saving
  days, trips past midnight, loops, cancelled and extra trips. Add one for any
  bug you fix.
- **Recorded feeds** in `tests/fixtures/archive` check that real data decodes,
  that every document matches the API schemas, and that buses stay on their
  route lines. Refresh them with `make fixtures` (keep them small: 10 minutes
  is plenty).
- **Never call BC Transit from a test.** Use the fixtures or `httpx.MockTransport`.
- **End-to-end tests** (`make e2e`) run the built web app against the backend
  replaying the fixtures, on desktop and phone viewports, with the browser clock
  frozen at the fixtures' time and no map tiles. Each test reads the API's own
  documents and checks the page against them, so they keep passing when you
  refresh the fixtures. Any console error fails a test.

## The web app

`make web-dev` serves it at http://localhost:5180 against the backend from
`make dev`. Keep logic in `web/src/lib/` with tests; `make web-check` runs lint,
types, tests and a build.

If you change an API response, update `backend/src/transitlive/api/schemas.py`,
then run `make api-types` and commit the regenerated types. CI fails if they
don't match.

## Adding a transit system

Add an entry to `config/systems.toml` with its operator ID from
https://www.bctransit.com/open-data/. Each system adds 9 requests a minute to
BC Transit's load, so check with the maintainers first.

## Changing the database

Add an Alembic migration in `backend/src/transitlive/db/migrations/versions/`
and update `db/schema.py` to match. Never edit a migration that has shipped.

## Be kind to BC Transit

The collector is the only code that contacts BC Transit, and it does so on a
fixed schedule with backoff. Don't add other callers, and don't shorten the
intervals without discussion.
