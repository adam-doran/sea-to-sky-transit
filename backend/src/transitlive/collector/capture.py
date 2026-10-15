"""Record a stretch of real feeds into an archive directory, without a database.

Used to refresh the test fixtures (make fixtures). Keeps to the same polite
intervals as the collector.
"""

from __future__ import annotations

import asyncio
import logging
import time

from transitlive.collector.archive import Archive
from transitlive.collector.fetch import Fetcher, Spacing
from transitlive.collector.realtime import FeedError, decode
from transitlive.config import REALTIME_FEEDS, Config

log = logging.getLogger("transitlive.capture")


async def capture(config: Config, archive: Archive, minutes: float) -> int:
    fetcher = Fetcher(config.collector.user_agent, config.collector.timeout_seconds)
    saved = 0
    try:
        for system in config.systems:
            result = await fetcher.get(config.collector.static(system))
            if result.ok and result.body and result.sha256:
                archive.write_static(system.slug, result.sha256, result.body, time.time())

        async def loop(slug: str, feed: str, url: str, interval: float) -> None:
            nonlocal saved
            end = time.monotonic() + minutes * 60
            last = None
            spacing = Spacing(interval, name=f"{slug} {feed}")
            while time.monotonic() < end:
                await spacing.wait()
                spacing.mark()
                result = await fetcher.get(url)
                if result.ok and result.body and result.sha256 != last:
                    try:
                        snap = decode(feed, result.body)
                    except FeedError as e:
                        log.warning("%s %s: %s", slug, feed, e)
                    else:
                        archive.write_realtime(slug, feed, snap.header_timestamp, result.body)
                        last = result.sha256
                        saved += 1

        await asyncio.gather(
            *(
                loop(s.slug, feed, config.collector.realtime(feed, s), config.collector.intervals[feed])
                for s in config.systems
                for feed in REALTIME_FEEDS
            )
        )
    finally:
        await fetcher.aclose()
    return saved
