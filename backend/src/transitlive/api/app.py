"""The public API. It never contacts BC Transit: it serves documents the
collector has already built, so any amount of traffic costs BC Transit nothing.

Responses carry an ETag (304 when unchanged) and Cache-Control headers sized
for a CDN in front: the live document is cached for 5 seconds, so a burst of
users is served from the CDN, not from here.
"""

from __future__ import annotations

import datetime as dt
import gzip
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy import Engine

from transitlive.api import schemas
from transitlive.config import Config, load_config
from transitlive.db import store
from transitlive.db.engine import make_engine

CACHE_CONTROL = {
    "static": "public, max-age=300, stale-while-revalidate=3600",
    "live": "public, max-age=5, stale-while-revalidate=10",
    "departures": "public, max-age=15, stale-while-revalidate=30",
}
MEMORY_TTL_SECONDS = 2.0  # collapse bursts of identical reads into one database query
HEALTH_TTL_SECONDS = 10.0  # the health check is public, so it never costs more than one query per 10 s
STALE_AFTER_SECONDS = 120  # health check: a realtime feed this old means the collector is in trouble


@dataclass
class _Cached:
    doc: store.StoredDocument | None
    at: float


@dataclass
class _CachedHealth:
    rows: list[dict[str, Any]]
    at: float


def create_app(config: Config | None = None, engine: Engine | None = None) -> FastAPI:
    config = config or load_config()
    engine = engine or make_engine()
    slugs = {s.slug for s in config.systems}
    cache: dict[tuple[str, str], _Cached] = {}
    health_cache: _CachedHealth | None = None
    health_lock = threading.Lock()

    app = FastAPI(
        title="Sea-to-Sky Transit Live API",
        version="0.1.0",
        description="Live BC Transit data for the Sea-to-Sky corridor, served from the project's own cache.",
    )

    def document(slug: str, kind: str) -> store.StoredDocument:
        if slug not in slugs:
            raise HTTPException(404, f"unknown system '{slug}'")
        key = (slug, kind)
        now = time.monotonic()
        hit = cache.get(key)
        if hit is None or now - hit.at > MEMORY_TTL_SECONDS:
            hit = cache[key] = _Cached(store.get_document(engine, slug, kind), now)
        if hit.doc is None:
            raise HTTPException(503, "not collected yet; try again shortly", headers={"Retry-After": "10"})
        return hit.doc

    def feed_health() -> list[dict[str, Any]]:
        # The lock means a burst of requests as the cache expires costs one query, not one each
        nonlocal health_cache
        with health_lock:
            now = time.monotonic()
            if health_cache is None or now - health_cache.at > HEALTH_TTL_SECONDS:
                health_cache = _CachedHealth(store.feed_health(engine), now)
            return health_cache.rows

    def respond(request: Request, slug: str, kind: str) -> Response:
        doc = document(slug, kind)
        etag = f'"{doc.etag}"'
        headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL[kind], "Vary": "Accept-Encoding"}
        if etag in request.headers.get("if-none-match", ""):
            return Response(status_code=304, headers=headers)
        if "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
            return Response(doc.body_gzip, media_type="application/json", headers=headers)
        return Response(gzip.decompress(doc.body_gzip), media_type="application/json", headers=headers)

    @app.get("/api/systems", response_model=list[schemas.SystemInfo])
    def systems() -> list[dict[str, str]]:
        return [{"slug": s.slug, "name": s.name, "timezone": s.timezone} for s in config.systems]

    @app.get(
        "/api/systems/{slug}/static",
        response_model=schemas.StaticDocument,
        summary="Routes, shapes, stops and shared-road runs",
    )
    def static(slug: str, request: Request) -> Response:
        return respond(request, slug, "static")

    @app.get(
        "/api/systems/{slug}/live",
        response_model=schemas.LiveDocument,
        summary="Buses, route summaries, schedule check and alerts",
    )
    def live(slug: str, request: Request) -> Response:
        return respond(request, slug, "live")

    @app.get(
        "/api/systems/{slug}/departures",
        response_model=schemas.DeparturesDocument,
        summary="Next departures at every stop",
    )
    def departures(slug: str, request: Request) -> Response:
        return respond(request, slug, "departures")

    @app.get("/api/health", response_model=schemas.Health)
    def health(response: Response) -> dict[str, Any]:
        now = dt.datetime.now(dt.UTC)
        rows = feed_health()
        feeds, timetables = [], {}
        for r in rows:
            if r["feed"] == "static":
                timetables[r["system"]] = {
                    "version": r["timetable_version"],
                    "ends": r["timetable_end"],
                    "last_sync": r["last_success"],
                }
                continue
            age = (now - r["last_success"]).total_seconds() if r["last_success"] else None
            feeds.append(
                {
                    "system": r["system"],
                    "feed": r["feed"],
                    "last_success": r["last_success"].isoformat() if r["last_success"] else None,
                    "last_header": r["last_header"].isoformat() if r["last_header"] else None,
                    "age_seconds": age,
                    "stale": age is None or age > STALE_AFTER_SECONDS,
                }
            )
        expected = {(s.slug, f) for s in config.systems for f in ("vehicleupdates", "tripupdates", "alerts")}
        seen = {(f["system"], f["feed"]) for f in feeds}
        ok = bool(feeds) and seen >= expected and not any(f["stale"] for f in feeds)
        response.status_code = 200 if ok else 503
        response.headers["Cache-Control"] = "no-store"
        return {"ok": ok, "feeds": feeds, "timetables": timetables}

    return app
