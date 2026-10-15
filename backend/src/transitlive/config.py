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

    def realtime(self, feed: str, system: System) -> str:
        return self.realtime_url.format(feed=feed, operator=system.operator_id)

    def static(self, system: System) -> str:
        return self.static_url.format(operator=system.operator_id)


@dataclass(frozen=True)
class Config:
    collector: CollectorSettings
    systems: tuple[System, ...]

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
    )
    systems = tuple(
        System(slug=s["slug"], name=s["name"], operator_id=int(s["operator_id"]), timezone=s["timezone"])
        for s in raw["systems"]
    )
    if len({s.slug for s in systems}) != len(systems):
        raise ValueError("system slugs must be unique")
    return Config(collector=collector, systems=systems)
