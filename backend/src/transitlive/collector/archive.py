"""The raw archive: every distinct feed fetch, compressed, on disk.

Layout (dates in UTC, so daylight saving never makes a folder ambiguous):
    {root}/{system}/{feed}/{YYYY-MM-DD}/{header_timestamp}.pb.zst
    {root}/{system}/static/{YYYY-MM-DD}_{sha256[:16]}.zip
    {root}/bundles/{system}/{YYYY-MM-DD}.tar.zst

The collector writes one file per snapshot. Each night it packs the previous
day into a bundle (collector/bundles.py): a zstd-compressed tar of that day's
snapshots, uncompressed inside, and its timetable zips, named
    {feed}/{header_timestamp}.pb
    static/{YYYY-MM-DD}_{sha256[:16]}.zip
Consecutive snapshots are nearly identical, so a bundle is far smaller than
the files it replaces, which are deleted a few days later.

Files and bundles together are the source of truth: the database can be
rebuilt from them, or from bundles alone. Members are written static first,
then by feed and timestamp, and readers rely on that order.
"""

from __future__ import annotations

import datetime as dt
import heapq
import os
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path

import zstandard

# zstandard compressors aren't thread-safe and the collector writes from
# worker threads, so each call makes its own (cheap) compressor.
ZSTD_LEVEL = 10
BUNDLES = "bundles"
STATIC = "static"


def _utc_day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _is_day(name: str) -> bool:
    try:
        dt.date.fromisoformat(name)
    except ValueError:
        return False
    return len(name) == 10


MemberKey = tuple[int, str, int, str]


def member_key(name: str) -> MemberKey:
    """Sort order of bundle members: timetables first, then by feed and time."""
    group, _, leaf = name.partition("/")
    if group == STATIC:
        return (0, "", 0, leaf)
    return (1, group, int(leaf.split(".")[0]), "")


def iter_bundle(path: Path, want: Callable[[str], bool] = lambda _: True) -> Iterator[tuple[str, bytes]]:
    """Stream a bundle's members, in the order they were written, without
    unpacking it. Members `want` rejects are skipped (still decompressed)."""
    with (
        path.open("rb") as f,
        zstandard.ZstdDecompressor().stream_reader(f) as reader,
        tarfile.open(fileobj=reader, mode="r|") as tar,
    ):
        for info in tar:
            if not info.isfile() or not want(info.name):
                continue
            member = tar.extractfile(info)
            if member is not None:
                yield info.name, member.read()


