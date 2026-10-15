"""Compile static GTFS rows into the Timetable the domain logic uses.

Ported from the prototype's scripts/build_gtfs.py.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict

from transitlive.domain.model import Departure, LatLon, Route, Stop, Timetable, Trip
from transitlive.domain.service_day import hms_to_secs
from transitlive.gtfs.load import GtfsFeed

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_HEX_COLOR = re.compile(r"[0-9A-Fa-f]{6}")


def _route_sort_key(short: str) -> tuple[int, str]:
    return (len(short), short)


def _color(value: str | None, default: str) -> str:
    """A GTFS colour as #RRGGBB, or the default if it isn't six hex digits.
    The web app puts it in styles, so nothing else gets through."""
    return "#" + (value if value and _HEX_COLOR.fullmatch(value) else default).upper()


def compile_timetable(feed: GtfsFeed, default_timezone: str = "America/Vancouver") -> Timetable:
    agency = feed.table("agency")
    feed_info = feed.table("feed_info")

    # Shapes: shape id -> [(lat, lon), ...] in sequence order
    points: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for p in feed.table("shapes"):
        points[p["shape_id"]].append(
            (int(p["shape_pt_sequence"]), round(float(p["shape_pt_lat"]), 5), round(float(p["shape_pt_lon"]), 5))
        )
    shape_coords: dict[str, tuple[LatLon, ...]] = {
        sid: tuple((lat, lon) for _, lat, lon in sorted(pts)) for sid, pts in points.items()
    }

    trips_rows = feed.table("trips")
    route_shape_ids: dict[str, list[str]] = defaultdict(list)
    for t in trips_rows:
        sid = t.get("shape_id", "")
        if sid in shape_coords and sid not in route_shape_ids[t["route_id"]]:
            route_shape_ids[t["route_id"]].append(sid)
    for ids in route_shape_ids.values():
        ids.sort()

    # Stop times grouped by trip, in sequence order
    by_trip: dict[str, list[tuple[int, str, int]]] = defaultdict(list)  # (seq, stop_id, secs)
    for st in feed.table("stop_times"):
        hms = st.get("departure_time") or st.get("arrival_time")
        if not hms:
            continue
        by_trip[st["trip_id"]].append((int(st["stop_sequence"]), st["stop_id"], hms_to_secs(hms)))

    trips: dict[str, Trip] = {}
    departures: dict[str, list[Departure]] = defaultdict(list)
    stop_routes: dict[str, set[str]] = defaultdict(set)
    for row in trips_rows:
        times = sorted(by_trip.get(row["trip_id"], []))
        if not times:
            continue
        shape_ids = route_shape_ids.get(row["route_id"], [])
        sid = row.get("shape_id", "")
        trip = Trip(
            id=row["trip_id"],
            route_id=row["route_id"],
            headsign=row.get("trip_headsign", ""),
            direction=int(row.get("direction_id") or 0),
            service_id=row["service_id"],
            start_secs=min(s for _, _, s in times),
            end_secs=max(s for _, _, s in times),
            block_id=row.get("block_id", ""),
            shape_index=shape_ids.index(sid) if sid in shape_ids else None,
            first_stop_id=times[0][1],
        )
        trips[trip.id] = trip
        # The last stop of a trip is an arrival, not somewhere you can board
        for _, stop_id, secs in times[:-1]:
            departures[stop_id].append(Departure(secs=secs, trip_id=trip.id))
            stop_routes[stop_id].add(trip.route_id)

    routes = {
        r["route_id"]: Route(
            id=r["route_id"],
            short=r.get("route_short_name", ""),
            long=r.get("route_long_name", ""),
            color=_color(r.get("route_color"), "666666"),
            text_color=_color(r.get("route_text_color"), "FFFFFF"),
            shapes=tuple(shape_coords[s] for s in route_shape_ids.get(r["route_id"], [])),
        )
        for r in sorted(feed.table("routes"), key=lambda r: _route_sort_key(r.get("route_short_name", "")))
    }

    order = {rid: i for i, rid in enumerate(routes)}
    stops = {
        s["stop_id"]: Stop(
            id=s["stop_id"],
            code=s.get("stop_code", ""),
            name=s["stop_name"],
            lat=round(float(s["stop_lat"]), 5),
            lon=round(float(s["stop_lon"]), 5),
            routes=tuple(sorted(stop_routes[s["stop_id"]], key=lambda r: order.get(r, 999))),
        )
        for s in feed.table("stops")
        if s.get("stop_lat") and s["stop_id"] in stop_routes
    }

    return Timetable(
        agency_name=agency[0].get("agency_name", "") if agency else "",
        timezone=(agency[0].get("agency_timezone") if agency else None) or default_timezone,
        feed_version=feed_info[0].get("feed_version", "") if feed_info else "",
        start_date=feed_info[0].get("feed_start_date", "") if feed_info else "",
        end_date=feed_info[0].get("feed_end_date", "") if feed_info else "",
        routes=routes,
        stops=stops,
        trips=trips,
        departures={sid: tuple(sorted(d, key=lambda x: x.secs)) for sid, d in departures.items()},
        services=_expand_services(feed),
    )


def _expand_services(feed: GtfsFeed) -> dict[str, frozenset[str]]:
    services: dict[str, set[str]] = defaultdict(set)
    for c in feed.table("calendar"):
        day = dt.datetime.strptime(c["start_date"], "%Y%m%d").date()
        end = dt.datetime.strptime(c["end_date"], "%Y%m%d").date()
        while day <= end:
            if c.get(WEEKDAYS[day.weekday()]) == "1":
                services[day.strftime("%Y%m%d")].add(c["service_id"])
            day += dt.timedelta(days=1)
    for cd in feed.table("calendar_dates"):
        if cd["exception_type"] == "1":
            services[cd["date"]].add(cd["service_id"])
        else:
            services[cd["date"]].discard(cd["service_id"])
    return {d: frozenset(ids) for d, ids in sorted(services.items()) if ids}
