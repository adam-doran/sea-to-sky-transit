"""Polite HTTP fetching from BC Transit.

One client for the whole collector. Every request identifies the project in
its User-Agent and has a timeout. After a failure the next attempt for that
system and feed waits with exponential backoff and jitter, so an outage at
BC Transit never turns into a burst of retries.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

MAX_BACKOFF_SECONDS = 300
EARLY_WAKE_WARN_SECONDS = 0.5  # timers routinely fire a few ms early; only bigger gaps are news

log = logging.getLogger("transitlive.fetch")


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int | None
    body: bytes | None
    sha256: str | None
    latency_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.body is not None and self.error is None


@dataclass
class Backoff:
    """Exponential backoff with full jitter, per (system, feed)."""

    base: float
    failures: int = 0
    not_before: float = 0.0
    rng: random.Random = field(default_factory=random.Random)

    def ready(self, now: float) -> bool:
        return now >= self.not_before

    def success(self) -> None:
        self.failures = 0
        self.not_before = 0.0

    def failure(self, now: float) -> float:
        self.failures += 1
        delay = min(MAX_BACKOFF_SECONDS, self.base * 2**self.failures)
        wait = self.rng.uniform(self.base, delay)
        self.not_before = now + wait
        return wait


class Spacing:
    """Never start two requests to the same feed less than `interval` apart.

    asyncio's timers follow the monotonic clock, which can jump forward in a
    virtual machine (Docker Desktop does this), waking every sleeping loop at
    once. So the gap is checked on both the monotonic and the wall clock, and
    re-checked after every wake-up. A wall clock that has gone backwards (more
    than one interval) is ignored rather than waited out.
    """

    def __init__(
        self,
        interval: float,
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        name: str = "",
    ) -> None:
        self.interval = interval
        self.mono = mono
        self.wall = wall
        self.name = name
        self.last_mono: float | None = None
        self.last_wall: float | None = None

    def remaining(self) -> float:
        if self.last_mono is None or self.last_wall is None:
            return 0.0
        by_mono = self.last_mono + self.interval - self.mono()
        by_wall = self.last_wall + self.interval - self.wall()
        if by_wall > self.interval:  # the wall clock went backwards
            by_wall = 0.0
        return max(by_mono, by_wall, 0.0)

    async def wait(self) -> None:
        slept = False
        while (left := self.remaining()) > 0:
            if slept and left > EARLY_WAKE_WARN_SECONDS:
                log.warning("%s: woke %.1fs early (clock jump?); waiting again", self.name, left)
            await asyncio.sleep(left)
            slept = True

    def mark(self) -> None:
        self.last_mono = self.mono()
        self.last_wall = self.wall()


class Fetcher:
    def __init__(self, user_agent: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/x-protobuf, application/zip, */*"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    async def get(self, url: str) -> FetchResult:
        start = time.monotonic()
        try:
            resp = await self.client.get(url)
        except httpx.HTTPError as e:
            return FetchResult(
                url, None, None, None, int((time.monotonic() - start) * 1000), f"{type(e).__name__}: {e}"
            )
        latency = int((time.monotonic() - start) * 1000)
        if resp.status_code != 200:
            return FetchResult(url, resp.status_code, None, None, latency, f"HTTP {resp.status_code}")
        body = resp.content
        return FetchResult(url, 200, body, hashlib.sha256(body).hexdigest(), latency)

    async def aclose(self) -> None:
        await self.client.aclose()
