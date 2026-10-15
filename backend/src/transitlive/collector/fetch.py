"""Polite HTTP fetching from BC Transit.

One client for the whole collector. Every request identifies the project in
its User-Agent and has a timeout. After a failure the next attempt for that
system and feed waits with exponential backoff and jitter, so an outage at
BC Transit never turns into a burst of retries.

Downloads are bounded too: each kind has a size cap and a deadline for the
whole request, and redirects are followed only to https on the same host.
A download that breaks a limit is a failed fetch like any other.
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
MAX_REDIRECTS = 3
EARLY_WAKE_WARN_SECONDS = 0.5  # timers routinely fire a few ms early; only bigger gaps are news

log = logging.getLogger("transitlive.fetch")


@dataclass(frozen=True)
class Limits:
    max_bytes: int  # after any Content-Encoding is undone
    deadline_seconds: float  # for the whole request, however slowly the bytes arrive


REALTIME = Limits(5 * 2**20, 30)  # snapshots are tens of kilobytes
TIMETABLE = Limits(100 * 2**20, 300)  # zips are well under 1 MB today


class Refused(Exception):
    """A response the fetcher won't take: too big, or a redirect elsewhere."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


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
            timeout=timeout,  # per connect, read and write; Limits.deadline_seconds caps the whole request
            follow_redirects=False,  # see _download
            transport=transport,
        )

    async def get(self, url: str, limits: Limits) -> FetchResult:
        start = time.monotonic()

        def failed(error: str, status: int | None = None) -> FetchResult:
            return FetchResult(url, status, None, None, int((time.monotonic() - start) * 1000), error)

        try:
            async with asyncio.timeout(limits.deadline_seconds):
                status, body = await self._download(url, limits.max_bytes)
        except TimeoutError:
            return failed(f"no complete response within {limits.deadline_seconds:g}s")
        except Refused as e:
            return failed(str(e), e.status)
        except httpx.HTTPError as e:
            return failed(f"{type(e).__name__}: {e}")
        if body is None:
            return failed(f"HTTP {status}", status)
        latency = int((time.monotonic() - start) * 1000)
        return FetchResult(url, 200, body, hashlib.sha256(body).hexdigest(), latency)

    async def _download(self, url: str, max_bytes: int) -> tuple[int, bytes | None]:
        """(status, body), with a body only for 200. Follows redirects only
        to https on the same host, so a redirect can't downgrade the
        connection or send the collector somewhere else."""
        origin = target = httpx.URL(url)
        for _ in range(MAX_REDIRECTS + 1):
            async with self.client.stream("GET", target) as resp:
                if resp.is_redirect:
                    target = resp.url.join(resp.headers["location"])
                    if target.scheme != "https" or (target.host, target.port) != (origin.host, origin.port):
                        raise Refused(f"redirect to {target.scheme}://{target.host} refused", resp.status_code)
                    continue
                if resp.status_code != 200:
                    return resp.status_code, None
                return 200, await _read_capped(resp, max_bytes)
        raise Refused(f"more than {MAX_REDIRECTS} redirects", None)

    async def aclose(self) -> None:
        await self.client.aclose()


async def _read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    too_big = Refused(f"response over {max_bytes:,} bytes", resp.status_code)
    declared = resp.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise too_big
    chunks: list[bytes] = []
    size = 0
    async for chunk in resp.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)
