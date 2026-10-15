"""Build small GTFS feeds and realtime objects in memory for tests."""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from typing import Any
from zoneinfo import ZoneInfo

from transitlive.domain.model import StopTimeUpdate, Timetable, TripUpdate, Vehicle
from transitlive.gtfs.compile import compile_timetable
from transitlive.gtfs.load import read_gtfs_zip

TZ = "America/Vancouver"


def at(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> int:
    """Epoch seconds for a local Vancouver time."""
    return int(dt.datetime(y, mo, d, h, mi, s, tzinfo=ZoneInfo(TZ)).timestamp())


def gtfs_zip(tables: dict[str, list[dict[str, Any]]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, rows in tables.items():
            out = io.StringIO()
            if rows:
                writer = csv.DictWriter(out, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            zf.writestr(f"{name}.txt", out.getvalue())
    return buf.getvalue()


class FeedBuilder:
    """A tiny transit system. Stops lie along a north-south line, 0.001 deg
    latitude (~111 m) apart, unless given coordinates."""

    def __init__(self, service_dates: tuple[str, ...] = ("20261014",)) -> None:
        self.routes: list[dict[str, Any]] = []
        self.stops: dict[str, tuple[float, float]] = {}
        self.trips: list[dict[str, Any]] = []
        self.stop_times: list[dict[str, Any]] = []
        self.shapes: list[dict[str, Any]] = []
        self.service_dates = service_dates

    def route(self, rid: str, short: str, color: str = "004B8D") -> FeedBuilder:
        self.routes.append(
            {
                "route_id": rid,
                "route_short_name": short,
                "route_long_name": f"Route {short}",
                "route_type": 3,
                "route_color": color,
                "route_text_color": "FFFFFF",
            }
        )
        return self

    def stop(self, sid: str, lat: float, lon: float = -123.15) -> FeedBuilder:
        self.stops[sid] = (lat, lon)
        return self

    def shape(self, shape_id: str, points: list[tuple[float, float]]) -> FeedBuilder:
        for i, (lat, lon) in enumerate(points):
            self.shapes.append({"shape_id": shape_id, "shape_pt_lat": lat, "shape_pt_lon": lon, "shape_pt_sequence": i})
        return self

    def trip(
        self,
        tid: str,
        rid: str,
        times: list[tuple[str, str]],
        *,
        block: str = "",
        shape: str = "",
        headsign: str = "Downtown",
        service: str = "S1",
    ) -> FeedBuilder:
        self.trips.append(
            {
                "route_id": rid,
                "service_id": service,
                "trip_id": tid,
                "trip_headsign": headsign,
                "shape_id": shape,
                "block_id": block,
                "direction_id": 0,
            }
        )
        for seq, (stop_id, hms) in enumerate(times, start=1):
            self.stop_times.append(
                {
                    "trip_id": tid,
                    "arrival_time": hms,
                    "departure_time": hms,
                    "stop_id": stop_id,
                    "stop_sequence": seq,
                }
            )
        return self

    def build(self) -> Timetable:
        tables: dict[str, list[dict[str, Any]]] = {
            "agency": [
                {
                    "agency_id": "0",
                    "agency_name": "Test Transit",
                    "agency_url": "https://example.org",
                    "agency_timezone": TZ,
                }
            ],
            "feed_info": [
                {
                    "feed_publisher_name": "Test",
                    "feed_version": "v1",
                    "feed_start_date": self.service_dates[0],
                    "feed_end_date": self.service_dates[-1],
                }
            ],
            "routes": self.routes,
            "stops": [
                {"stop_id": s, "stop_name": f"Stop {s}", "stop_lat": lat, "stop_lon": lon, "stop_code": s}
                for s, (lat, lon) in self.stops.items()
            ],
            "trips": self.trips,
            "stop_times": self.stop_times,
            "calendar_dates": [{"service_id": "S1", "date": d, "exception_type": 1} for d in self.service_dates],
        }
        if self.shapes:
            tables["shapes"] = self.shapes
        return compile_timetable(read_gtfs_zip(gtfs_zip(tables)))


def vehicle(
    vid: str = "V1",
    *,
    trip: str | None = "T1",
    route: str | None = "R1",
    lat: float = 49.700,
    lon: float = -123.15,
    speed: float | None = 10.0,
    seq: int | None = 3,
    start_date: str | None = None,
    start_time: str | None = None,
    timestamp: int | None = None,
) -> Vehicle:
    return Vehicle(
        vehicle_id=vid,
        label=vid,
        trip_id=trip,
        route_id=route,
        start_date=start_date,
        start_time=start_time,
        lat=lat,
        lon=lon,
        bearing=None,
        speed=speed,
        current_stop_sequence=seq,
        stop_id=None,
        status="IN_TRANSIT_TO",
        occupancy=None,
        timestamp=timestamp,
    )


def stu(stop_id: str, t: int | None, delay: int | None = 0, relationship: str = "SCHEDULED") -> StopTimeUpdate:
    return StopTimeUpdate(
        stop_sequence=None,
        stop_id=stop_id,
        arrival_time=t,
        arrival_delay=delay,
        departure_time=t,
        departure_delay=delay,
        relationship=relationship,
    )


def trip_update(trip_id: str, *updates: StopTimeUpdate, cancelled: bool = False, route: str = "R1") -> TripUpdate:
    return TripUpdate(
        trip_id=trip_id,
        route_id=route,
        start_date=None,
        start_time=None,
        relationship="CANCELED" if cancelled else "SCHEDULED",
        stop_updates=tuple(updates),
    )


def simple_line() -> FeedBuilder:
    """Route R1 through stops A..D, 0.001 deg (~111 m) apart, on a straight shape."""
    fb = FeedBuilder().route("R1", "1")
    for i, sid in enumerate("ABCD"):
        fb.stop(sid, 49.700 + i * 0.001)
    fb.shape("SH1", [(49.700 + i * 0.0005, -123.15) for i in range(7)])
    return fb
