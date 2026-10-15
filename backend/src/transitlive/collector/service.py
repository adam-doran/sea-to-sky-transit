"""The collector: the only part of the system that talks to BC Transit.

Per system it polls each realtime feed on a fixed interval, whatever the
number of users, and syncs the static timetable every few hours. Every fetch
is logged; every new snapshot is archived, stored as history, applied to the
system's runtime, and turned into the documents the API serves.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Engine

from transitlive.collector.archive import Archive
from transitlive.collector.fetch import Backoff, Fetcher, Spacing
from transitlive.collector.realtime import FeedError, decode
from transitlive.config import REALTIME_FEEDS, Config, System
from transitlive.db import store
from transitlive.db.engine import ensure_partitions
from transitlive.domain.model import Snapshot, Timetable
from transitlive.domain.service_day import local_date
from transitlive.gtfs.compile import compile_timetable
from transitlive.gtfs.load import read_gtfs_zip
from transitlive.live.runtime import SystemRuntime

log = logging.getLogger("transitlive.collector")

FORCED_SYNC_COOLDOWN_SECONDS = 15 * 60
START_STAGGER_SECONDS = 1.1
DOCS_FOR_FEED = {
    "vehicleupdates": ("live",),
    "tripupdates": ("live", "departures"),
    "alerts": ("live",),
}


def covers(tt: Timetable, now: float) -> bool:
    """Does this timetable describe today's service?"""
    today = local_date(now, tt.timezone)
    if today in tt.services:
        return True
    return bool(tt.start_date and tt.end_date and tt.start_date <= today <= tt.end_date)