class Archive:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # ---- writing ----

    def realtime_path(self, system: str, feed: str, header_ts: int) -> Path:
        return self.root / system / feed / _utc_day(header_ts) / f"{header_ts}.pb.zst"

    def write_realtime(self, system: str, feed: str, header_ts: int, data: bytes) -> Path:
        path = self.realtime_path(system, feed, header_ts)
        if not path.exists():
            _atomic_write(path, zstandard.ZstdCompressor(level=ZSTD_LEVEL).compress(data))
        return path

    def write_static(self, system: str, sha256: str, data: bytes, fetched_at: float) -> Path:
        path = self.root / system / STATIC / f"{_utc_day(fetched_at)}_{sha256[:16]}.zip"
        if not path.exists():
            _atomic_write(path, data)
        return path

    # ---- individual files ----

    def iter_realtime(self, system: str, feed: str) -> Iterator[tuple[int, Path]]:
        """Archived snapshot files of one feed, oldest first (not bundles)."""
        for day in self.file_days(system, feed):
            yield from self.day_files(system, feed, day)

    def file_days(self, system: str, feed: str) -> list[dt.date]:
        """Days that still have individual snapshot files for one feed."""
        base = self.root / system / feed
        if not base.exists():
            return []
        return sorted(dt.date.fromisoformat(d.name) for d in base.iterdir() if d.is_dir() and _is_day(d.name))

    def day_files(self, system: str, feed: str, day: dt.date) -> list[tuple[int, Path]]:
        files = (self.root / system / feed / day.isoformat()).glob("*.pb.zst")
        return sorted((int(f.name.split(".")[0]), f) for f in files)

    def iter_static(self, system: str) -> Iterator[Path]:
        base = self.root / system / STATIC
        if base.exists():
            yield from sorted(base.glob("*.zip"))

    @staticmethod
    def read(path: Path) -> bytes:
        data = path.read_bytes()
        return zstandard.ZstdDecompressor().decompress(data) if path.suffix == ".zst" else data

    # ---- bundles ----

    def bundle_path(self, system: str, day: dt.date) -> Path:
        return self.root / BUNDLES / system / f"{day.isoformat()}.tar.zst"

    def bundle_days(self, system: str) -> list[dt.date]:
        base = self.root / BUNDLES / system
        if not base.exists():
            return []
        names = (p.name.removesuffix(".tar.zst") for p in base.glob("*.tar.zst"))
        return sorted(dt.date.fromisoformat(n) for n in names if _is_day(n))

    def has_bundles(self, systems: list[str], day: dt.date) -> bool:
        return all(self.bundle_path(s, day).exists() for s in systems)

    # ---- reading files and bundles alike ----

    def snapshots(self, system: str, feed: str) -> Iterator[tuple[int, bytes]]:
        """Every archived snapshot of one feed, oldest first, decompressed,
        whether it's still a file, already in a bundle, or both."""
        days = sorted(set(self.file_days(system, feed)) | set(self.bundle_days(system)))
        for day in days:
            yield from self._day_snapshots(system, feed, day)

    def _day_snapshots(self, system: str, feed: str, day: dt.date) -> Iterator[tuple[int, bytes]]:
        bundle = self.bundle_path(system, day)
        prefix = f"{feed}/"
        members = iter_bundle(bundle, lambda n: n.startswith(prefix)) if bundle.exists() else iter(())
        from_bundle = ((member_key(name)[2], 1, data) for name, data in members)
        from_files = ((ts, 0, path) for ts, path in self.day_files(system, feed, day))
        last: int | None = None
        # A snapshot can be both a file and a bundle member (until the file is
        # deleted). Files sort first at the same timestamp; each is yielded once.
        merged: Iterator[tuple[int, int, bytes | Path]] = heapq.merge(from_files, from_bundle, key=lambda x: x[:2])
        for ts, _, item in merged:
            if ts != last:
                last = ts
                yield ts, item if isinstance(item, bytes) else self.read(item)

    def latest_static(self, system: str) -> tuple[str, Callable[[], bytes]] | None:
        """The newest archived timetable zip, as (file name, loader). Names
        start with the day they were fetched, so they sort by age."""
        best: tuple[str, Callable[[], bytes]] | None = None
        files = list(self.iter_static(system))
        if files:
            best = (files[-1].name, files[-1].read_bytes)
        for day in reversed(self.bundle_days(system)):
            if best is not None and best[0][:10] >= day.isoformat():
                break
            names = list(self._bundle_static_names(system, day))
            if names:
                member = f"{STATIC}/{names[-1]}"
                best = (names[-1], lambda d=day, m=member: self._bundle_member(system, d, m))
                break
        return best

    def _bundle_static_names(self, system: str, day: dt.date) -> Iterator[str]:
        """Timetable zip names in one bundle. Static members come first, so
        this stops reading at the first snapshot."""
        path = self.bundle_path(system, day)
        with (
            path.open("rb") as f,
            zstandard.ZstdDecompressor().stream_reader(f) as reader,
            tarfile.open(fileobj=reader, mode="r|") as tar,
        ):
            for info in tar:
                if not info.name.startswith(f"{STATIC}/"):
                    return
                yield info.name.removeprefix(f"{STATIC}/")

    def _bundle_member(self, system: str, day: dt.date, name: str) -> bytes:
        for member, data in iter_bundle(self.bundle_path(system, day), lambda n: n == name):
            if member == name:
                return data
        raise FileNotFoundError(f"{name} not in {self.bundle_path(system, day)}")

    def load(self, relative: str) -> bytes:
        """Read an archive path as stored in the database (feed_versions.archive_path),
        falling back to that day's bundle once the file itself is gone. Paths
        that lead outside the archive are refused."""
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError(f"{relative!r} is outside the archive")
        if path.exists():
            return self.read(path)
        parts = Path(relative).parts
        if len(parts) == 3 and parts[1] == STATIC and _is_day(parts[2][:10]):
            day = dt.date.fromisoformat(parts[2][:10])
            if self.bundle_path(parts[0], day).exists():
                return self._bundle_member(parts[0], day, f"{STATIC}/{parts[2]}")
        raise FileNotFoundError(path)
