"""Daily bundles: long-term storage for the raw archive.

Each night the collector packs the previous UTC day of each system into one
`bundles/{system}/{YYYY-MM-DD}.tar.zst` (layout in collector/archive.py),
verifies it, uploads it to S3 if a bucket is configured, and deletes
individual snapshot files once their day has a verified (and uploaded) bundle
and is a few days old. A NAS can pull the bundles directory with rsync.

Everything here is safe to re-run: a bundle that already holds every file of
its day is left alone, and one that's missing files is rebuilt with them,
keeping members whose files are already gone.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import heapq
import io
import logging
import os
import tarfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import zstandard

from transitlive.collector.archive import STATIC, Archive, MemberKey, iter_bundle, member_key
from transitlive.config import REALTIME_FEEDS, ArchiveSettings

log = logging.getLogger("transitlive.bundles")

BUNDLE_LEVEL = 19


class BundleError(Exception):
    """A bundle didn't match the files it was made from."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def previous_utc_day(now: float) -> dt.date:
    return dt.datetime.fromtimestamp(now, dt.UTC).date() - dt.timedelta(days=1)


def day_sources(archive: Archive, system: str, day: dt.date) -> dict[str, Path]:
    """The individual files of one day, by bundle member name."""
    sources: dict[str, Path] = {}
    for zip_path in archive.iter_static(system):
        if zip_path.name.startswith(day.isoformat()):
            sources[f"{STATIC}/{zip_path.name}"] = zip_path
    for feed in REALTIME_FEEDS:
        for ts, path in archive.day_files(system, feed, day):
            sources[f"{feed}/{ts}.pb"] = path
    return sources


def bundle_hashes(path: Path) -> dict[str, str]:
    """sha256 of every member of a bundle, by name."""
    return {name: sha256(data) for name, data in iter_bundle(path)}


def verify(path: Path, expected: dict[str, str]) -> None:
    """Decompress a bundle and check it holds exactly the expected members."""
    found = bundle_hashes(path)
    if len(found) != len(expected):
        raise BundleError(f"{path}: {len(found)} members, expected {len(expected)}")
    wrong = sorted(name for name, digest in expected.items() if found.get(name) != digest)
    if wrong:
        raise BundleError(f"{path}: {len(wrong)} members don't match their files, e.g. {wrong[0]}")


def _write(path: Path, members: Iterator[tuple[str, bytes]]) -> dict[str, str]:
    """Write a bundle (not atomically); returns the sha256 of each member."""
    written: dict[str, str] = {}
    params = zstandard.ZstdCompressor(level=BUNDLE_LEVEL, write_checksum=True)
    with (
        path.open("wb") as f,
        params.stream_writer(f, closefd=False) as zf,
        tarfile.open(fileobj=zf, mode="w|", format=tarfile.PAX_FORMAT) as tar,
    ):
        for name, data in members:
            if name in written:
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            group, _, leaf = name.partition("/")
            info.mtime = int(leaf.split(".")[0]) if group != STATIC else 0
            tar.addfile(info, io.BytesIO(data))
            written[name] = sha256(data)
    return written


@dataclass(frozen=True)
class Bundled:
    system: str
    day: dt.date
    path: Path
    members: int
    size: int
    created: bool  # False when an existing bundle already held every file


def bundle_day(archive: Archive, system: str, day: dt.date) -> Bundled | None:
    """Pack one system's day into its bundle, verify it, and put it in place.
    Returns None when there's nothing archived for that day."""
    sources = day_sources(archive, system, day)
    path = archive.bundle_path(system, day)
    existing = bundle_hashes(path) if path.exists() else {}
    if not sources and not existing:
        return None
    source_hashes = {name: sha256(archive.read(p)) for name, p in sources.items()}
    if path.exists() and all(existing.get(n) == h for n, h in source_hashes.items()):
        return Bundled(system, day, path, len(existing), path.stat().st_size, created=False)

    # Members already bundled whose files have since been deleted are kept
    keep = set(existing) - set(sources)
    from_files: Iterator[tuple[MemberKey, str, Path | bytes]] = (
        (member_key(n), n, p) for n, p in sorted(sources.items(), key=lambda x: member_key(x[0]))
    )
    from_bundle: Iterator[tuple[MemberKey, str, Path | bytes]] = (
        (member_key(n), n, data) for n, data in (iter_bundle(path, lambda n: n in keep) if keep else iter(()))
    )

    def members() -> Iterator[tuple[str, bytes]]:
        for _, name, item in heapq.merge(from_files, from_bundle, key=lambda x: x[0]):
            yield name, item if isinstance(item, bytes) else archive.read(item)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        written = _write(tmp, members())
        expected = {n: existing[n] for n in keep} | source_hashes
        if written != expected:
            raise BundleError(f"{tmp}: files changed while bundling")
        verify(tmp, expected)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    size = path.stat().st_size
    log.info("%s %s: bundled %d files into %s (%.0f KB)", system, day, len(written), path.name, size / 1024)
    return Bundled(system, day, path, len(written), size, created=True)


