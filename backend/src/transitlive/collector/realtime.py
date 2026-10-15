"""Decode GTFS-Realtime protobuf feeds into domain objects."""

from __future__ import annotations

from urllib.parse import urlsplit

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as rt

from transitlive.domain.model import ActivePeriod, Alert, Snapshot, StopTimeUpdate, TripUpdate, Vehicle


class FeedError(ValueError):
    """The bytes are not a usable GTFS-Realtime feed."""


def _enum(msg: object, field: str) -> str | None:
    if not msg.HasField(field):  # type: ignore[attr-defined]
        return None
    descriptor = msg.DESCRIPTOR.fields_by_name[field].enum_type  # type: ignore[attr-defined]
    return str(descriptor.values_by_number[getattr(msg, field)].name)


def _opt(msg: object, field: str) -> object | None:
    return getattr(msg, field) if msg.HasField(field) else None  # type: ignore[attr-defined]


def _text(ts: rt.TranslatedString) -> str:
    if not ts.translation:
        return ""
    for t in ts.translation:
        if not t.language or t.language.startswith("en"):
            return str(t.text)
    return str(ts.translation[0].text)


def _http_url(url: str) -> str:
    """The URL if it's an absolute http(s) link, else "". Alert links end up as
    hrefs in the web app, where a javascript: URL would run script."""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return url if parts.scheme.lower() in ("http", "https") and parts.netloc else ""


def decode(feed: str, data: bytes) -> Snapshot:
    msg = rt.FeedMessage()
    try:
        msg.ParseFromString(data)
    except DecodeError as e:
        raise FeedError(f"{feed}: not a GTFS-Realtime message ({e})") from e
    if not msg.HasField("header"):
        raise FeedError(f"{feed}: missing header")

    vehicles: list[Vehicle] = []
    trip_updates: list[TripUpdate] = []
    alerts: list[Alert] = []
    for entity in msg.entity:
        if entity.HasField("vehicle") and entity.vehicle.HasField("position"):
            vp = entity.vehicle
            trip = vp.trip if vp.HasField("trip") else None
            vehicles.append(
                Vehicle(
                    vehicle_id=vp.vehicle.id or entity.id,
                    label=vp.vehicle.label or vp.vehicle.id or entity.id,
                    trip_id=(trip.trip_id or None) if trip else None,
                    route_id=(trip.route_id or None) if trip else None,
                    start_date=(trip.start_date or None) if trip else None,
                    start_time=(trip.start_time or None) if trip else None,
                    lat=vp.position.latitude,
                    lon=vp.position.longitude,
                    bearing=_opt(vp.position, "bearing"),  # type: ignore[arg-type]
                    speed=_opt(vp.position, "speed"),  # type: ignore[arg-type]
                    current_stop_sequence=_opt(vp, "current_stop_sequence"),  # type: ignore[arg-type]
                    stop_id=vp.stop_id or None,
                    status=_enum(vp, "current_status"),
                    occupancy=_enum(vp, "occupancy_status"),
                    timestamp=_opt(vp, "timestamp"),  # type: ignore[arg-type]
                )
            )
        if entity.HasField("trip_update") and entity.trip_update.trip.trip_id:
            tu = entity.trip_update
            updates = []
            for s in tu.stop_time_update:
                arr = s.arrival if s.HasField("arrival") else None
                dep = s.departure if s.HasField("departure") else None
                updates.append(
                    StopTimeUpdate(
                        stop_sequence=_opt(s, "stop_sequence"),  # type: ignore[arg-type]
                        stop_id=s.stop_id or None,
                        arrival_time=(_opt(arr, "time") if arr else None),  # type: ignore[arg-type]
                        arrival_delay=(_opt(arr, "delay") if arr else None),  # type: ignore[arg-type]
                        departure_time=(_opt(dep, "time") if dep else None),  # type: ignore[arg-type]
                        departure_delay=(_opt(dep, "delay") if dep else None),  # type: ignore[arg-type]
                        relationship=_enum(s, "schedule_relationship") or "SCHEDULED",
                    )
                )
            trip_updates.append(
                TripUpdate(
                    trip_id=tu.trip.trip_id,
                    route_id=tu.trip.route_id or None,
                    start_date=tu.trip.start_date or None,
                    start_time=tu.trip.start_time or None,
                    relationship=_enum(tu.trip, "schedule_relationship") or "SCHEDULED",
                    stop_updates=tuple(updates),
                    vehicle_id=(tu.vehicle.id or None) if tu.HasField("vehicle") else None,
                    timestamp=_opt(tu, "timestamp"),  # type: ignore[arg-type]
                )
            )
        if entity.HasField("alert"):
            a = entity.alert
            alerts.append(
                Alert(
                    id=entity.id,
                    header=_text(a.header_text),
                    description=_text(a.description_text),
                    url=_http_url(_text(a.url)),
                    cause=_enum(a, "cause"),
                    effect=_enum(a, "effect"),
                    active_periods=tuple(
                        ActivePeriod(
                            start=p.start if p.HasField("start") else None, end=p.end if p.HasField("end") else None
                        )
                        for p in a.active_period
                    ),
                    route_ids=tuple(dict.fromkeys(e.route_id for e in a.informed_entity if e.route_id)),
                    stop_ids=tuple(dict.fromkeys(e.stop_id for e in a.informed_entity if e.stop_id)),
                )
            )
    return Snapshot(
        feed=feed,
        header_timestamp=int(msg.header.timestamp),
        vehicles=tuple(vehicles),
        trip_updates=tuple(trip_updates),
        alerts=tuple(alerts),
    )
