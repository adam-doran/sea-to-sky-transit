"""Limits on what the collector takes from upstream: download size and time,
redirects, timetable zip size, and archive paths read back from the database."""

from __future__ import annotations

import asyncio
import io
import zipfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.builders import gtfs_zip
from transitlive.collector.archive import Archive
from transitlive.collector.fetch import Fetcher, Limits
from transitlive.gtfs import load
from transitlive.gtfs.load import read_gtfs_zip

URL = "https://bct.tmix.se/gtfs-realtime/vehicleupdates.pb?operatorIds=43"
SMALL = Limits(max_bytes=1000, deadline_seconds=5)


async def get(handler: Callable[[httpx.Request], httpx.Response], limits: Limits = SMALL) -> tuple[object, ...]:
    fetcher = Fetcher("test", 5, transport=httpx.MockTransport(handler))
    try:
        r = await fetcher.get(URL, limits)
    finally:
        await fetcher.aclose()
    return r.ok, r.status, r.body, r.error


async def test_a_body_within_the_cap_is_returned() -> None:
    assert await get(lambda _: httpx.Response(200, content=b"x" * 1000)) == (True, 200, b"x" * 1000, None)


async def test_errors_keep_their_status() -> None:
    assert await get(lambda _: httpx.Response(503)) == (False, 503, None, "HTTP 503")


async def test_a_declared_size_over_the_cap_is_refused() -> None:
    ok, status, body, error = await get(lambda _: httpx.Response(200, content=b"x" * 1001))
    assert (ok, status, body) == (False, 200, None)
    assert error == "response over 1,000 bytes"


async def test_a_streamed_body_over_the_cap_is_refused() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(100):
            yield b"x" * 100

    ok, _, body, error = await get(lambda _: httpx.Response(200, content=chunks()))  # no Content-Length
    assert (ok, body, error) == (False, None, "response over 1,000 bytes")


async def test_a_slow_drip_hits_the_deadline() -> None:
    async def drip() -> AsyncIterator[bytes]:
        for _ in range(100):
            await asyncio.sleep(0.05)  # each read is quick; the whole response isn't
            yield b"x"

    ok, _, body, error = await get(lambda _: httpx.Response(200, content=drip()), Limits(1000, 0.3))
    assert (ok, body, error) == (False, None, "no complete response within 0.3s")


def redirecting(location: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/moved":
            return httpx.Response(200, content=b"here")
        return httpx.Response(302, headers={"Location": location})

    return handler


async def test_redirects_are_followed_on_the_same_host_over_https() -> None:
    assert await get(redirecting("/moved")) == (True, 200, b"here", None)
    assert await get(redirecting("https://bct.tmix.se/moved")) == (True, 200, b"here", None)


@pytest.mark.parametrize(
    ("location", "error"),
    [
        ("http://bct.tmix.se/moved", "redirect to http://bct.tmix.se refused"),
        ("https://example.com/moved", "redirect to https://example.com refused"),
        ("https://bct.tmix.se:8443/moved", "redirect to https://bct.tmix.se refused"),
    ],
)
async def test_other_redirects_are_refused(location: str, error: str) -> None:
    assert await get(redirecting(location)) == (False, 302, None, error)


async def test_redirect_loops_end() -> None:
    assert await get(redirecting("/again")) == (False, None, None, "more than 3 redirects")


def small_feed() -> dict[str, list[dict[str, Any]]]:
    return {
        "routes": [{"route_id": "R1", "route_short_name": "1", "route_type": 3}],
        "trips": [{"route_id": "R1", "service_id": "S1", "trip_id": "T1"}],
        "stop_times": [{"trip_id": "T1", "arrival_time": "08:00:00", "stop_id": "S1", "stop_sequence": 1}],
    }


def test_a_zip_claiming_too_much_is_refused_before_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    data = gtfs_zip(small_feed())
    size = sum(i.file_size for i in zipfile.ZipFile(io.BytesIO(data)).infolist())
    monkeypatch.setattr(load, "MAX_UNCOMPRESSED_BYTES", size - 1)
    with pytest.raises(ValueError, match="uncompressed"):
        read_gtfs_zip(data)
    monkeypatch.setattr(load, "MAX_UNCOMPRESSED_BYTES", size)
    assert read_gtfs_zip(data).table("routes")


def test_files_outside_the_gtfs_tables_are_not_read() -> None:
    tables = small_feed()
    plain = gtfs_zip(tables)
    buf = io.BytesIO(plain)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("transfers.txt", "from_stop_id,to_stop_id\n")
        zf.writestr("extra/huge.bin", b"\0" * 10_000)
    with_extras = read_gtfs_zip(buf.getvalue())
    assert set(with_extras.tables) == set(tables)
    assert with_extras.content_sha256 == read_gtfs_zip(plain).content_sha256


def test_archive_paths_stay_inside_the_archive(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    (root / "squamish" / "static").mkdir(parents=True)
    (root / "squamish" / "static" / "2026-10-15_x.zip").write_bytes(b"zip")
    (tmp_path / "secret").write_bytes(b"no")
    archive = Archive(root)
    assert archive.load("squamish/static/2026-10-15_x.zip") == b"zip"
    for path in ("../secret", "squamish/../../secret", str(tmp_path / "secret")):
        with pytest.raises(ValueError, match="outside the archive"):
            archive.load(path)
