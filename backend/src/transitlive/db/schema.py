"""Table definitions used by the collector and API.

The database itself is created by the Alembic migrations in db/migrations
(explicit SQL, because two tables are partitioned by month). Keep the two in
step; tests/integration checks every table round-trips.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

systems = Table(
    "systems",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("slug", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("operator_id", Integer, nullable=False),
    Column("timezone", Text, nullable=False),
)

feed_fetches = Table(
    "feed_fetches",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("system_id", SmallInteger, nullable=False),
    Column("feed", Text, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("url", Text, nullable=False),
    Column("http_status", SmallInteger),
    Column("bytes", Integer),
    Column("sha256", Text),
    Column("header_at", DateTime(timezone=True)),
    Column("latency_ms", Integer),
    Column("is_new", Boolean, nullable=False, server_default="false"),
    Column("error", Text),
)

feed_versions = Table(
    "feed_versions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("system_id", SmallInteger, nullable=False),
    Column("zip_sha256", Text, nullable=False),
    Column("content_sha256", Text, nullable=False),
    Column("feed_version", Text),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("first_seen", DateTime(timezone=True), nullable=False),
    Column("last_seen", DateTime(timezone=True), nullable=False),
    Column("archive_path", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default="false"),
)

gtfs_routes = Table(
    "gtfs_routes",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("route_id", Text, primary_key=True),
    Column("short_name", Text),
    Column("long_name", Text),
    Column("color", Text),
    Column("text_color", Text),
)
gtfs_stops = Table(
    "gtfs_stops",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("stop_id", Text, primary_key=True),
    Column("code", Text),
    Column("name", Text),
    Column("lat", Float),
    Column("lon", Float),
)
gtfs_trips = Table(
    "gtfs_trips",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("trip_id", Text, primary_key=True),
    Column("route_id", Text),
    Column("service_id", Text),
    Column("headsign", Text),
    Column("direction_id", SmallInteger),
    Column("block_id", Text),
    Column("shape_id", Text),
)
gtfs_stop_times = Table(
    "gtfs_stop_times",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("trip_id", Text, primary_key=True),
    Column("stop_sequence", Integer, primary_key=True),
    Column("stop_id", Text),
    Column("arrival_time", Text),
    Column("departure_time", Text),
)
gtfs_shapes = Table(
    "gtfs_shapes",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("shape_id", Text, primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("lat", Float),
    Column("lon", Float),
)
gtfs_calendar_dates = Table(
    "gtfs_calendar_dates",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("service_id", Text, primary_key=True),
    Column("date", Date, primary_key=True),
    Column("exception_type", SmallInteger),
)
gtfs_calendar = Table(
    "gtfs_calendar",
    metadata,
    Column("feed_version_id", Integer, primary_key=True),
    Column("service_id", Text, primary_key=True),
    Column("days", Text),  # seven 0/1 characters, Monday first
    Column("start_date", Date),
    Column("end_date", Date),
)

vehicle_positions = Table(
    "vehicle_positions",
    metadata,
    Column("system_id", SmallInteger, primary_key=True),
    Column("vehicle_id", Text, primary_key=True),
    Column("observed_at", DateTime(timezone=True), primary_key=True),
    Column("feed_at", DateTime(timezone=True), nullable=False),
    Column("trip_id", Text),
    Column("route_id", Text),
    Column("start_date", Text),
    Column("start_time", Text),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("bearing", Float),
    Column("speed", Float),
    Column("stop_id", Text),
    Column("stop_sequence", Integer),
    Column("status", Text),
    Column("occupancy", Text),
    Column("shape_index", SmallInteger),
    Column("distance_along", Float),
)

stop_predictions = Table(
    "stop_predictions",
    metadata,
    Column("system_id", SmallInteger, primary_key=True),
    Column("trip_id", Text, primary_key=True),
    Column("start_date", Text, primary_key=True),
    Column("stop_key", Text, primary_key=True),  # stop sequence if given, else stop id
    Column("observed_at", DateTime(timezone=True), primary_key=True),
    Column("stop_id", Text),
    Column("stop_sequence", Integer),
    Column("arrival_at", DateTime(timezone=True)),
    Column("departure_at", DateTime(timezone=True)),
    Column("delay", Integer),
    Column("relationship", Text),
    Column("trip_relationship", Text),
)

alerts = Table(
    "alerts",
    metadata,
    Column("system_id", SmallInteger, primary_key=True),
    Column("alert_id", Text, primary_key=True),
    Column("content_sha256", Text, primary_key=True),
    Column("first_seen", DateTime(timezone=True), nullable=False),
    Column("last_seen", DateTime(timezone=True), nullable=False),
    Column("header", Text),
    Column("description", Text),
    Column("url", Text),
    Column("cause", Text),
    Column("effect", Text),
    Column("route_ids", ARRAY(Text)),
    Column("stop_ids", ARRAY(Text)),
    Column("active_periods", JSONB),
)

live_documents = Table(
    "live_documents",
    metadata,
    Column("system_id", SmallInteger, primary_key=True),
    Column("kind", Text, primary_key=True),  # static | live | departures
    Column("etag", Text, nullable=False),
    Column("body_gzip", LargeBinary, nullable=False),
    Column("built_at", DateTime(timezone=True), nullable=False),
)
