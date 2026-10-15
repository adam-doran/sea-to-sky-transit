"""Load config/systems.toml: which transit systems to collect and how politely."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "systems.toml"
REALTIME_FEEDS = ("vehicleupdates", "tripupdates", "alerts")


@dataclass(frozen=True)
class System:
    slug: str
    name: str
    operator_id: int
    timezone: str


@dataclass(frozen=True)
class CollectorSettings:
    user_agent: str
    realtime_url: str
    static_url: str
    timeout_seconds: float = 10
    static_sync_hours: float = 6
    intervals: dict[str, float] = field(default_factory=dict)
    # stop_predictions stores a new row when a predicted time moves this much
    prediction_threshold_seconds: float = 30

    def realtime(self, feed: str, system: System) -> str:
        return self.realtime_url.format(feed=feed, operator=system.operator_id)

    def static(self, system: System) -> str:
        return self.static_url.format(operator=system.operator_id)


@dataclass(frozen=True)
class ArchiveSettings:
    """Daily bundles, where they go, and how long the raw files and history stay."""

    keep_snapshot_days: int = 3  # individual snapshot files, once bundled (and uploaded)
    database_days: int = 90  # monthly history partitions, once bundled; 0 keeps them forever
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_region: str | None = None

    def __post_init__(self) -> None:
        if self.keep_snapshot_days < 1:
            raise ValueError("archive.keep_snapshot_days must be at least 1")
        # Below about a month, last month's partition would be dropped and
        # recreated by ensure_partitions over and over.
        if self.database_days and self.database_days < 35:
            raise ValueError("archive.database_days must be 0 (keep forever) or at least 35")


@dataclass(frozen=True)
class Config:
    collector: CollectorSettings
    systems: tuple[System, ...]
    archive: ArchiveSettings = field(default_factory=ArchiveSettings)

    def system(self, slug: str) -> System:
        for s in self.systems:
            if s.slug == slug:
                return s
        raise KeyError(slug)


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("TRANSITLIVE_CONFIG") or DEFAULT_CONFIG)
    raw = tomllib.loads(path.read_text())
    c = raw["collector"]
    intervals = {feed: float(c.get("intervals", {}).get(feed, 30)) for feed in REALTIME_FEEDS}
    collector = CollectorSettings(
        user_agent=c["user_agent"],
        realtime_url=c["realtime_url"],
        static_url=c["static_url"],
        timeout_seconds=float(c.get("timeout_seconds", 10)),
        static_sync_hours=float(c.get("static_sync_hours", 6)),
        intervals=intervals,
        prediction_threshold_seconds=float(c.get("prediction_threshold_seconds", 30)),
    )
    a = raw.get("archive", {})
    # The S3 settings can come from the environment too, so a deployment can
    # set them in deploy/.env without editing this file.
    bucket = os.environ.get("TRANSITLIVE_S3_BUCKET") or a.get("s3_bucket") or None
    archive = ArchiveSettings(
        keep_snapshot_days=int(a.get("keep_snapshot_days", 3)),
        database_days=int(a.get("database_days", 90)),
        s3_bucket=bucket,
        s3_prefix=os.environ.get("TRANSITLIVE_S3_PREFIX") or a.get("s3_prefix", ""),
        s3_region=os.environ.get("TRANSITLIVE_S3_REGION") or a.get("s3_region") or None,
    )
    systems = tuple(
        System(slug=s["slug"], name=s["name"], operator_id=int(s["operator_id"]), timezone=s["timezone"])
        for s in raw["systems"]
    )
    if len({s.slug for s in systems}) != len(systems):
        raise ValueError("system slugs must be unique")
    return Config(collector=collector, systems=systems, archive=archive)
