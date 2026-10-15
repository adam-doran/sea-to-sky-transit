"""The raw archive: every distinct feed fetch, compressed, on disk.

Layout (dates in UTC, so daylight saving never makes a folder ambiguous):
    {root}/{system}/{feed}/{YYYY-MM-DD}/{header_timestamp}.pb.zst
    {root}/{system}/static/{YYYY-MM-DD}_{sha256[:16]}.zip

These files are the source of truth: the database can be rebuilt from them.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterator
from pathlib import Path

import zstandard

# zstandard compressors aren't thread-safe and the collector writes from
# worker threads, so each call makes its own (cheap) compressor.
ZSTD_LEVEL = 10


def _utc_day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Archive:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def realtime_path(self, system: str, feed: str, header_ts: int) -> Path:
        return self.root / system / feed / _utc_day(header_ts) / f"{header_ts}.pb.zst"

    def write_realtime(self, system: str, feed: str, header_ts: int, data: bytes) -> Path:
        path = self.realtime_path(system, feed, header_ts)
        if not path.exists():
            _atomic_write(path, zstandard.ZstdCompressor(level=ZSTD_LEVEL).compress(data))
        return path

    def write_static(self, system: str, sha256: str, data: bytes, fetched_at: float) -> Path:
        path = self.root / system / "static" / f"{_utc_day(fetched_at)}_{sha256[:16]}.zip"
        if not path.exists():
            _atomic_write(path, data)
        return path

    def iter_realtime(self, system: str, feed: str) -> Iterator[tuple[int, Path]]:
        """Archived snapshots of one feed, oldest first."""
        base = self.root / system / feed
        if not base.exists():
            return
        for day in sorted(base.iterdir()):
            files = sorted(day.glob("*.pb.zst"), key=lambda p: int(p.name.split(".")[0]))
            for f in files:
                yield int(f.name.split(".")[0]), f

    def iter_static(self, system: str) -> Iterator[Path]:
        base = self.root / system / "static"
        if base.exists():
            yield from sorted(base.glob("*.zip"))

    @staticmethod
    def read(path: Path) -> bytes:
        data = path.read_bytes()
        return zstandard.ZstdDecompressor().decompress(data) if path.suffix == ".zst" else data
