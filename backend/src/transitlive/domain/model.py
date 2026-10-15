"""Typed timetable and realtime data that the domain logic works on.

Times are Unix epoch seconds. Timetable times ("secs") are seconds after the
GTFS service-day start, which can exceed 24 h for trips running past midnight.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LatLon = tuple[float, float]


@dataclass(frozen=True)
class Route:
    id: str
    short: str
    long: str
    color: str
    text_color: str
    shapes: tuple[tuple[LatLon, ...], ...]


@dataclass(frozen=True)
class Stop:
    id: str
    code: str
    name: str
    lat: float
    lon: float
    routes: tuple[str, ...]


@dataclass(frozen=True)
class Trip:
    id: str
    route_id: str
    headsign: str
    direction: int
    service_id: str
    start_secs: int
    end_secs: int
    block_id: str
    shape_index: int | None
    first_stop_id: str


@dataclass(frozen=True)
class Departure:
    """A scheduled departure from a stop (the last stop of a trip is excluded)."""

    secs: int
    trip_id: str


@dataclass(frozen=True)
class Timetable:
    agency_name: str
    timezone: str
    feed_version: str
    start_date: str  # YYYYMMDD
    end_date: str
    routes: dict[str, Route]  # in display order
    stops: dict[str, Stop]
    trips: dict[str, Trip]
    departures: dict[str, tuple[Departure, ...]]  # stop id -> sorted by secs
    services: dict[str, frozenset[str]]  # YYYYMMDD -> active service ids


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    label: str
    trip_id: str | None
    route_id: str | None
    start_date: str | None
    start_time: str | None
    lat: float
    lon: float
    bearing: float | None
    speed: float | None  # metres per second
    current_stop_sequence: int | None
    stop_id: str | None
    status: str | None  # INCOMING_AT | STOPPED_AT | IN_TRANSIT_TO
    occupancy: str | None
    timestamp: int | None


@dataclass(frozen=True)
class StopTimeUpdate:
    stop_sequence: int | None
    stop_id: str | None
    arrival_time: int | None
    arrival_delay: int | None
    departure_time: int | None
    departure_delay: int | None
    relationship: str = "SCHEDULED"  # SCHEDULED | SKIPPED | NO_DATA

    @property
    def time(self) -> int | None:
        return self.departure_time or self.arrival_time

    @property
    def delay(self) -> int | None:
        return self.departure_delay if self.departure_delay is not None else self.arrival_delay


@dataclass(frozen=True)
class TripUpdate:
    trip_id: str
    route_id: str | None
    start_date: str | None
    start_time: str | None
    relationship: str  # SCHEDULED | ADDED | UNSCHEDULED | CANCELED
    stop_updates: tuple[StopTimeUpdate, ...]
    vehicle_id: str | None = None
    timestamp: int | None = None

    @property
    def cancelled(self) -> bool:
        return self.relationship == "CANCELED"


@dataclass(frozen=True)
class ActivePeriod:
    start: int | None
    end: int | None


@dataclass(frozen=True)
class Alert:
    id: str
    header: str
    description: str
    url: str
    cause: str | None
    effect: str | None
    active_periods: tuple[ActivePeriod, ...]
    route_ids: tuple[str, ...]
    stop_ids: tuple[str, ...]

    def active_at(self, now: float) -> bool:
        if not self.active_periods:
            return True
        return any((p.start is None or p.start <= now) and (p.end is None or p.end >= now) for p in self.active_periods)


@dataclass(frozen=True)
class Snapshot:
    """One decoded realtime feed fetch."""

    feed: str
    header_timestamp: int
    vehicles: tuple[Vehicle, ...] = ()
    trip_updates: tuple[TripUpdate, ...] = ()
    alerts: tuple[Alert, ...] = ()


@dataclass
class LiveState:
    """Latest realtime data for one system."""

    vehicles: tuple[Vehicle, ...] = ()
    trip_updates: dict[str, TripUpdate] = field(default_factory=dict)
    alerts: tuple[Alert, ...] = ()
    vehicles_at: int | None = None
    trip_updates_at: int | None = None
    alerts_at: int | None = None
