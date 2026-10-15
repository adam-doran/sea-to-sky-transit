"""Reads and writes for the collector and API."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from transitlive.config import System
from transitlive.db import schema as s
from transitlive.domain.model import Alert, Snapshot, TripUpdate
from transitlive.domain.shape_track import TrackPosition
from transitlive.gtfs.load import GtfsFeed


def _ts(epoch: float | None) -> dt.datetime | None:
    return None if epoch is None else dt.datetime.fromtimestamp(epoch, dt.UTC)


def _date(key: str | None) -> dt.date | None:
    if not key or len(key) != 8:
        return None
    return dt.date(int(key[:4]), int(key[4:6]), int(key[6:8]))


def _chunks(rows: list[dict[str, Any]], size: int = 5000) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


# ---- systems ----


def sync_systems(engine: Engine, systems: Sequence[System]) -> dict[str, int]:
    """Make the systems table match the config. IDs are the BC Transit operator IDs."""
    with engine.begin() as conn:
        for sysm in systems:
            stmt = pg_insert(s.systems).values(
                id=sysm.operator_id,
                slug=sysm.slug,
                name=sysm.name,
                operator_id=sysm.operator_id,
                timezone=sysm.timezone,
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=[s.systems.c.id],
                    set_={"slug": sysm.slug, "name": sysm.name, "timezone": sysm.timezone},
                )
            )
    return {sysm.slug: sysm.operator_id for sysm in systems}


# ---- fetch log ----


def record_fetch(
    engine: Engine,
    system_id: int,
    feed: str,
    fetched_at: float,
    url: str,
    status: int | None,
    size: int | None,
    sha256: str | None,
    header_at: float | None,
    latency_ms: int,
    is_new: bool,
    error: str | None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(s.feed_fetches).values(
                system_id=system_id,
                feed=feed,
                fetched_at=_ts(fetched_at),
                url=url,
                http_status=status,
                bytes=size,
                sha256=sha256,
                header_at=_ts(header_at),
                latency_ms=latency_ms,
                is_new=is_new,
                error=error,
            )
        )


# ---- static timetables ----


@dataclass(frozen=True)
class SavedVersion:
    id: int
    is_new: bool
    archive_path: str


def save_feed_version(
    engine: Engine, system_id: int, feed: GtfsFeed, archive_path: str, seen_at: float
) -> SavedVersion:
    """Store a timetable version (and all its rows) unless its content is already stored."""
    info = (feed.table("feed_info") or [{}])[0]
    with engine.begin() as conn:
        existing = conn.execute(
            select(s.feed_versions.c.id, s.feed_versions.c.archive_path).where(
                s.feed_versions.c.system_id == system_id,
                s.feed_versions.c.content_sha256 == feed.content_sha256,
            )
        ).first()
        if existing is not None:
            conn.execute(
                update(s.feed_versions).where(s.feed_versions.c.id == existing.id).values(last_seen=_ts(seen_at))
            )
            return SavedVersion(existing.id, False, existing.archive_path)

        version_id = conn.execute(
            insert(s.feed_versions)
            .values(
                system_id=system_id,
                zip_sha256=feed.zip_sha256,
                content_sha256=feed.content_sha256,
                feed_version=info.get("feed_version"),
                start_date=_date(info.get("feed_start_date")),
                end_date=_date(info.get("feed_end_date")),
                first_seen=_ts(seen_at),
                last_seen=_ts(seen_at),
                archive_path=archive_path,
            )
            .returning(s.feed_versions.c.id)
        ).scalar_one()

        def rows(table: str, mapping: dict[str, str]) -> list[dict[str, Any]]:
            return [
                {"feed_version_id": version_id, **{col: r.get(src) or None for col, src in mapping.items()}}
                for r in feed.table(table)
            ]

        tables: list[tuple[Any, list[dict[str, Any]]]] = [
            (
                s.gtfs_routes,
                rows(
                    "routes",
                    {
                        "route_id": "route_id",
                        "short_name": "route_short_name",
                        "long_name": "route_long_name",
                        "color": "route_color",
                        "text_color": "route_text_color",
                    },
                ),
            ),
            (
                s.gtfs_stops,
                [
                    {**r, "lat": float(r["lat"]) if r["lat"] else None, "lon": float(r["lon"]) if r["lon"] else None}
                    for r in rows(
                        "stops",
                        {
                            "stop_id": "stop_id",
                            "code": "stop_code",
                            "name": "stop_name",
                            "lat": "stop_lat",
                            "lon": "stop_lon",
                        },
                    )
                ],
            ),
            (
                s.gtfs_trips,
                [
                    {**r, "direction_id": int(r["direction_id"]) if r["direction_id"] else None}
                    for r in rows(
                        "trips",
                        {
                            "trip_id": "trip_id",
                            "route_id": "route_id",
                            "service_id": "service_id",
                            "headsign": "trip_headsign",
                            "direction_id": "direction_id",
                            "block_id": "block_id",
                            "shape_id": "shape_id",
                        },
                    )
                ],
            ),
            (
                s.gtfs_stop_times,
                [
                    {**r, "stop_sequence": int(r["stop_sequence"])}
                    for r in rows(
                        "stop_times",
                        {
                            "trip_id": "trip_id",
                            "stop_sequence": "stop_sequence",
                            "stop_id": "stop_id",
                            "arrival_time": "arrival_time",
                            "departure_time": "departure_time",
                        },
                    )
                ],
            ),
            (
                s.gtfs_shapes,
                [
                    {**r, "sequence": int(r["sequence"]), "lat": float(r["lat"]), "lon": float(r["lon"])}
                    for r in rows(
                        "shapes",
                        {
                            "shape_id": "shape_id",
                            "sequence": "shape_pt_sequence",
                            "lat": "shape_pt_lat",
                            "lon": "shape_pt_lon",
                        },
                    )
                ],
            ),
            (
                s.gtfs_calendar_dates,
                [
                    {**r, "date": _date(r["date"]), "exception_type": int(r["exception_type"])}
                    for r in rows(
                        "calendar_dates",
                        {"service_id": "service_id", "date": "date", "exception_type": "exception_type"},
                    )
                ],
            ),
            (
                s.gtfs_calendar,
                [
                    {
                        "feed_version_id": version_id,
                        "service_id": c["service_id"],
                        "days": "".join(
                            c.get(d, "0")
                            for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
                        ),
                        "start_date": _date(c.get("start_date")),
                        "end_date": _date(c.get("end_date")),
                    }
                    for c in feed.table("calendar")
                ],
            ),
        ]
        for table, data in tables:
            for chunk in _chunks(data):
                conn.execute(insert(table), chunk)
        return SavedVersion(version_id, True, archive_path)


def activate_version(engine: Engine, system_id: int, version_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(s.feed_versions)
            .where(s.feed_versions.c.system_id == system_id, s.feed_versions.c.active)
            .values(active=False)
        )
        conn.execute(update(s.feed_versions).where(s.feed_versions.c.id == version_id).values(active=True))


def active_version(engine: Engine, system_id: int) -> tuple[int, str] | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(s.feed_versions.c.id, s.feed_versions.c.archive_path).where(
                s.feed_versions.c.system_id == system_id, s.feed_versions.c.active
            )
        ).first()
    return None if row is None else (row.id, row.archive_path)


# ---- realtime history ----


def insert_vehicle_positions(
    engine: Engine, system_id: int, snap: Snapshot, tracks: dict[str, TrackPosition | None]
) -> int:
    rows = []
    for v in snap.vehicles:
        track = tracks.get(v.vehicle_id)
        rows.append(
            {
                "system_id": system_id,
                "vehicle_id": v.vehicle_id,
                "observed_at": _ts(v.timestamp or snap.header_timestamp),
                "feed_at": _ts(snap.header_timestamp),
                "trip_id": v.trip_id,
                "route_id": v.route_id,
                "start_date": v.start_date,
                "start_time": v.start_time,
                "lat": v.lat,
                "lon": v.lon,
                "bearing": v.bearing,
                "speed": v.speed,
                "stop_id": v.stop_id,
                "stop_sequence": v.current_stop_sequence,
                "status": v.status,
                "occupancy": v.occupancy,
                "shape_index": track.shape_index if track else None,
                "distance_along": track.distance_along if track else None,
            }
        )
    if not rows:
        return 0
    with engine.begin() as conn:
        result = conn.execute(pg_insert(s.vehicle_positions).on_conflict_do_nothing(), rows)
    return result.rowcount or 0


class PredictionDeduper:
    """Remembers the last stored prediction per (trip, start date, stop), so
    only meaningful changes are stored: a predicted time (or delay) moving by
    at least `threshold_seconds`, or a schedule relationship changing. The
    first observation of each key is always stored, so after a restart the
    first fetch is stored in full."""

    def __init__(self, threshold_seconds: float = 30) -> None:
        self.threshold = threshold_seconds
        self.last: dict[tuple[str, str, str], tuple[Any, ...]] = {}

    def _moved(self, old: tuple[Any, ...], new: tuple[Any, ...]) -> bool:
        if len(old) != len(new):
            return True
        if len(new) == 1:  # trip-level row: (trip relationship,)
            return old != new
        *old_times, old_rel, old_trip_rel = old
        *new_times, new_rel, new_trip_rel = new
        if (old_rel, old_trip_rel) != (new_rel, new_trip_rel):
            return True
        for a, b in zip(old_times, new_times, strict=True):
            if (a is None) != (b is None):
                return True
            if a is not None and abs(b - a) >= self.threshold:
                return True
        return False

    def changed_rows(self, system_id: int, snap: Snapshot, trip_dates: dict[str, str]) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for tu in snap.trip_updates:
            start_date = tu.start_date or trip_dates.get(tu.trip_id, "")
            for stu in tu.stop_updates or (None,):
                stop_key = (
                    ""
                    if stu is None
                    else (str(stu.stop_sequence) if stu.stop_sequence is not None else stu.stop_id or "")
                )
                key = (tu.trip_id, start_date, stop_key)
                seen.add(key)
                value: tuple[Any, ...] = (
                    (tu.relationship,)
                    if stu is None
                    else (stu.arrival_time, stu.departure_time, stu.delay, stu.relationship, tu.relationship)
                )
                previous = self.last.get(key)
                if previous is not None and not self._moved(previous, value):
                    continue
                self.last[key] = value
                rows.append(_prediction_row(system_id, snap.header_timestamp, tu, start_date, stop_key, stu))
        for key in list(self.last):
            if key not in seen:
                del self.last[key]
        return rows


def _prediction_row(
    system_id: int, observed: int, tu: TripUpdate, start_date: str, stop_key: str, stu: Any
) -> dict[str, Any]:
    return {
        "system_id": system_id,
        "trip_id": tu.trip_id,
        "start_date": start_date,
        "stop_key": stop_key,
        "observed_at": _ts(observed),
        "stop_id": stu.stop_id if stu else None,
        "stop_sequence": stu.stop_sequence if stu else None,
        "arrival_at": _ts(stu.arrival_time) if stu else None,
        "departure_at": _ts(stu.departure_time) if stu else None,
        "delay": stu.delay if stu else None,
        "relationship": stu.relationship if stu else None,
        "trip_relationship": tu.relationship,
    }


def insert_stop_predictions(engine: Engine, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with engine.begin() as conn:
        for chunk in _chunks(rows):
            conn.execute(pg_insert(s.stop_predictions).on_conflict_do_nothing(), chunk)
    return len(rows)


def upsert_alerts(engine: Engine, system_id: int, alerts: Sequence[Alert], seen_at: float) -> None:
    with engine.begin() as conn:
        for a in alerts:
            periods = [{"start": p.start, "end": p.end} for p in a.active_periods]
            content = json.dumps(
                [a.header, a.description, a.url, a.cause, a.effect, a.route_ids, a.stop_ids, periods], sort_keys=True
            )
            stmt = pg_insert(s.alerts).values(
                system_id=system_id,
                alert_id=a.id,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                first_seen=_ts(seen_at),
                last_seen=_ts(seen_at),
                header=a.header,
                description=a.description,
                url=a.url,
                cause=a.cause,
                effect=a.effect,
                route_ids=list(a.route_ids),
                stop_ids=list(a.stop_ids),
                active_periods=periods,
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=[s.alerts.c.system_id, s.alerts.c.alert_id, s.alerts.c.content_sha256],
                    set_={"last_seen": _ts(seen_at)},
                )
            )


# ---- live documents ----


def save_document(engine: Engine, system_id: int, kind: str, doc: dict[str, Any], built_at: float) -> str:
    body = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()
    etag = hashlib.sha256(body).hexdigest()[:20]
    stmt = pg_insert(s.live_documents).values(
        system_id=system_id, kind=kind, etag=etag, body_gzip=gzip.compress(body, 6), built_at=_ts(built_at)
    )
    with engine.begin() as conn:
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[s.live_documents.c.system_id, s.live_documents.c.kind],
                set_={"etag": etag, "body_gzip": stmt.excluded.body_gzip, "built_at": stmt.excluded.built_at},
            )
        )
    return etag


@dataclass(frozen=True)
class StoredDocument:
    etag: str
    body_gzip: bytes
    built_at: dt.datetime


def get_document(engine: Engine, slug: str, kind: str) -> StoredDocument | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(s.live_documents.c.etag, s.live_documents.c.body_gzip, s.live_documents.c.built_at)
            .join(s.systems, s.systems.c.id == s.live_documents.c.system_id)
            .where(s.systems.c.slug == slug, s.live_documents.c.kind == kind)
        ).first()
    return None if row is None else StoredDocument(row.etag, row.body_gzip, row.built_at)


def feed_health(engine: Engine) -> list[dict[str, Any]]:
    """Per system and feed: when it last succeeded, and the latest feed timestamp."""
    with engine.connect() as conn:
        last_ok = (
            select(
                s.feed_fetches.c.system_id,
                s.feed_fetches.c.feed,
                func.max(s.feed_fetches.c.fetched_at).label("last_success"),
                func.max(s.feed_fetches.c.header_at).label("last_header"),
            )
            .where(s.feed_fetches.c.error.is_(None))
            .group_by(s.feed_fetches.c.system_id, s.feed_fetches.c.feed)
            .subquery()
        )
        rows = conn.execute(
            select(s.systems.c.slug, last_ok.c.feed, last_ok.c.last_success, last_ok.c.last_header)
            .join(last_ok, last_ok.c.system_id == s.systems.c.id)
            .order_by(s.systems.c.slug, last_ok.c.feed)
        ).all()
        versions = conn.execute(
            select(s.systems.c.slug, s.feed_versions.c.feed_version, s.feed_versions.c.end_date)
            .join(s.feed_versions, s.feed_versions.c.system_id == s.systems.c.id)
            .where(s.feed_versions.c.active)
        ).all()
    expiry = {v.slug: (v.feed_version, v.end_date) for v in versions}
    return [
        {
            "system": r.slug,
            "feed": r.feed,
            "last_success": r.last_success,
            "last_header": r.last_header,
            "timetable_version": expiry.get(r.slug, (None, None))[0],
            "timetable_end": expiry.get(r.slug, (None, None))[1],
        }
        for r in rows
    ]
