"""The API's response shapes: the contract with the web app.

The collector builds documents as plain dicts (live/runtime.py); the tests
validate them against these models, and the web app's TypeScript types are
generated from the OpenAPI schema these produce.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemInfo(Model):
    slug: str
    name: str
    timezone: str


class TimetableInfo(Model):
    feed_version: str
    start_date: str
    end_date: str


class Shape(Model):
    coords: list[tuple[float, float]]  # [lat, lon]
    length_m: float
    closed: bool


class RouteInfo(Model):
    id: str
    short: str
    long: str
    color: str
    text_color: str
    shapes: list[Shape]


class StopInfo(Model):
    id: str
    code: str
    name: str
    lat: float
    lon: float
    routes: list[str]


class StaticDocument(Model):
    system: SystemInfo
    timetable: TimetableInfo
    routes: list[RouteInfo]
    stops: list[StopInfo]
    route_runs: dict[str, Any]  # GeoJSON FeatureCollection; features carry a "routes" list


class FeedTimes(Model):
    vehicles_at: int | None
    trip_updates_at: int | None
    alerts_at: int | None


class TimetableStatus(Model):
    feed_version: str
    out_of_date: bool
    unknown_trip_ratio: float


class Waiting(Model):
    departs: int | None
    scheduled: int | None
    predicted: int | None
    stop_id: str | None


class Track(Model):
    shape_index: int
    distance_along: float  # metres along the shape; keeps counting past the end on closed loops
    lat: float
    lon: float
    glide: bool


class VehicleInfo(Model):
    id: str
    label: str
    route_id: str | None
    trip_id: str | None
    headsign: str | None
    lat: float
    lon: float
    bearing: float | None
    speed: float | None
    status: str | None
    stop_id: str | None
    occupancy: str | None
    timestamp: int | None
    waiting: Waiting | None
    track: Track | None


class NextDeparture(Model):
    time: int
    scheduled: int | None
    trip_id: str
    stop_id: str | None


class RouteSummary(Model):
    id: str
    moving: int
    waiting: int
    scheduled_now: int
    untracked: int
    cancelled: int
    next: NextDeparture | None


class Issue(Model):
    kind: Literal["untracked", "cancelled", "extra"]
    route_id: str | None
    trip_id: str | None
    headsign: str | None
    start: int | None
    end: int | None
    vehicle_id: str | None
    start_time: str | None = None


class AlertInfo(Model):
    id: str
    header: str
    description: str
    url: str
    effect: str | None
    route_ids: list[str]
    stop_ids: list[str]


class LiveDocument(Model):
    system: SystemInfo
    generated_at: int
    feeds: FeedTimes
    timetable: TimetableStatus
    vehicles: list[VehicleInfo]
    routes: list[RouteSummary]
    issues: list[Issue]
    alerts: list[AlertInfo]


class StopDeparture(Model):
    time: int
    trip_id: str
    route_id: str
    headsign: str
    live: bool
    delay: int | None
    cancelled: bool
    untracked: bool


class DeparturesDocument(Model):
    system: SystemInfo
    generated_at: int
    trip_updates_at: int | None
    stops: dict[str, list[StopDeparture]]


class FeedHealth(Model):
    system: str
    feed: str
    last_success: str | None
    last_header: str | None
    age_seconds: float | None
    stale: bool


class Health(Model):
    ok: bool
    feeds: list[FeedHealth]
    timetables: dict[str, dict[str, Any]]
