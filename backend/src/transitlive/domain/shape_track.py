"""Where each bus is along its trip's shape, so the map can glide it along the
route line between reports instead of jumping or cutting across.

Each bus remembers how far along its shape it is and only ever moves forward
from there. That keeps loops (Squamish route 3) and roads driven twice in one
trip in the right order. Distances on closed loops keep counting past the end
of the shape ("unwrapped"), so a client can interpolate between two reports
and take the result modulo the shape length.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from transitlive.domain.model import LatLon, Timetable, Vehicle

SNAP_METRES = 40  # how far a report may sit from the line and still count as on it
JITTER_METRES = 15  # GPS noise: a bus can appear to step backwards slightly
MAX_STEP_METRES = 2000  # further than this between reports and we jump instead
TIE_METRES = 5  # passes this close in distance from the line count as equally close
CLOSED_LOOP_METRES = 30  # shapes whose ends are this close form a loop
EARTH_METRES_PER_DEGREE = 111_320.0


@dataclass(frozen=True)
class ShapeGeom:
    latlngs: tuple[LatLon, ...]
    xy: tuple[tuple[float, float], ...]
    cum: tuple[float, ...]  # distance along the shape at each point, metres

    @property
    def total(self) -> float:
        return self.cum[-1]

    @property
    def closed(self) -> bool:
        (x0, y0), (x1, y1) = self.xy[0], self.xy[-1]
        return math.hypot(x1 - x0, y1 - y0) < CLOSED_LOOP_METRES


@dataclass(frozen=True)
class Candidate:
    shape_index: int
    along: float
    off: float


@dataclass(frozen=True)
class TrackPosition:
    shape_index: int
    distance_along: float  # metres; unwrapped on closed loops
    lat: float  # the report snapped onto the line
    lon: float
    glide: bool  # True when the client should glide from the previous position


class Projection:
    """Flat x/y metres around a reference latitude: accurate at town scale."""

    def __init__(self, ref_lat: float) -> None:
        self.kx = EARTH_METRES_PER_DEGREE * math.cos(math.radians(ref_lat))

    def xy(self, p: LatLon) -> tuple[float, float]:
        return (p[1] * self.kx, p[0] * EARTH_METRES_PER_DEGREE)


def build_geom(latlngs: tuple[LatLon, ...], proj: Projection) -> ShapeGeom:
    xy = tuple(proj.xy(p) for p in latlngs)
    cum = [0.0]
    for (x0, y0), (x1, y1) in itertools.pairwise(xy):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    return ShapeGeom(latlngs=latlngs, xy=xy, cum=tuple(cum))


def candidates_on(geom: ShapeGeom, shape_index: int, p: tuple[float, float]) -> list[Candidate]:
    """Every place a point lies on a shape: one candidate per pass of the
    shape that comes within SNAP_METRES."""
    found: list[Candidate] = []
    in_run = False
    px, py = p
    for i in range(1, len(geom.xy)):
        ax, ay = geom.xy[i - 1]
        dx, dy = geom.xy[i][0] - ax, geom.xy[i][1] - ay
        len2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2)) if len2 else 0.0
        off = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if off > SNAP_METRES:
            in_run = False
            continue
        cand = Candidate(shape_index=shape_index, along=geom.cum[i - 1] + t * math.sqrt(len2), off=off)
        if not in_run:
            found.append(cand)
            in_run = True
        elif off < found[-1].off:
            found[-1] = cand
    return found


def point_along(geom: ShapeGeom, d: float) -> LatLon:
    if geom.closed and geom.total > 0:
        d %= geom.total
    d = max(0.0, min(geom.total, d))
    lo, hi = 1, len(geom.cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if geom.cum[mid] < d:
            lo = mid + 1
        else:
            hi = mid
    seg = geom.cum[lo] - geom.cum[lo - 1]
    k = (d - geom.cum[lo - 1]) / seg if seg else 0.0
    (lat0, lon0), (lat1, lon1) = geom.latlngs[lo - 1], geom.latlngs[lo]
    return (lat0 + (lat1 - lat0) * k, lon0 + (lon1 - lon0) * k)


@dataclass
class _State:
    route_id: str
    shape_index: int
    along: float  # unwrapped


class ShapeTracker:
    """Keeps each vehicle's position along its shape between reports."""

    def __init__(self, tt: Timetable) -> None:
        lats = [s.lat for s in tt.stops.values()] or [49.7]
        self.proj = Projection(sum(lats) / len(lats))
        self.tt = tt
        self.geoms = {rid: [build_geom(s, self.proj) for s in r.shapes] for rid, r in tt.routes.items()}
        self.state: dict[str, _State] = {}

    def update(self, v: Vehicle) -> TrackPosition | None:
        trip = self.tt.trips.get(v.trip_id or "")
        route_id = v.route_id or (trip.route_id if trip else None)
        geoms = self.geoms.get(route_id or "", [])
        # The trip's own shape when the timetable says which; otherwise
        # (an extra trip) any of its route's shapes
        if trip is not None and trip.shape_index is not None and trip.shape_index < len(geoms):
            indexes = [trip.shape_index]
        else:
            indexes = list(range(len(geoms)))
        p = self.proj.xy((v.lat, v.lon))
        cands = [c for i in indexes for c in candidates_on(geoms[i], i, p)]
        prev = self.state.get(v.vehicle_id)

        # Continue forward along the shape the bus was already on
        best: tuple[float, Candidate] | None = None
        if prev is not None and prev.route_id == route_id:
            prev_wrapped = prev.along
            geom = geoms[prev.shape_index] if prev.shape_index < len(geoms) else None
            if geom is not None and geom.closed and geom.total > 0:
                prev_wrapped = prev.along % geom.total
            forward: list[tuple[float, Candidate]] = []
            for c in cands:
                if c.shape_index != prev.shape_index or geom is None:
                    continue
                ahead = c.along - prev_wrapped
                if geom.closed and ahead < -JITTER_METRES:
                    ahead += geom.total
                if -JITTER_METRES <= ahead <= MAX_STEP_METRES:
                    forward.append((max(0.0, ahead), c))
            if forward:
                # The pass the bus is closest to wins. Passes about as close as
                # each other (a road driven both ways) go to the nearest ahead.
                closest = min(c.off for _, c in forward)
                best = min((f for f in forward if f[1].off <= closest + TIE_METRES), key=lambda f: f[0])

        if best is not None and prev is not None and route_id is not None:
            ahead, c = best
            prev.along += ahead
            lat, lon = point_along(geoms[c.shape_index], prev.along)
            return TrackPosition(c.shape_index, prev.along, lat, lon, glide=ahead > 0)

        if not cands or route_id is None:
            # Off its shape: no snapping, the map shows the raw position
            self.state.pop(v.vehicle_id, None)
            return None
        # New bus, new trip or a long jump: start again from the best match
        c = min(cands, key=lambda c: c.off)
        self.state[v.vehicle_id] = _State(route_id=route_id, shape_index=c.shape_index, along=c.along)
        lat, lon = point_along(geoms[c.shape_index], c.along)
        return TrackPosition(c.shape_index, c.along, lat, lon, glide=False)

    def forget_missing(self, present: set[str]) -> None:
        for vid in list(self.state):
            if vid not in present:
                del self.state[vid]
