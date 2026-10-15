"""Replay archived feeds through the collector, on a fake clock.

Used by tests, the end-to-end test stack and local development without
network access. The archive layout is the collector's own, so any slice of the
production archive (or tests/fixtures/archive) can be replayed, from
individual files, daily bundles, or both.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import heapq
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from transitlive.collector.archive import Archive
from transitlive.collector.fetch import FetchResult, Limits
from transitlive.collector.realtime import decode
from transitlive.collector.service import Collector
from transitlive.config import REALTIME_FEEDS, Config
from transitlive.db.engine import ensure_partitions

log = logging.getLogger("transitlive.replay")


class ArchiveFetcher:
    """Stands in for BC Transit: serves each system's newest archived timetable."""

    def __init__(self, config: Config, archive: Archive) -> None:
        self.by_url: dict[str, tuple[str, Callable[[], bytes]]] = {}
        for system in config.systems:
            found = archive.latest_static(system.slug)
            if found is not None:
                self.by_url[config.collector.static(system)] = found

    async def get(self, url: str, limits: Limits) -> FetchResult:  # the archive is already trusted
        found = self.by_url.get(url)
        if found is None:
            return FetchResult(url, 404, None, None, 0, "HTTP 404")
        name, load = found
        return FetchResult(url, 200, load(), name.removesuffix(".zip").split("_")[-1], 0)

    async def aclose(self) -> None:
        pass


@dataclass(frozen=True, order=True)
class Event:
    timestamp: int
    slug: str
    feed: str
    data: bytes = field(compare=False, repr=False)


def _stream(archive: Archive, slug: str, feed: str) -> Iterator[Event]:
    for ts, data in archive.snapshots(slug, feed):
        yield Event(ts, slug, feed, data)


def events(config: Config, archive: Archive) -> Iterator[Event]:
    """All archived snapshots for the configured systems, in time order."""
    # A helper function, not a nested generator expression: those bind
    # slug and feed late, labelling every snapshot with the last ones.
    yield from heapq.merge(*(_stream(archive, s.slug, feed) for s in config.systems for feed in REALTIME_FEEDS))


class Replayer:
    def __init__(self, config: Config, engine: Engine, archive_root: str | Path) -> None:
        self.config = config
        self.archive = Archive(archive_root)
        self.now = 0.0
        self.collector = Collector(
            config,
            engine,
            self.archive,
            ArchiveFetcher(config, self.archive),  # type: ignore[arg-type]
            clock=lambda: self.now,
        )

    async def prepare(self) -> None:
        first = next(events(self.config, self.archive), None)
        if first is None:
            raise SystemExit(f"nothing to replay in {self.archive.root}")
        self.now = first.timestamp
        await self.collector.prepare()
        # History older than the collector's own partitions (a rebuild from
        # bundles) gets monthly partitions too, not the DEFAULT one
        first_day = dt.datetime.fromtimestamp(first.timestamp, dt.UTC).date()
        today = dt.datetime.now(dt.UTC).date()
        months = max(0, (today.year - first_day.year) * 12 + today.month - first_day.month)
        await asyncio.to_thread(ensure_partitions, self.collector.engine, first_day, months + 2)

    async def step(self, event: Event) -> None:
        self.now = event.timestamp
        snap = decode(event.feed, event.data)
        await self.collector.ingest(event.slug, snap)

    async def run(self, speed: float = 1.0, loop: bool = False) -> int:
        """Replay in (scaled) real time. speed=0 replays as fast as possible."""
        await self.prepare()
        count = 0
        while True:
            previous: int | None = None
            for event in events(self.config, self.archive):
                if speed > 0 and previous is not None and event.timestamp > previous:
                    await asyncio.sleep((event.timestamp - previous) / speed)
                previous = event.timestamp
                await self.step(event)
                count += 1
            log.info("replayed %d snapshots", count)
            if not loop:
                return count
