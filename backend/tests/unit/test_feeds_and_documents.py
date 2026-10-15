"""Realtime decoding, the archive, backoff, and the document contract,
using the recorded fixtures in tests/fixtures/archive (make fixtures)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from google.transit import gtfs_realtime_pb2 as rt

from transitlive.api import schemas
from transitlive.collector.archive import Archive
from transitlive.collector.fetch import Backoff, Spacing
from transitlive.collector.realtime import FeedError, decode
from transitlive.collector.replay import events
from transitlive.config import REALTIME_FEEDS, load_config
from transitlive.gtfs.compile import compile_timetable
from transitlive.gtfs.load import read_gtfs_zip
from transitlive.live.runtime import MISMATCH_STRIKES, SystemRuntime

ARCHIVE = Archive(Path(__file__).parents[1] / "fixtures" / "archive")
CONFIG = load_config()


def runtimes() -> dict[str, SystemRuntime]:
    out = {}
    for system in CONFIG.systems:
        zips = list(ARCHIVE.iter_static(system.slug))
        tt = compile_timetable(read_gtfs_zip(zips[-1].read_bytes()), system.timezone)
        out[system.slug] = SystemRuntime(system, tt)
    return out


class TestDecode:
    def test_every_archived_snapshot_decodes(self) -> None:
        seen = set()
        for event in events(CONFIG, ARCHIVE):
            snap = decode(event.feed, event.data)
            assert snap.header_timestamp == event.timestamp
            seen.add((event.slug, event.feed, event.timestamp))
        on_disk = {
            (s.slug, feed, ts)
            for s in CONFIG.systems
            for feed in REALTIME_FEEDS
            for ts, _ in ARCHIVE.iter_realtime(s.slug, feed)
        }
        assert seen == on_disk  # every snapshot, labelled with its own system and feed
        assert len({(slug, feed) for slug, feed, _ in seen}) == 9

    def test_vehicle_fields(self) -> None:
        _ts, path = next(ARCHIVE.iter_realtime("squamish", "vehicleupdates"))
        snap = decode("vehicleupdates", Archive.read(path))
        v = snap.vehicles[0]
        assert v.vehicle_id and v.trip_id and v.route_id and v.route_id.endswith("-SQU")
        assert 49.6 < v.lat < 49.8 and -123.3 < v.lon < -123.0
        assert v.status in {"INCOMING_AT", "STOPPED_AT", "IN_TRANSIT_TO", None}

    def test_trip_update_fields(self) -> None:
        _, path = next(ARCHIVE.iter_realtime("whistler", "tripupdates"))
        snap = decode("tripupdates", Archive.read(path))
        tu = snap.trip_updates[0]
        assert tu.trip_id and tu.stop_updates and tu.relationship in {"SCHEDULED", "ADDED", "CANCELED", "UNSCHEDULED"}
        assert any(s.time for s in tu.stop_updates)

    def test_empty_feed(self) -> None:
        msg = rt.FeedMessage()
        msg.header.gtfs_realtime_version = "2.0"
        msg.header.timestamp = 1_792_000_000
        snap = decode("vehicleupdates", msg.SerializeToString())
        assert snap.vehicles == () and snap.header_timestamp == 1_792_000_000

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(FeedError):
            decode("vehicleupdates", b"<html>Service Unavailable</html>")

    def test_missing_header_is_rejected(self) -> None:
        with pytest.raises(FeedError):
            decode("vehicleupdates", b"")


class TestArchive:
    def test_round_trip_and_layout(self, tmp_path: Path) -> None:
        archive = Archive(tmp_path)
        path = archive.write_realtime("squamish", "alerts", 1_792_000_000, b"payload")
        assert path.relative_to(tmp_path).as_posix() == "squamish/alerts/2026-10-14/1792000000.pb.zst"  # 17:46 UTC
        assert Archive.read(path) == b"payload"
        assert list(archive.iter_realtime("squamish", "alerts")) == [(1_792_000_000, path)]

    def test_writing_twice_keeps_the_first_copy(self, tmp_path: Path) -> None:
        archive = Archive(tmp_path)
        path = archive.write_realtime("squamish", "alerts", 1, b"first")
        archive.write_realtime("squamish", "alerts", 1, b"second")
        assert Archive.read(path) == b"first"


class TestBackoff:
    def test_waits_grow_and_reset(self) -> None:
        b = Backoff(base=10, rng=random.Random(1))
        assert b.ready(0)
        waits = [b.failure(0) for _ in range(6)]
        assert all(10 <= w <= 300 for w in waits)
        assert not b.ready(0)
        b.success()
        assert b.ready(0)

    def test_capped(self) -> None:
        b = Backoff(base=10, rng=random.Random(2))
        for _ in range(20):
            wait = b.failure(0)
        assert wait <= 300


class TestDocuments:
    """Replay the fixtures through each system's runtime, and check every
    document against the API schemas (the contract with the web app)."""

    def test_documents_match_the_schemas(self) -> None:
        rts = runtimes()
        built = 0
        for event in events(CONFIG, ARCHIVE):
            rt_ = rts[event.slug]
            rt_.apply(decode(event.feed, event.data))
            if event.feed == "vehicleupdates":
                schemas.LiveDocument.model_validate(rt_.live_document(event.timestamp))
                built += 1
            elif event.feed == "tripupdates":
                schemas.DeparturesDocument.model_validate(rt_.departures_document(event.timestamp))
        for rt_ in rts.values():
            schemas.StaticDocument.model_validate(rt_.static_document())
        assert built > 10

    def test_buses_stay_on_their_shapes(self) -> None:
        """The prototype's bug: gliding must follow the line. Every tracked
        position must sit on its shape, and distances only move forward."""
        rts = runtimes()
        last: dict[str, float] = {}
        tracked = 0
        for event in events(CONFIG, ARCHIVE):
            if event.feed != "vehicleupdates":
                continue
            rt_ = rts[event.slug]
            rt_.apply(decode(event.feed, event.data))
            for vid, track in rt_.tracks.items():
                if track is None:
                    last.pop(vid, None)
                    continue
                tracked += 1
                if track.glide and vid in last:
                    assert track.distance_along >= last[vid]
                last[vid] = track.distance_along
        assert tracked > 20

    def test_static_document_has_route_runs(self) -> None:
        doc = runtimes()["squamish"].static_document()
        shared = [f for f in doc["route_runs"]["features"] if f["properties"]["count"] > 1]
        assert shared, "downtown Squamish roads are shared by several routes"

    def test_mismatch_guard(self) -> None:
        from tests.builders import vehicle
        from transitlive.domain.model import Snapshot

        rt_ = runtimes()["squamish"]
        strangers = Snapshot("vehicleupdates", 1, vehicles=(vehicle(trip="not-in-timetable", route=None),))
        for _ in range(MISMATCH_STRIKES):
            assert not rt_.timetable_out_of_date
            rt_.apply(strangers)
        assert rt_.timetable_out_of_date
        assert rt_.live_document(1)["timetable"]["out_of_date"]


class TestSpacing:
    def test_first_request_is_immediate(self) -> None:
        assert Spacing(10, mono=lambda: 0, wall=lambda: 0).remaining() == 0

    def test_waits_out_the_interval(self) -> None:
        clock = {"mono": 100.0, "wall": 1_000.0}
        sp = Spacing(10, mono=lambda: clock["mono"], wall=lambda: clock["wall"])
        sp.mark()
        clock["mono"] += 4
        clock["wall"] += 4
        assert sp.remaining() == pytest.approx(6)

    def test_monotonic_jump_does_not_let_requests_through(self) -> None:
        # Docker Desktop's VM: the monotonic clock leaps ahead, the wall clock doesn't
        clock = {"mono": 100.0, "wall": 1_000.0}
        sp = Spacing(10, mono=lambda: clock["mono"], wall=lambda: clock["wall"])
        sp.mark()
        clock["mono"] += 500
        clock["wall"] += 1
        assert sp.remaining() == pytest.approx(9)

    def test_wall_clock_going_backwards_is_not_waited_out(self) -> None:
        clock = {"mono": 100.0, "wall": 1_000.0}
        sp = Spacing(10, mono=lambda: clock["mono"], wall=lambda: clock["wall"])
        sp.mark()
        clock["mono"] += 10
        clock["wall"] -= 3600
        assert sp.remaining() == 0

    async def test_wait_sleeps_until_allowed(self) -> None:
        sp = Spacing(0.05)
        sp.mark()
        await sp.wait()
        assert sp.remaining() == 0
