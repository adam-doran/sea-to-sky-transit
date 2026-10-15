"""Long-term storage against PostgreSQL: rebuilding history from daily bundles
alone, and dropping old history partitions only when bundles cover them."""

from __future__ import annotations

import datetime as dt
import logging
import shutil
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, insert, select, text

from transitlive.collector.archive import Archive
from transitlive.collector.bundles import bundle_day
from transitlive.collector.replay import Replayer
from transitlive.collector.service import Collector
from transitlive.config import load_config
from transitlive.db import schema as s
from transitlive.db import store
from transitlive.db.engine import drop_old_partitions, ensure_partitions, migrate

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "archive"
CONFIG = load_config()
DAY = dt.date(2026, 10, 15)


def count(engine: Engine, table: s.Table) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def partitions(engine: Engine, table: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                "WHERE i.inhparent = to_regclass(:t) ORDER BY 1"
            ),
            {"t": table},
        )
        return list(rows.scalars())


async def test_history_rebuilds_from_bundles_alone(engine: Engine, database_url: str, tmp_path: Path) -> None:
    await Replayer(CONFIG, engine, FIXTURES).run(speed=0)
    from_files = (count(engine, s.vehicle_positions), count(engine, s.stop_predictions), count(engine, s.alerts))

    shutil.copytree(FIXTURES, tmp_path / "archive")
    archive = Archive(tmp_path / "archive")
    for system in CONFIG.systems:
        assert bundle_day(archive, system.slug, DAY) is not None
    restored = tmp_path / "restored"
    shutil.copytree(archive.root / "bundles", restored / "bundles")
    assert not list(restored.glob("*/vehicleupdates"))

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    migrate(database_url)
    ensure_partitions(engine)
    await Replayer(CONFIG, engine, restored).run(speed=0)

    assert (
        count(engine, s.vehicle_positions),
        count(engine, s.stop_predictions),
        count(engine, s.alerts),
    ) == from_files
    with engine.connect() as conn:
        active = conn.execute(select(s.feed_versions.c.system_id).where(s.feed_versions.c.active)).scalars().all()
    assert sorted(active) == [43, 44, 50]  # timetables came out of the bundles too
    assert count(engine, s.live_documents) == 9


def add_rows(engine: Engine, *days: dt.date) -> None:
    with engine.begin() as conn:
        for i, day in enumerate(days):
            at = dt.datetime.combine(day, dt.time(12), dt.UTC)
            conn.execute(
                insert(s.vehicle_positions).values(
                    system_id=43, vehicle_id=f"v{i}", observed_at=at, feed_at=at, lat=49.7, lon=-123.1
                )
            )
            conn.execute(
                insert(s.stop_predictions).values(
                    system_id=43, trip_id=f"t{i}", start_date="", stop_key="1", observed_at=at
                )
            )


def test_old_months_are_dropped_only_when_bundled(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    store.sync_systems(engine, CONFIG.systems)
    ensure_partitions(engine, dt.date(2026, 5, 15), months_ahead=1)  # April, May, June
    add_rows(engine, dt.date(2026, 4, 3), dt.date(2026, 5, 3), dt.date(1990, 1, 1))  # 1990: DEFAULT partition
    store.record_fetch(engine, 43, "vehicleupdates", 1_775_000_000, "u", 200, 1, "x", None, 5, True, None)

    def bundled(day: dt.date) -> bool:
        return day.month == 4 or (day.month == 5 and day.day != 20)  # May 20th has no bundle

    caplog.set_level(logging.INFO, "transitlive.db")
    # On 2026-08-15, with 90 days kept, months ending on or before May 17th can go
    dropped = drop_old_partitions(engine, dt.date(2026, 8, 15), 90, bundled)
    assert dropped == ["vehicle_positions_202604", "stop_predictions_202604"]
    assert "dropped vehicle_positions_202604 (1 rows" in caplog.text

    # Later: May is old enough but May 20th still has no bundle; June is empty
    dropped = drop_old_partitions(engine, dt.date(2026, 10, 14), 90, bundled)
    assert dropped == ["vehicle_positions_202606", "stop_predictions_202606"]
    assert "keeping vehicle_positions_202605: 1 days have no bundles, e.g. 2026-05-20" in caplog.text
    for table in ("vehicle_positions", "stop_predictions"):
        names = partitions(engine, table)
        assert f"{table}_default" in names and f"{table}_202605" in names
        assert f"{table}_202604" not in names
    assert count(engine, s.vehicle_positions) == 2  # May's row and the DEFAULT partition's
    assert count(engine, s.feed_fetches) == 1


def test_partitions_are_not_created_over_rows_in_the_default(engine: Engine) -> None:
    add_rows(engine, dt.date(2026, 2, 10))  # no February partition: lands in DEFAULT
    created = ensure_partitions(engine, dt.date(2026, 3, 10), months_ahead=0)
    assert created == ["vehicle_positions_202603", "stop_predictions_202603"]
    assert count(engine, s.vehicle_positions) == 1


async def test_the_collector_drops_bundled_months(engine: Engine, tmp_path: Path) -> None:
    ensure_partitions(engine, dt.date(2026, 5, 15), months_ahead=0)  # April and May
    add_rows(engine, dt.date(2026, 4, 3), dt.date(2026, 5, 3))
    archive = Archive(tmp_path)
    for day in (dt.date(2026, 4, 1) + dt.timedelta(days=i) for i in range(30)):
        for system in CONFIG.systems:
            path = archive.bundle_path(system.slug, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")  # existence is what counts here
    now = dt.datetime(2026, 8, 20, 0, 10, tzinfo=dt.UTC).timestamp()
    collector = Collector(CONFIG, engine, archive, None, clock=lambda: now)  # type: ignore[arg-type]
    await collector.maintain()
    assert "vehicle_positions_202604" not in partitions(engine, "vehicle_positions")
    assert "vehicle_positions_202605" in partitions(engine, "vehicle_positions")  # not bundled
    assert "vehicle_positions_202609" in partitions(engine, "vehicle_positions")  # created ahead
    assert collector.archive_maintained == dt.date(2026, 8, 20)
