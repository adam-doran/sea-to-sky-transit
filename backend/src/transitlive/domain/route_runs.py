"""Split route shapes into runs of road used by the same set of routes.

A road shared by routes 1, 2 and 9 becomes one run listing all three, so the
map can draw them side by side instead of the last-drawn route hiding the
others. BC Transit's shapes share exact coordinates on common roads, so
segments match exactly.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

from transitlive.domain.model import LatLon, Timetable

Segment = tuple[LatLon, LatLon]


@dataclass(frozen=True)
class RouteRun:
    routes: tuple[str, ...]  # in display order
    coords: tuple[LatLon, ...]


def _key(a: LatLon, b: LatLon) -> Segment:
    return (a, b) if a <= b else (b, a)


def build_route_runs(tt: Timetable) -> list[RouteRun]:
    seg_routes: dict[Segment, set[str]] = {}
    for route in tt.routes.values():
        for shape in route.shapes:
            for a, b in itertools.pairwise(shape):
                if a != b:
                    seg_routes.setdefault(_key(a, b), set()).add(route.id)

    order = {rid: i for i, rid in enumerate(tt.routes)}
    runs: list[RouteRun] = []
    drawn: set[Segment] = set()
    for route in tt.routes.values():
        for shape in route.shapes:
            current: list[LatLon] = []
            current_routes: tuple[str, ...] = ()
            for a, b in itertools.pairwise(shape):
                k = _key(a, b)
                if a == b or k in drawn:
                    if current:
                        runs.append(RouteRun(current_routes, tuple(current)))
                    current = []
                    continue
                drawn.add(k)
                routes = tuple(sorted(seg_routes[k], key=lambda r: order[r]))
                if current and routes == current_routes:
                    current.append(b)
                else:
                    if current:
                        runs.append(RouteRun(current_routes, tuple(current)))
                    current, current_routes = [a, b], routes
            if current:
                runs.append(RouteRun(current_routes, tuple(current)))
    return runs


def route_runs_geojson(runs: list[RouteRun]) -> dict[str, Any]:
    """GeoJSON (lon, lat order) with each run's routes as a property."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"routes": list(run.routes), "count": len(run.routes)},
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in run.coords]},
            }
            for run in runs
        ],
    }
