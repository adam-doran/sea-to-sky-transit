"""The health check: one indexed lookup per system and feed, cached in the API."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text

from transitlive.api import app as api
from transitlive.config import REALTIME_FEEDS, load_config
from transitlive.db import store

pytestmark = pytest.mark.integration

CONFIG = load_config()
T0 = 1_792_000_000.0


def fetch(engine: Engine, system_id: int, feed: str, at: float, header: float | None, error: str | None = None) -> None:
    store.record_fetch(engine, system_id, feed, at, "u", 200, 1, "x", header, 5, True, error)


def utc(epoch: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(epoch, dt.UTC)


def test_feed_health_finds_the_latest_success(engine: Engine) -> None:
    store.sync_systems(engine, CONFIG.systems)
    fetch(engine, 43, "vehicleupdates", T0, T0 - 20)
    fetch(engine, 43, "vehicleupdates", T0 + 30, T0 + 10)
    fetch(engine, 43, "vehicleupdates", T0 + 60, None, "HTTP 503")  # failures don't count
    fetch(engine, 43, "static", T0, None)
    fetch(engine, 44, "alerts", T0, None, "HTTP 503")  # never succeeded: no row

    rows = store.feed_health(engine)
    assert [(r["system"], r["feed"], r["last_success"], r["last_header"]) for r in rows] == [
        ("squamish", "static", utc(T0), None),
        ("squamish", "vehicleupdates", utc(T0 + 30), utc(T0 + 10)),
    ]
    assert all(r["timetable_version"] is None and r["timetable_end"] is None for r in rows)


def test_feed_health_uses_the_index(engine: Engine) -> None:
    """A year of fetches must not mean reading a year of fetches."""
    store.sync_systems(engine, CONFIG.systems)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO feed_fetches (system_id, feed, fetched_at, url, is_new) "
                "SELECT sys, feed, now() - make_interval(secs => n * 30), 'u', false "
                "FROM unnest(ARRAY[43, 44, 50]) sys, unnest(CAST(:feeds AS text[])) feed, "
                "generate_series(1, 5000) n"
            ),
            {"feeds": ["static", *REALTIME_FEEDS]},
        )
        conn.execute(text("ANALYZE feed_fetches"))

    statements: list[tuple[str, Any]] = []

    def capture(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        if "feed_fetches" in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert len(store.feed_health(engine)) == 3 * 4
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    [(statement, parameters)] = statements
    with engine.connect() as conn:
        plan = "\n".join(conn.exec_driver_sql("EXPLAIN " + statement, parameters).scalars())
    assert "feed_fetches_latest" in plan
    assert "Seq Scan on feed_fetches" not in plan


def test_health_is_cached_briefly(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    store.sync_systems(engine, CONFIG.systems)
    now = time.time()
    for system in CONFIG.systems:
        for feed in REALTIME_FEEDS:
            fetch(engine, system.operator_id, feed, now - 5, now - 10)
    fetch(engine, 43, "static", now - 60, None)

    calls = []
    real = store.feed_health

    def counted(engine: Engine) -> list[dict[str, Any]]:
        calls.append(1)
        return real(engine)

    monkeypatch.setattr(store, "feed_health", counted)
    client = TestClient(api.create_app(CONFIG, engine))

    first = client.get("/api/health")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["ok"] is True
    assert set(body) == {"ok", "feeds", "timetables"}
    assert len(body["feeds"]) == 9
    assert set(body["feeds"][0]) == {"system", "feed", "last_success", "last_header", "age_seconds", "stale"}
    assert set(body["timetables"]) == {"squamish"}
    assert set(body["timetables"]["squamish"]) == {"version", "ends", "last_sync"}

    # A burst of checks is one query...
    for _ in range(5):
        assert client.get("/api/health").json()["ok"] is True
    assert len(calls) == 1

    # ...until the cache expires
    monkeypatch.setattr(api, "HEALTH_TTL_SECONDS", 0.0)
    client.get("/api/health")
    assert len(calls) == 2
