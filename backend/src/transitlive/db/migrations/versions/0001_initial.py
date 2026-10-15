"""Initial schema: systems, fetch log, timetable versions, realtime history, live documents.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE systems (
    id          smallint PRIMARY KEY,
    slug        text NOT NULL UNIQUE,
    name        text NOT NULL,
    operator_id integer NOT NULL,
    timezone    text NOT NULL
);

-- One row per upstream request: monitoring, and research on feed reliability
CREATE TABLE feed_fetches (
    id          bigserial PRIMARY KEY,
    system_id   smallint NOT NULL REFERENCES systems(id),
    feed        text NOT NULL,
    fetched_at  timestamptz NOT NULL,
    url         text NOT NULL,
    http_status smallint,
    bytes       integer,
    sha256      text,
    header_at   timestamptz,
    latency_ms  integer,
    is_new      boolean NOT NULL DEFAULT false,
    error       text
);
CREATE INDEX feed_fetches_fetched_at_brin ON feed_fetches USING brin (fetched_at);
CREATE INDEX feed_fetches_latest ON feed_fetches (system_id, feed, fetched_at DESC);

-- One row per distinct static timetable (ignoring the per-export feed_info.txt)
CREATE TABLE feed_versions (
    id             serial PRIMARY KEY,
    system_id      smallint NOT NULL REFERENCES systems(id),
    zip_sha256     text NOT NULL,
    content_sha256 text NOT NULL,
    feed_version   text,
    start_date     date,
    end_date       date,
    first_seen     timestamptz NOT NULL,
    last_seen      timestamptz NOT NULL,
    archive_path   text NOT NULL,
    active         boolean NOT NULL DEFAULT false,
    UNIQUE (system_id, content_sha256)
);
CREATE UNIQUE INDEX feed_versions_one_active ON feed_versions (system_id) WHERE active;

CREATE TABLE gtfs_routes (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    route_id text NOT NULL, short_name text, long_name text, color text, text_color text,
    PRIMARY KEY (feed_version_id, route_id)
);
CREATE TABLE gtfs_stops (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    stop_id text NOT NULL, code text, name text, lat double precision, lon double precision,
    PRIMARY KEY (feed_version_id, stop_id)
);
CREATE TABLE gtfs_trips (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    trip_id text NOT NULL, route_id text, service_id text, headsign text,
    direction_id smallint, block_id text, shape_id text,
    PRIMARY KEY (feed_version_id, trip_id)
);
CREATE TABLE gtfs_stop_times (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    trip_id text NOT NULL, stop_sequence integer NOT NULL, stop_id text,
    arrival_time text, departure_time text,  -- HH:MM:SS, may exceed 24:00:00
    PRIMARY KEY (feed_version_id, trip_id, stop_sequence)
);
CREATE TABLE gtfs_shapes (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    shape_id text NOT NULL, sequence integer NOT NULL, lat double precision, lon double precision,
    PRIMARY KEY (feed_version_id, shape_id, sequence)
);
CREATE TABLE gtfs_calendar_dates (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    service_id text NOT NULL, date date NOT NULL, exception_type smallint,
    PRIMARY KEY (feed_version_id, service_id, date)
);
CREATE TABLE gtfs_calendar (
    feed_version_id integer NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    service_id text NOT NULL, days text, start_date date, end_date date,
    PRIMARY KEY (feed_version_id, service_id)
);

-- Realtime history, partitioned by month (partitions created by the collector)
CREATE TABLE vehicle_positions (
    system_id      smallint NOT NULL,
    vehicle_id     text NOT NULL,
    observed_at    timestamptz NOT NULL,  -- the vehicle's own timestamp, else the feed's
    feed_at        timestamptz NOT NULL,
    trip_id        text, route_id text, start_date text, start_time text,
    lat            double precision NOT NULL,
    lon            double precision NOT NULL,
    bearing        real, speed real,
    stop_id        text, stop_sequence integer,
    status         text, occupancy text,
    shape_index    smallint, distance_along real,
    PRIMARY KEY (system_id, vehicle_id, observed_at)
) PARTITION BY RANGE (observed_at);
CREATE INDEX vehicle_positions_trip ON vehicle_positions (system_id, trip_id, observed_at);
-- Catches rows outside the monthly partitions (e.g. a bus reporting a 1970 timestamp)
CREATE TABLE vehicle_positions_default PARTITION OF vehicle_positions DEFAULT;

-- A row only when a predicted time changes for a (trip, stop)
CREATE TABLE stop_predictions (
    system_id         smallint NOT NULL,
    trip_id           text NOT NULL,
    start_date        text NOT NULL,
    stop_key          text NOT NULL,
    observed_at       timestamptz NOT NULL,
    stop_id           text, stop_sequence integer,
    arrival_at        timestamptz, departure_at timestamptz,
    delay             integer,
    relationship      text, trip_relationship text,
    PRIMARY KEY (system_id, trip_id, start_date, stop_key, observed_at)
) PARTITION BY RANGE (observed_at);
CREATE INDEX stop_predictions_stop ON stop_predictions (system_id, stop_id, observed_at);
CREATE TABLE stop_predictions_default PARTITION OF stop_predictions DEFAULT;

CREATE TABLE alerts (
    system_id      smallint NOT NULL REFERENCES systems(id),
    alert_id       text NOT NULL,
    content_sha256 text NOT NULL,
    first_seen     timestamptz NOT NULL,
    last_seen      timestamptz NOT NULL,
    header text, description text, url text, cause text, effect text,
    route_ids text[], stop_ids text[], active_periods jsonb,
    PRIMARY KEY (system_id, alert_id, content_sha256)
);

-- Pre-built API responses, replaced in place
CREATE TABLE live_documents (
    system_id smallint NOT NULL REFERENCES systems(id),
    kind      text NOT NULL,
    etag      text NOT NULL,
    body_gzip bytea NOT NULL,
    built_at  timestamptz NOT NULL,
    PRIMARY KEY (system_id, kind)
);
"""

DOWNGRADE = """
DROP TABLE live_documents, alerts, stop_predictions, vehicle_positions,
    gtfs_calendar, gtfs_calendar_dates, gtfs_shapes, gtfs_stop_times, gtfs_trips, gtfs_stops, gtfs_routes,
    feed_versions, feed_fetches, systems;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
