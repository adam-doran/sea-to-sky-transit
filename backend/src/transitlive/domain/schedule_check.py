"""Cross-check the timetable against the live feeds.

For each route: which trips should be on the road now, is a bus reporting each
one, which are cancelled, and when is the next departure (and from where).
Also: buses running trips that aren't in the timetable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from transitlive.domain.model import Timetable, TripUpdate, Vehicle
from transitlive.domain.service_day import recent_service_days
from transitlive.domain.waiting import predicted_start, waiting_info

UNTRACKED_GRACE_SECONDS = 180  # buses can log in a few minutes after their trip starts


@dataclass(frozen=True)
class TripRef:
    trip_id: str
    route_id: str
    headsign: str
    start: int
    end: int


@dataclass(frozen=True)
class NextDeparture:
    time: int  # predicted if known, else scheduled
    scheduled: int | None
    trip_id: str
    stop_id: str | None


@dataclass
class RouteStatus:
    active: int = 0  # trips that should be on the road now
    tracked: int = 0
    untracked: list[TripRef] = field(default_factory=list)
    cancelled: list[TripRef] = field(default_factory=list)
    next: NextDeparture | None = None

    def consider(self, cand: NextDeparture) -> None:
        if self.next is None or cand.time < self.next.time:
            self.next = cand


@dataclass(frozen=True)
class ScheduleCheck:
    routes: dict[str, RouteStatus]
    untracked_trips: frozenset[str]
    unscheduled: tuple[Vehicle, ...]  # buses on trips missing from the timetable
    unknown_trip_ratio: float  # share of reporting buses whose trip isn't in the timetable


def vehicle_route(tt: Timetable, v: Vehicle) -> str | None:
    if v.route_id:
        return v.route_id
    trip = tt.trips.get(v.trip_id or "")
    return trip.route_id if trip else None


def vehicle_block(tt: Timetable, v: Vehicle) -> str | None:
    if not v.trip_id:
        return None
    trip = tt.trips.get(v.trip_id)
    if trip is not None:
        return trip.block_id or None
    # Trips missing from the timetable: BC Transit trip IDs end in the block ID
    # ("2516528:14637469:14647750"). A heuristic, so only used as a fallback.
    parts = v.trip_id.split(":")
    return parts[2] if len(parts) == 3 else None


def schedule_check(
    tt: Timetable,
    vehicles: Sequence[Vehicle],
    trip_updates: Mapping[str, TripUpdate],
    now: float,
) -> ScheduleCheck:
    tracked_trips = {v.trip_id for v in vehicles if v.trip_id}
    # A bus that finishes a trip early logs straight into the next trip of its
    # block, so a trip only counts as untracked if no bus is on its block at all.
    tracked_blocks = {b for v in vehicles if (b := vehicle_block(tt, v))}
    routes = {rid: RouteStatus() for rid in tt.routes}
    untracked: set[str] = set()

    for _key, base, services in recent_service_days(tt, now):
        for trip in tt.trips.values():
            status = routes.get(trip.route_id)
            if status is None or trip.service_id not in services:
                continue
            start = base + trip.start_secs
            end = base + trip.end_secs
            if start > now:
                predicted = predicted_start(tt, trip_updates, trip.id)
                status.consider(
                    NextDeparture(
                        time=predicted if predicted is not None else start,
                        scheduled=start,
                        trip_id=trip.id,
                        stop_id=trip.first_stop_id,
                    )
                )
                continue
            if end < now:
                continue
            ref = TripRef(trip_id=trip.id, route_id=trip.route_id, headsign=trip.headsign, start=start, end=end)
            tu = trip_updates.get(trip.id)
            if tu is not None and tu.cancelled:
                status.cancelled.append(ref)
                continue
            status.active += 1
            if trip.id in tracked_trips or (trip.block_id and trip.block_id in tracked_blocks):
                status.tracked += 1
            elif now - start > UNTRACKED_GRACE_SECONDS:
                status.untracked.append(ref)
                untracked.add(trip.id)

    # A bus still waiting at its first stop hasn't departed, even if its
    # scheduled start has passed: it stays the route's next departure.
    for v in vehicles:
        w = waiting_info(tt, trip_updates, v, now)
        rid = vehicle_route(tt, v)
        if w is not None and w.departs is not None and rid in routes and v.trip_id:
            routes[rid].consider(
                NextDeparture(time=w.departs, scheduled=w.scheduled, trip_id=v.trip_id, stop_id=w.stop_id)
            )

    with_trips = [v for v in vehicles if v.trip_id]
    unscheduled = tuple(v for v in with_trips if v.trip_id not in tt.trips)
    ratio = len(unscheduled) / len(with_trips) if with_trips else 0.0
    return ScheduleCheck(
        routes=routes, untracked_trips=frozenset(untracked), unscheduled=unscheduled, unknown_trip_ratio=ratio
    )
