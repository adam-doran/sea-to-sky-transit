"""Collector -> PostgreSQL -> API, end to end, on the recorded fixtures."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text

from transitlive.api import schemas
from transitlive.api.app import create_app
from transitlive.collector.archive import Archive
from transitlive.collector.fetch import Fetcher
from transitlive.collector.replay import Replayer
from transitlive.collector.service import Collector
from transitlive.config import load_config
from transitlive.db import schema as s

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "archive"
CONFIG = load_config()


def count(engine: Engine, table: s.Table) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


async def replay(engine: Engine) -> int:
    return await Replayer(CONFIG, engine, FIXTURES).run(speed=0)


async def test_replay_fills_history_and_documents(engine: Engine) -> None:
    replayed = await replay(engine)
    assert replayed > 50
    assert count(engine, s.systems) == 3
    with engine.connect() as conn:
        active = conn.execute(select(s.feed_versions.c.system_id).where(s.feed_versions.c.active)).scalars().all()
    assert sorted(active) == [43, 44, 50]
    assert count(engine, s.gtfs_stop_times) > 10_000
    assert count(engine, s.vehicle_positions) > 50
    assert count(engine, s.stop_predictions) > 100
    assert count(engine, s.live_documents) == 9  # 3 systems x static, live, departures
    with engine.connect() as conn:
        tracked = conn.execute(
            select(func.count()).select_from(s.vehicle_positions).where(s.vehicle_positions.c.shape_index.is_not(None))
        ).scalar_one()
    assert tracked > 0


async def test_rebuilding_from_the_archive_gives_the_same_history(engine: Engine) -> None:
    await replay(engine)
    first = (count(engine, s.vehicle_positions), count(engine, s.stop_predictions))
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE vehicle_positions, stop_predictions"))
    await replay(engine)
    assert (count(engine, s.vehicle_positions), count(engine, s.stop_predictions)) == first
    # ...and replaying on top of existing history adds no duplicates
    await replay(engine)
    assert count(engine, s.vehicle_positions) == first[0]


async def test_api_serves_cached_documents(engine: Engine) -> None:
    await replay(engine)
    client = TestClient(create_app(CONFIG, engine))

    assert [x["slug"] for x in client.get("/api/systems").json()] == ["squamish", "whistler", "pemberton"]

    live = client.get("/api/systems/squamish/live")
    assert live.status_code == 200
    assert live.headers["cache-control"].startswith("public, max-age=5")
    schemas.LiveDocument.model_validate(live.json())

    again = client.get("/api/systems/squamish/live", headers={"If-None-Match": live.headers["etag"]})
    assert again.status_code == 304

    raw = client.get("/api/systems/whistler/departures", headers={"Accept-Encoding": "gzip"})
    schemas.DeparturesDocument.model_validate(raw.json())  # httpx decodes gzip transparently

    static = client.get("/api/systems/pemberton/static")
    schemas.StaticDocument.model_validate(static.json())
    assert "max-age=300" in static.headers["cache-control"]

    assert client.get("/api/systems/vancouver/live").status_code == 404


async def test_api_before_anything_is_collected(engine: Engine) -> None:
    client = TestClient(create_app(CONFIG, engine))
    resp = client.get("/api/systems/squamish/live")
    assert resp.status_code == 503 and resp.headers["retry-after"] == "10"
    assert client.get("/api/health").status_code == 503


def fake_bc_transit(requests: list[str], fail: bool = False) -> httpx.MockTransport:
    """Serves the fixture archive as if it were bct.tmix.se."""
    archive = Archive(FIXTURES)
    slugs = {str(sys.operator_id): sys.slug for sys in CONFIG.systems}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.headers["user-agent"] == CONFIG.collector.user_agent
        if fail:
            return httpx.Response(503)
        slug = slugs[request.url.params["operatorIds"]]
        if "gtfs-realtime" in request.url.path:
            feed = request.url.path.rsplit("/", 1)[-1].removesuffix(".pb")
            _, path = list(archive.iter_realtime(slug, feed))[-1]
            return httpx.Response(200, content=Archive.read(path))
        return httpx.Response(200, content=list(archive.iter_static(slug))[-1].read_bytes())

    return httpx.MockTransport(handler)


async def test_collector_polls_politely(engine: Engine, tmp_path: Path) -> None:
    requests: list[str] = []
    fetcher = Fetcher(CONFIG.collector.user_agent, 5, transport=fake_bc_transit(requests))
    collector = Collector(CONFIG, engine, Archive(tmp_path), fetcher)
    await collector.prepare()
    assert len(requests) == 3  # one timetable download per system

    for slug in collector.tasks:
        for feed in ("vehicleupdates", "tripupdates", "alerts"):
            await collector.poll_once(slug, feed)
    assert len(requests) == 3 + 9

    # Identical data is logged but not archived or stored twice
    before = count(engine, s.vehicle_positions)
    await collector.poll_once("squamish", "vehicleupdates")
    assert count(engine, s.vehicle_positions) == before
    with engine.connect() as conn:
        rows = (
            conn.execute(
                select(s.feed_fetches.c.is_new)
                .where(s.feed_fetches.c.feed == "vehicleupdates", s.feed_fetches.c.system_id == 43)
                .order_by(s.feed_fetches.c.id)
            )
            .scalars()
            .all()
        )
    assert rows == [True, False]
    health = TestClient(create_app(CONFIG, engine)).get("/api/health")
    assert health.status_code == 200 and health.json()["ok"]
    await fetcher.aclose()


async def test_collector_backs_off_when_bc_transit_is_down(engine: Engine, tmp_path: Path) -> None:
    ok_requests: list[str] = []
    fetcher = Fetcher(CONFIG.collector.user_agent, 5, transport=fake_bc_transit(ok_requests))
    now = [1_792_000_000.0]
    collector = Collector(CONFIG, engine, Archive(tmp_path), fetcher, clock=lambda: now[0])
    await collector.prepare()

    failing: list[str] = []
    collector.fetcher = Fetcher(CONFIG.collector.user_agent, 5, transport=fake_bc_transit(failing, fail=True))
    assert await collector.poll_once("squamish", "vehicleupdates") is None
    assert len(failing) == 1
    # Retrying straight away is refused without contacting BC Transit
    assert await collector.poll_once("squamish", "vehicleupdates") is None
    assert len(failing) == 1
    now[0] += 400  # past the longest backoff
    await collector.poll_once("squamish", "vehicleupdates")
    assert len(failing) == 2
    with engine.connect() as conn:
        errors = conn.execute(select(s.feed_fetches.c.error).where(s.feed_fetches.c.error.is_not(None))).scalars()
        assert list(errors) == ["HTTP 503", "HTTP 503"]
    await fetcher.aclose()
    await collector.fetcher.aclose()


def test_documents_are_stored_gzipped(engine: Engine) -> None:
    from transitlive.db import store

    store.sync_systems(engine, CONFIG.systems)
    etag = store.save_document(engine, 43, "live", {"hello": "world"}, 1_792_000_000)
    doc = store.get_document(engine, "squamish", "live")
    assert doc is not None and doc.etag == etag
    assert json.loads(gzip.decompress(doc.body_gzip)) == {"hello": "world"}