# ---- S3 ----


class S3Store:
    """Uploads bundles to s3://{bucket}/{prefix}{system}/{YYYY-MM-DD}.tar.zst.
    Credentials come from the environment (on EC2, the instance's IAM role)."""

    def __init__(self, bucket: str, prefix: str = "", region: str | None = None, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        self.client = client
        self.bucket = bucket
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"

    @classmethod
    def from_settings(cls, settings: ArchiveSettings) -> S3Store | None:
        if not settings.s3_bucket:
            return None
        return cls(settings.s3_bucket, settings.s3_prefix, settings.s3_region)

    def key(self, system: str, day: dt.date) -> str:
        return f"{self.prefix}{system}/{day.isoformat()}.tar.zst"

    def has(self, path: Path, system: str, day: dt.date, digest: str | None = None) -> bool:
        """Is this bundle in S3 already, with the same size and sha256?"""
        from botocore.exceptions import ClientError

        try:
            head = self.client.head_object(Bucket=self.bucket, Key=self.key(system, day))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        digest = digest or file_sha256(path)
        return bool(head["ContentLength"] == path.stat().st_size and head.get("Metadata", {}).get("sha256") == digest)

    def upload(self, path: Path, system: str, day: dt.date) -> bool:
        """Upload a bundle unless S3 already has it. True when uploaded."""
        digest = file_sha256(path)
        if self.has(path, system, day, digest):
            return False
        with path.open("rb") as body:
            self.client.put_object(
                Bucket=self.bucket,
                Key=self.key(system, day),
                Body=body,
                ContentType="application/zstd",
                Metadata={"sha256": digest},
                ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),  # S3 checks it on arrival
            )
        log.info("%s %s: uploaded to s3://%s/%s", system, day, self.bucket, self.key(system, day))
        return True


# ---- local retention ----


def prune_day(archive: Archive, system: str, day: dt.date, s3: S3Store | None) -> int:
    """Delete one day's snapshot files, but only if its bundle holds every one
    of them, byte for byte (and S3 has the bundle, when configured). Timetable
    zips stay: they're small, and restarts read them."""
    files = [(f"{feed}/{ts}.pb", p) for feed in REALTIME_FEEDS for ts, p in archive.day_files(system, feed, day)]
    if not files:
        return 0
    bundle = archive.bundle_path(system, day)
    if not bundle.exists():
        log.warning("%s %s: keeping %d files: no bundle", system, day, len(files))
        return 0
    hashes = bundle_hashes(bundle)
    missing = [name for name, p in files if hashes.get(name) != sha256(archive.read(p))]
    if missing:
        log.warning("%s %s: keeping files: %d aren't in the bundle (e.g. %s)", system, day, len(missing), missing[0])
        return 0
    if s3 is not None and not s3.has(bundle, system, day):
        log.warning("%s %s: keeping files: the bundle isn't in S3 yet", system, day)
        return 0
    for _, p in files:
        p.unlink()
    for feed in REALTIME_FEEDS:
        folder = archive.root / system / feed / day.isoformat()
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
    log.info("%s %s: deleted %d snapshot files (bundled)", system, day, len(files))
    return len(files)


# ---- the nightly run ----


@dataclass
class Summary:
    bundled: list[Bundled] = field(default_factory=list)
    uploaded: int = 0
    deleted_files: int = 0
    errors: int = 0


def pending_days(archive: Archive, system: str, before: dt.date) -> list[dt.date]:
    """Days before `before` that still have snapshot files, or a timetable zip
    but no bundle yet. (Timetable zips are never deleted, so they alone
    don't keep a bundled day pending.)"""
    days = {d for feed in REALTIME_FEEDS for d in archive.file_days(system, feed)}
    bundled = set(archive.bundle_days(system))
    days |= {d for p in archive.iter_static(system) if (d := dt.date.fromisoformat(p.name[:10])) not in bundled}
    return sorted(d for d in days if d < before)


def maintain(
    archive: Archive, systems: Sequence[str], settings: ArchiveSettings, today: dt.date, s3: S3Store | None
) -> Summary:
    """Bundle every finished day that still has files, upload the bundles,
    then delete files older than settings.keep_snapshot_days."""
    summary = Summary()
    cutoff = today - dt.timedelta(days=settings.keep_snapshot_days)
    for system in systems:
        for day in pending_days(archive, system, today):
            try:
                result = bundle_day(archive, system, day)
                if result is None:
                    continue
                if result.created:
                    summary.bundled.append(result)
                if s3 is not None and s3.upload(result.path, system, day):
                    summary.uploaded += 1
                if day < cutoff:
                    summary.deleted_files += prune_day(archive, system, day, s3)
            except Exception:
                summary.errors += 1
                log.exception("%s %s: bundling failed; its files are kept", system, day)
    return summary
