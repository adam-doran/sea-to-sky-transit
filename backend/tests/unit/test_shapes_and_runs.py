from __future__ import annotations

import math
from pathlib import Path

from tests.builders import FeedBuilder, simple_line, vehicle
from transitlive.domain.route_runs import build_route_runs, route_runs_geojson
from transitlive.domain.shape_track import ShapeTracker, build_geom, point_along
from transitlive.gtfs.compile import compile_timetable
from transitlive.gtfs.load import read_gtfs_zip

FIXTURES = Path(__file__).parents[1] / "fixtures"
M_PER_DEG_LAT = 111_320


def straight():
    fb = simple_line()
    fb.trip("T1", "R1", [("A", "10:00:00"), ("D", "10:10:00")], shape="SH1")
    return fb.build()


def loop():
    """A closed square loop of ~4 x 111 m, starting and ending at the same corner."""
    fb = FeedBuilder().route("R3", "3").stop("A", 49.700).stop("B", 49.701)
    corners = [(49.700, -123.150), (49.701, -123.150), (49.701, -123.1485), (49.700, -123.1485), (49.700, -123.150)]
    fb.shape("LOOP", corners)
    fb.trip("T1", "R3", [("A", "10:00:00"), ("B", "10:05:00"), ("A", "10:10:00")], shape="LOOP")
    return fb.build()


class TestShapeTracker:
    def test_first_report_snaps_without_gliding(self) -> None:
        tracker = ShapeTracker(straight())
        pos = tracker.update(vehicle(trip="T1", lat=49.7005, lon=-123.15005))
        assert pos is not None and not pos.glide
        assert pos.lon == -123.15  # snapped onto the line
        assert math.isclose(pos.distance_along, 0.0005 * M_PER_DEG_LAT, rel_tol=0.01)

    def test_moving_forward_glides(self) -> None:
        tracker = ShapeTracker(straight())
        tracker.update(vehicle(trip="T1", lat=49.7005))
        pos = tracker.update(vehicle(trip="T1", lat=49.7015))
        assert pos is not None and pos.glide
        assert math.isclose(pos.distance_along, 0.0015 * M_PER_DEG_LAT, rel_tol=0.01)

    def test_small_backward_jitter_holds_position(self) -> None:
        tracker = ShapeTracker(straight())
        first = tracker.update(vehicle(trip="T1", lat=49.7010))
        pos = tracker.update(vehicle(trip="T1", lat=49.70095))  # ~5 m back
        assert first is not None and pos is not None
        assert pos.distance_along == first.distance_along and not pos.glide

    def test_off_route_report_is_not_snapped(self) -> None:
        tracker = ShapeTracker(straight())
        assert tracker.update(vehicle(trip="T1", lat=49.701, lon=-123.14)) is None  # ~720 m east

    def test_closed_loop_keeps_counting_past_its_start(self) -> None:
        tt = loop()
        tracker = ShapeTracker(tt)
        geom = tracker.geoms["R3"][0]
        assert geom.closed
        # Just before the end of the loop (on the last side, heading west)...
        before = tracker.update(vehicle(trip="T1", route="R3", lat=49.700, lon=-123.1498))
        # ...then just past the start, heading north again
        after = tracker.update(vehicle(trip="T1", route="R3", lat=49.7002, lon=-123.150))
        assert before is not None and after is not None and after.glide
        assert after.distance_along > before.distance_along > geom.total * 0.9
        assert after.distance_along > geom.total  # unwrapped
        assert after.distance_along - before.distance_along < 60

    def test_out_and_back_road_follows_the_right_pass(self) -> None:
        # The shape drives north then comes back south on the same road
        fb = FeedBuilder().route("R1", "1").stop("A", 49.700).stop("B", 49.702)
        fb.shape("OB", [(49.700, -123.15), (49.702, -123.15), (49.700, -123.15)])
        fb.trip("T1", "R1", [("A", "10:00:00"), ("B", "10:05:00"), ("A", "10:10:00")], shape="OB")
        tracker = ShapeTracker(fb.build())
        tracker.update(vehicle(trip="T1", lat=49.7019))  # near the far end, outbound
        back = tracker.update(vehicle(trip="T1", lat=49.7015))  # now heading back south
        geom = tracker.geoms["R1"][0]
        assert back is not None and back.glide
        assert back.distance_along > geom.total / 2  # on the return pass, not the outbound one

    def test_uses_the_trips_own_shape(self) -> None:
        # Two parallel variants 30 m apart; the trip says it is on SH-B
        fb = FeedBuilder().route("R1", "1").stop("A", 49.700).stop("B", 49.702)
        fb.shape("SH-A", [(49.700, -123.1500), (49.702, -123.1500)])
        fb.shape("SH-B", [(49.700, -123.1496), (49.702, -123.1496)])
        fb.trip("T0", "R1", [("A", "09:00:00"), ("B", "09:05:00")], shape="SH-A")
        fb.trip("T1", "R1", [("A", "10:00:00"), ("B", "10:05:00")], shape="SH-B")
        tracker = ShapeTracker(fb.build())
        pos = tracker.update(vehicle(trip="T1", lat=49.701, lon=-123.1499))  # nearer SH-A
        assert pos is not None and pos.shape_index == 1 and pos.lon == -123.1496

    def test_long_jump_restarts_instead_of_gliding(self) -> None:
        fb = FeedBuilder().route("R1", "1").stop("A", 49.70).stop("B", 49.73)
        fb.shape("LONG", [(49.70 + i * 0.001, -123.15) for i in range(31)])
        fb.trip("T1", "R1", [("A", "10:00:00"), ("B", "10:30:00")], shape="LONG")
        tracker = ShapeTracker(fb.build())
        tracker.update(vehicle(trip="T1", lat=49.701))
        pos = tracker.update(vehicle(trip="T1", lat=49.725))  # ~2.7 km later
        assert pos is not None and not pos.glide

    def test_point_along_wraps_on_loops(self) -> None:
        tracker = ShapeTracker(loop())
        geom = tracker.geoms["R3"][0]
        assert point_along(geom, geom.total + 10) == point_along(geom, 10)


