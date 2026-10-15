"""Upcoming departures at stops: live predictions first, the timetable otherwise."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from transitlive.domain.model import StopTimeUpdate, Timetable, TripUpdate
from transitlive.domain.service_day import recent_service_days

WINDOW_SECONDS = 3 * 3600
LIVE_GRACE_SECONDS = 30  # keep showing a live departure for a moment after its time
DEFAULT_LIMIT = 8


@dataclass(frozen=True)
class StopDeparture:
    time: int
    trip_id: str
    route_id: str
    headsign: str
    live: bool
    delay: int | None = None
    cancelled: bool = False
    untracked: bool = False


def all_departures(
    tt: Timetable,
    trip_updates: Mapping[str, TripUpdate],
    now: float,
    untracked_trips: frozenset[str] = frozenset(),
    window: int = WINDOW_SECONDS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, list[StopDeparture]]:
    """Next departures for every stop in the timetable."""
    # Index live predictions by stop once, rather than per stop
    live_by_stop: dict[str, list[tuple[str, StopTimeUpdate]]] = defaultdict(list)
    for trip_id, tu in trip_updates.items():
        if tu.cancelled:
            continue
        for stu in tu.stop_updates:
            if stu.stop_id:
                live_by_stop[stu.stop_id].append((trip_id, stu))
    days = recent_service_days(tt, now)
    return {
        stop_id: _stop_departures(
            tt, trip_updates, stop_id, now, live_by_stop[stop_id], days, untracked_trips, window, limit
        )
        for stop_id in tt.stops
    }


def stop_departures(
    tt: Timetable,
    trip_updates: Mapping[str, TripUpdate],
    stop_id: str,
    now: float,
    untracked_trips: frozenset[str] = frozenset(),
    window: int = WINDOW_SECONDS,
    limit: int = DEFAULT_LIMIT,
) -> list[StopDeparture]:
    live = [
        (trip_id, stu)
        for trip_id, tu in trip_updates.items()
        if not tu.cancelled
        for stu in tu.stop_updates
        if stu.stop_id == stop_id
    ]
    return _stop_departures(
        tt, trip_updates, stop_id, now, live, recent_service_days(tt, now), untracked_trips, window, limit
    )


def _stop_departures(
    tt: Timetable,
    trip_updates: Mapping[str, TripUpdate],
    stop_id: str,
    now: float,
    live: list[tuple[str, StopTimeUpdate]],
    days: list[tuple[str, int, frozenset[str]]],
    untracked_trips: frozenset[str],
    window: int,
    limit: int,
) -> list[StopDeparture]:
    scheduled = tt.departures.get(stop_id, ())
    boardable = {d.trip_id for d in scheduled}
    out: list[StopDeparture] = []

    for trip_id, stu in live:
        # Only trips you can board here: not the stop where a trip ends
        if trip_id not in boardable or stu.relationship == "SKIPPED":
            continue
        t = stu.time
        if t is None or t < now - LIVE_GRACE_SECONDS or t > now + window:
            continue
        trip = tt.trips[trip_id]
        out.append(
            StopDeparture(
                time=t, trip_id=trip_id, route_id=trip.route_id, headsign=trip.headsign, live=True, delay=stu.delay
            )
        )

    for _key, base, services in days:
        for dep in scheduled:
            trip = tt.trips[dep.trip_id]
            if trip.service_id not in services:
                continue
            tu = trip_updates.get(dep.trip_id)
            if tu is not None and not tu.cancelled:
                continue  # the live prediction above covers it (or it has passed this stop)
            time = base + dep.secs
            if time < now or time > now + window:
                continue
            out.append(
                StopDeparture(
                    time=time,
                    trip_id=dep.trip_id,
                    route_id=trip.route_id,
                    headsign=trip.headsign,
                    live=False,
                    cancelled=tu is not None and tu.cancelled,
                    untracked=dep.trip_id in untracked_trips,
                )
            )

    out.sort(key=lambda d: d.time)
    return out[:limit]