@dataclass
class SystemTask:
    system: System
    runtime: SystemRuntime | None = None
    last_sha: dict[str, str] = field(default_factory=dict)
    backoff: dict[str, Backoff] = field(default_factory=dict)
    deduper: store.PredictionDeduper = field(default_factory=store.PredictionDeduper)
    last_forced_sync: float = 0.0
    sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Collector:
    def __init__(
        self,
        config: Config,
        engine: Engine,
        archive: Archive,
        fetcher: Fetcher,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.engine = engine
        self.archive = archive
        self.fetcher = fetcher
        self.clock = clock
        self.tasks = {s.slug: SystemTask(s) for s in config.systems}

    # ---- startup ----

    async def prepare(self) -> None:
        await asyncio.to_thread(store.sync_systems, self.engine, self.config.systems)
        today = dt.datetime.fromtimestamp(self.clock(), dt.UTC).date()
        await asyncio.to_thread(ensure_partitions, self.engine, today)
        for task in self.tasks.values():
            await self._restore_timetable(task)
            if task.runtime is None:
                await self.sync_static(task.system.slug)

    async def _restore_timetable(self, task: SystemTask) -> None:
        """Start from the active timetable in the archive, so a restart doesn't
        depend on BC Transit being reachable."""
        found = await asyncio.to_thread(store.active_version, self.engine, task.system.operator_id)
        if found is None:
            return
        version_id, path = found
        try:
            data = await asyncio.to_thread(Archive.read, self.archive.root / path)
        except FileNotFoundError:
            log.warning("%s: active timetable %s missing from the archive", task.system.slug, path)
            return
        tt = await asyncio.to_thread(lambda: compile_timetable(read_gtfs_zip(data), task.system.timezone))
        task.runtime = SystemRuntime(task.system, tt, version_id)
        await self._publish(task, ("static", "live", "departures"))
        log.info("%s: restored timetable %s", task.system.slug, tt.feed_version)

    # ---- static timetable ----

    async def sync_static(self, slug: str) -> bool:
        """Download the timetable; store it if new; activate it if it covers
        today. Returns True when the active timetable changed."""
        task = self.tasks[slug]
        system = task.system
        async with task.sync_lock:
            url = self.config.collector.static(system)
            now = self.clock()
            result = await self.fetcher.get(url)
            await asyncio.to_thread(
                store.record_fetch,
                self.engine,
                system.operator_id,
                "static",
                now,
                url,
                result.status,
                len(result.body) if result.body else None,
                result.sha256,
                None,
                result.latency_ms,
                False,
                result.error,
            )
            if not result.ok or result.body is None or result.sha256 is None:
                log.warning("%s: timetable download failed: %s", slug, result.error)
                return False
            try:
                feed = await asyncio.to_thread(read_gtfs_zip, result.body)
                tt = await asyncio.to_thread(compile_timetable, feed, system.timezone)
            except Exception as e:  # a broken zip must never take down the collector
                log.error("%s: timetable rejected: %s", slug, e)
                return False
            path = await asyncio.to_thread(self.archive.write_static, slug, result.sha256, result.body, now)
            saved = await asyncio.to_thread(
                store.save_feed_version,
                self.engine,
                system.operator_id,
                feed,
                str(path.relative_to(self.archive.root)),
                now,
            )
            current = task.runtime
            same = current is not None and current.timetable_version_id == saved.id
            if same or not covers(tt, now):
                if not same:
                    log.info("%s: timetable %s doesn't cover today yet; keeping the current one", slug, tt.feed_version)
                return False
            await asyncio.to_thread(store.activate_version, self.engine, system.operator_id, saved.id)
            if current is None:
                task.runtime = SystemRuntime(system, tt, saved.id)
            else:
                current.set_timetable(tt, saved.id)
            log.info("%s: activated timetable %s (%s)", slug, tt.feed_version, "new" if saved.is_new else "stored")
            await self._publish(task, ("static", "live", "departures"))
            return True

    # ---- realtime ----

    async def poll_once(self, slug: str, feed: str) -> Snapshot | None:
        task = self.tasks[slug]
        system = task.system
        backoff = task.backoff.setdefault(feed, Backoff(base=self.config.collector.intervals[feed]))
        now = self.clock()
        if not backoff.ready(now):
            return None
        url = self.config.collector.realtime(feed, system)
        result = await self.fetcher.get(url)
        snap: Snapshot | None = None
        error = result.error
        if result.ok and result.body is not None:
            try:
                snap = decode(feed, result.body)
            except FeedError as e:
                error = str(e)
        is_new = snap is not None and result.sha256 != task.last_sha.get(feed)
        await asyncio.to_thread(
            store.record_fetch,
            self.engine,
            system.operator_id,
            feed,
            now,
            url,
            result.status,
            len(result.body) if result.body else None,
            result.sha256,
            snap.header_timestamp if snap else None,
            result.latency_ms,
            is_new,
            error,
        )
        if snap is None or result.body is None:
            wait = backoff.failure(now)
            log.warning("%s %s failed (%s); next try in %.0fs", slug, feed, error, wait)
            return None
        backoff.success()
        if is_new and result.sha256:
            task.last_sha[feed] = result.sha256
            await asyncio.to_thread(self.archive.write_realtime, slug, feed, snap.header_timestamp, result.body)
            await self.ingest(slug, snap)
        else:
            # Same data, but times have moved on: refresh the documents
            await self._publish(task, DOCS_FOR_FEED[feed])
        return snap

    async def ingest(self, slug: str, snap: Snapshot) -> None:
        """Apply a new snapshot: runtime, history tables, documents."""
        task = self.tasks[slug]
        rt = task.runtime
        if rt is None:
            return
        sid = task.system.operator_id
        rt.apply(snap)
        if snap.feed == "vehicleupdates":
            await asyncio.to_thread(store.insert_vehicle_positions, self.engine, sid, snap, dict(rt.tracks))
            if rt.timetable_out_of_date and self.clock() - task.last_forced_sync > FORCED_SYNC_COOLDOWN_SECONDS:
                task.last_forced_sync = self.clock()
                log.warning("%s: live trips don't match the timetable; syncing now", slug)
                asyncio.get_running_loop().create_task(self.sync_static(slug))
        elif snap.feed == "tripupdates":
            trip_dates = {v.trip_id: v.start_date for v in rt.live.vehicles if v.trip_id and v.start_date}
            rows = task.deduper.changed_rows(sid, snap, trip_dates)
            await asyncio.to_thread(store.insert_stop_predictions, self.engine, rows)
        elif snap.feed == "alerts":
            await asyncio.to_thread(store.upsert_alerts, self.engine, sid, snap.alerts, snap.header_timestamp)
        await self._publish(task, DOCS_FOR_FEED[snap.feed])

    async def _publish(self, task: SystemTask, kinds: tuple[str, ...]) -> None:
        rt = task.runtime
        if rt is None:
            return
        now = self.clock()
        for kind in kinds:
            if kind == "static":
                doc = rt.static_document()
            elif kind == "live":
                doc = rt.live_document(now)
            else:
                doc = rt.departures_document(now)
            await asyncio.to_thread(store.save_document, self.engine, task.system.operator_id, kind, doc, now)

    # ---- scheduling ----

    async def _feed_loop(self, slug: str, feed: str, start_delay: float = 0.0) -> None:
        spacing = Spacing(self.config.collector.intervals[feed], name=f"{slug} {feed}")
        await asyncio.sleep(start_delay)
        while True:
            await spacing.wait()
            spacing.mark()
            try:
                await self.poll_once(slug, feed)
            except Exception:
                log.exception("%s %s: unexpected error", slug, feed)

    async def _static_loop(self, slug: str) -> None:
        period = self.config.collector.static_sync_hours * 3600
        while True:
            await asyncio.sleep(period)
            try:
                await self.sync_static(slug)
            except Exception:
                log.exception("%s: timetable sync failed", slug)

    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(6 * 3600)
            try:
                await asyncio.to_thread(ensure_partitions, self.engine, dt.datetime.now(dt.UTC).date())
            except Exception:
                log.exception("partition maintenance failed")

    async def run(self) -> None:
        await self.prepare()
        # Stagger the loops so BC Transit sees a steady trickle, not bursts
        pairs = [(slug, feed) for slug in self.tasks for feed in REALTIME_FEEDS]
        loops = [self._feed_loop(slug, feed, i * START_STAGGER_SECONDS) for i, (slug, feed) in enumerate(pairs)]
        loops += [self._static_loop(slug) for slug in self.tasks]
        loops.append(self._maintenance_loop())
        log.info("collecting %d systems: %s", len(self.tasks), ", ".join(self.tasks))
        await asyncio.gather(*loops)
