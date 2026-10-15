"""Buses waiting to depart.

A bus counts as waiting when it is stationary and either its trip hasn't
started yet or it is still at the trip's first stop. Buses parked at a transit
centre report like this, already logged into their next trip.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from transitlive.domain.model import Timetable, TripUpdate, Vehicle
from transitlive.domain.service_day import gtfs_time, local_date, service_day_start

STATIONARY_MPS = 1.0  # below ~4 km/h a bus counts as stationary


@dataclass(frozen=True)
class Waiting:
    departs: int | None  # predicted departure if known, else scheduled
    scheduled: int | None
    predicted: int | None
    stop_id: str | None  # where the trip starts


def scheduled_start(
    tt: Timetable, trip_id: str, start_date: str | None, start_time: str | None, now: float
) -> int | None:
    if start_date and start_time:
        return gtfs_time(start_date, start_time, tt.timezone)
    trip = tt.trips.get(trip_id)
    if trip is None:
        return None
    return service_day_start(local_date(now, tt.timezone), tt.timezone) + trip.start_secs


def predicted_start(tt: Timetable, trip_updates: Mapping[str, TripUpdate], trip_id: str) -> int | None:
    """Live predicted departure from a trip's first stop, if the feed has one."""
    trip = tt.trips.get(trip_id)
    tu = trip_updates.get(trip_id)
    if trip is None or tu is None:
        return None
    for stu in tu.stop_updates:
        if stu.stop_id == trip.first_stop_id and stu.departure_time:
            return stu.departure_time
    return None


def waiting_info(tt: Timetable, trip_updates: Mapping[str, TripUpdate], v: Vehicle, now: float) -> Waiting | None:
    if (v.speed or 0) > STATIONARY_MPS or not v.trip_id:
        return None
    scheduled = scheduled_start(tt, v.trip_id, v.start_date, v.start_time, now)
    predicted = predicted_start(tt, trip_updates, v.trip_id)
    departs = predicted if predicted is not None else scheduled
    not_started = departs is not None and departs > now
    at_first_stop = v.current_stop_sequence is not None and v.current_stop_sequence <= 1
    if not not_started and not at_first_stop:
        return None
    trip = tt.trips.get(v.trip_id)
    return Waiting(
        departs=departs, scheduled=scheduled, predicted=predicted, stop_id=trip.first_stop_id if trip else None
    )