class TestRouteRuns:
    def test_shared_segment_lists_both_routes(self) -> None:
        fb = FeedBuilder().route("R1", "1").route("R2", "2").stop("A", 49.700).stop("B", 49.703)
        fb.shape("S1", [(49.700, -123.15), (49.701, -123.15), (49.702, -123.15)])
        fb.shape("S2", [(49.701, -123.15), (49.702, -123.15), (49.703, -123.15)])
        fb.trip("T1", "R1", [("A", "10:00:00"), ("B", "10:05:00")], shape="S1")
        fb.trip("T2", "R2", [("A", "10:00:00"), ("B", "10:05:00")], shape="S2")
        runs = build_route_runs(fb.build())
        assert {(r.routes, r.coords) for r in runs} == {
            (("R1",), ((49.700, -123.15), (49.701, -123.15))),
            (("R1", "R2"), ((49.701, -123.15), (49.702, -123.15))),
            (("R2",), ((49.702, -123.15), (49.703, -123.15))),
        }
        gj = route_runs_geojson(runs)
        assert gj["features"][0]["geometry"]["coordinates"][0] == [-123.15, 49.700]  # lon, lat


class TestRealSquamishTimetable:
    def test_compiles(self) -> None:
        zips = sorted((FIXTURES / "archive" / "squamish" / "static").glob("*.zip"))
        tt = compile_timetable(read_gtfs_zip(zips[-1].read_bytes()))
        assert [r.short for r in tt.routes.values()] == ["1", "2", "3", "4", "9"]
        route3 = tt.routes["3-SQU"]
        assert len(route3.shapes) == 1
        assert build_geom(route3.shapes[0], ShapeTracker(tt).proj).closed  # route 3 is a loop
        assert all(t.shape_index is not None for t in tt.trips.values())
        runs = build_route_runs(tt)
        assert any(len(r.routes) >= 3 for r in runs)  # downtown roads carry several routes
