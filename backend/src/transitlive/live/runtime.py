"""Per-system live state, and the documents the API serves.

SystemRuntime holds the active timetable and the latest realtime snapshots
for one system. It does no I/O, so the collector, replay mode and tests all
drive it the same way: apply snapshots, then build documents.

Documents:
    static      routes, shapes, stops and shared-road runs (changes with the timetable)
    live        buses, route summaries, schedule-check issues, alerts (every vehicle fetch)
    departures  next departures at every stop (every trip-update fetch)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from transitlive.config import System
from transitlive.domain.departures import all_departures
from transitlive.domain.model import LiveState, Snapshot, Timetable, Vehicle
from transitlive.domain.route_runs import build_route_runs, route_runs_geojson
from transitlive.domain.schedule_check import ScheduleCheck, schedule_check, vehicle_route
from transitlive.domain.shape_track import ShapeTracker, TrackPosition, build_geom
from transitlive.domain.waiting import waiting_info

# When this share of reporting buses run trips missing from the timetable,
# several checks in a row, the timetable is treated as out of date.
MISMATCH_RATIO = 0.2
MISMATCH_STRIKES = 3


@dataclass
class SystemRuntime:
    system: System
    timetable: Timetable
    timetable_version_id: int | None = None
    live: LiveState = field(default_factory=LiveState)
    tracks: dict[str, TrackPosition | None] = field(default_factory=dict)
    mismatch_strikes: int = 0
    tracker: ShapeTracker = field(init=False)

    def __post_init__(self) -> None:
        self.tracker = ShapeTracker(self.timetable)

    # ---- inputs ----

    def set_timetable(self, tt: Timetable, version_id: int | None = None) -> None:
        self.timetable = tt
        self.timetable_version_id = version_id
        self.tracker = ShapeTracker(tt)
        self.tracks = {}
        self.mismatch_strikes = 0

    def apply(self, snap: Snapshot) -> None:
        if snap.feed == "vehicleupdates":
            self.live.vehicles = snap.vehicles
            self.live.vehicles_at = snap.header_timestamp
            self.tracks = {v.vehicle_id: self.tracker.update(v) for v in snap.vehicles}
            self.tracker.forget_missing(set(self.tracks))
            with_trips = [v for v in snap.vehicles if v.trip_id]
            unknown = sum(1 for v in with_trips if v.trip_id not in self.timetable.trips)
            if with_trips and unknown / len(with_trips) > MISMATCH_RATIO:
                self.mismatch_strikes += 1
            else:
                self.mismatch_strikes = 0
        elif snap.feed == "tripupdates":
            self.live.trip_updates = {tu.trip_id: tu for tu in snap.trip_updates}
            self.live.trip_updates_at = snap.header_timestamp
        elif snap.feed == "alerts":
            self.live.alerts = snap.alerts
            self.live.alerts_at = snap.header_timestamp

    @property
    def timetable_out_of_date(self) -> bool:
        return self.mismatch_strikes >= MISMATCH_STRIKES

    def check(self, now: float) -> ScheduleCheck:
        return schedule_check(self.timetable, self.live.vehicles, self.live.trip_updates, now)

    # ---- documents ----

    def _system(self) -> dict[str, Any]:
        s = self.system
        return {"slug": s.slug, "name": s.name, "timezone": s.timezone}

    def static_document(self) -> dict[str, Any]:
        tt = self.timetable
        return {
            "system": self._system(),
            "timetable": {"feed_version": tt.feed_version, "start_date": tt.start_date, "end_date": tt.end_date},
            "routes": [
                {
                    "id": r.id,
                    "short": r.short,
                    "long": r.long,
                    "color": r.color,
                    "text_color": r.text_color,
                    "shapes": [
                        {
                            "coords": [[lat, lon] for lat, lon in shape],
                            "length_m": round(geom.total, 1),
                            "closed": geom.closed,
                        }
                        for shape in r.shapes
                        for geom in [build_geom(shape, self.tracker.proj)]
                    ],
                }
                for r in tt.routes.values()
            ],
            "stops": [
                {"id": s.id, "code": s.code, "name": s.name, "lat": s.lat, "lon": s.lon, "routes": list(s.routes)}
                for s in tt.stops.values()
            ],
            "route_runs": route_runs_geojson(build_route_runs(tt)),
        }

    def live_document(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        tt, live = self.timetable, self.live
        check = self.check(now)
        counts: dict[str, dict[str, int]] = {rid: {"moving": 0, "waiting": 0} for rid in tt.routes}

        vehicles = []
        for v in live.vehicles:
            w = waiting_info(tt, live.trip_updates, v, now)
            rid = vehicle_route(tt, v)
            if rid in counts:
                counts[rid]["waiting" if w else "moving"] += 1
            vehicles.append(self._vehicle(v, rid, w, self.tracks.get(v.vehicle_id)))

        routes = []
        for rid, status in check.routes.items():
            nxt = status.next
            routes.append(
                {
                    "id": rid,
                    **counts[rid],
                    "scheduled_now": status.active,
                    "untracked": len(status.untracked),
                    "cancelled": len(status.cancelled),
                    "next": None
                    if nxt is None
                    else {
                        "time": nxt.time,
                        "scheduled": nxt.scheduled,
                        "trip_id": nxt.trip_id,
                        "stop_id": nxt.stop_id,
                    },
                }
            )

        issues: list[dict[str, Any]] = []
        for rid, status in check.routes.items():
            for kind, refs in (("untracked", status.untracked), ("cancelled", status.cancelled)):
                issues.extend(
                    {
                        "kind": kind,
                        "route_id": rid,
                        "trip_id": t.trip_id,
                        "headsign": t.headsign,
                        "start": t.start,
                        "end": t.end,
                        "vehicle_id": None,
                    }
                    for t in refs
                )
        for v in check.unscheduled:
            issues.append(
                {
                    "kind": "extra",
                    "route_id": vehicle_route(tt, v),
                    "trip_id": v.trip_id,
                    "headsign": None,
                    "start": None,
                    "end": None,
                    "vehicle_id": v.vehicle_id,
                    "start_time": v.start_time,
                }
            )

        return {
            "system": self._system(),
            "generated_at": int(now),
            "feeds": {
                "vehicles_at": live.vehicles_at,
                "trip_updates_at": live.trip_updates_at,
                "alerts_at": live.alerts_at,
            },
            "timetable": {
                "feed_version": tt.feed_version,
                "out_of_date": self.timetable_out_of_date,
                "unknown_trip_ratio": round(check.unknown_trip_ratio, 3),
            },
            "vehicles": vehicles,
            "routes": routes,
            "issues": issues,
            "alerts": [
                {
                    "id": a.id,
                    "header": a.header,
                    "description": a.description,
                    "url": a.url,
                    "effect": a.effect,
                    "route_ids": list(a.route_ids),
                    "stop_ids": list(a.stop_ids),
                }
                for a in live.alerts
                if a.active_at(now)
            ],
        }

    def _vehicle(self, v: Vehicle, rid: str | None, w: Any, track: TrackPosition | None) -> dict[str, Any]:
        trip = self.timetable.trips.get(v.trip_id or "")
        return {
            "id": v.vehicle_id,
            "label": v.label,
            "route_id": rid,
            "trip_id": v.trip_id,
            "headsign": trip.headsign if trip else None,
            "lat": round(v.lat, 6),
            "lon": round(v.lon, 6),
            "bearing": v.bearing,
            "speed": v.speed,
            "status": v.status,
            "stop_id": v.stop_id,
            "occupancy": v.occupancy,
            "timestamp": v.timestamp,
            "waiting": None
            if w is None
            else {
                "departs": w.departs,
                "scheduled": w.scheduled,
                "predicted": w.predicted,
                "stop_id": w.stop_id,
            },
            "track": None
            if track is None
            else {
                "shape_index": track.shape_index,
                "distance_along": round(track.distance_along, 1),
                "lat": round(track.lat, 6),
                "lon": round(track.lon, 6),
                "glide": track.glide,
            },
        }

    def departures_document(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        check = self.check(now)
        deps = all_departures(self.timetable, self.live.trip_updates, now, check.untracked_trips)
        return {
            "system": self._system(),
            "generated_at": int(now),
            "trip_updates_at": self.live.trip_updates_at,
            "stops": {
                stop_id: [
                    {
                        "time": d.time,
                        "trip_id": d.trip_id,
                        "route_id": d.route_id,
                        "headsign": d.headsign,
                        "live": d.live,
                        "delay": d.delay,
                        "cancelled": d.cancelled,
                        "untracked": d.untracked,
                    }
                    for d in items
                ]
                for stop_id, items in deps.items()
                if items
            },
        }
