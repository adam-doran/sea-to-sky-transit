"""Database connection, migrations and monthly partitions."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = Path(__file__).parent / "migrations"
PARTITIONED = ("vehicle_positions", "stop_predictions")

log = logging.getLogger("transitlive.db")


def database_url() -> str:
    return os.environ.get(
        "TRANSITLIVE_DATABASE_URL", "postgresql+psycopg://transitlive:transitlive@localhost:5432/transitlive"
    )


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)


def migrate(url: str | None = None) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["url"] = url or database_url()
    command.upgrade(cfg, "head")


def _month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def _next_month(day: dt.date) -> dt.date:
    return (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def ensure_partitions(engine: Engine, around: dt.date | None = None, months_ahead: int = 2) -> list[str]:
    """Create monthly partitions from last month up to `months_ahead` ahead.
    Safe to call repeatedly; returns the partitions it created."""
    day = _month_start(around or dt.datetime.now(dt.UTC).date())
    start = _month_start(day - dt.timedelta(days=1))
    created = []
    with engine.begin() as conn:
        month = start
        for _ in range(months_ahead + 2):
            nxt = _next_month(month)
            for table in PARTITIONED:
                name = f"{table}_{month:%Y%m}"
                exists = conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar()
                if exists is None:
                    try:
                        with conn.begin_nested():
                            conn.execute(
                                text(
                                    f"CREATE TABLE {name} PARTITION OF {table} FOR VALUES "
                                    f"FROM ('{month.isoformat()} 00:00+00') TO ('{nxt.isoformat()} 00:00+00')"
                                )
                            )
                        created.append(name)
                    except IntegrityError:
                        # The DEFAULT partition already holds rows for this month
                        log.warning("can't create %s: %s_default has rows for that month", name, table)
            month = nxt
    return created


def drop_old_partitions(
    engine: Engine, today: dt.date, keep_days: int, bundled: Callable[[dt.date], bool]
) -> list[str]:
    """Drop monthly history partitions whose whole month is more than
    `keep_days` old, if every day of the month has bundles (`bundled(day)`) to
    rebuild it from, or the partition is empty. The DEFAULT partitions and
    every other table are never touched. Returns the partitions dropped."""
    cutoff = today - dt.timedelta(days=keep_days)
    dropped = []
    for table in PARTITIONED:
        with engine.connect() as conn:
            names: list[str] = list(
                conn.execute(
                    text(
                        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                        "WHERE i.inhparent = to_regclass(:t) ORDER BY c.relname"
                    ),
                    {"t": table},
                ).scalars()
            )
        for name in names:
            match = re.fullmatch(rf"{table}_(\d{{4}})(\d{{2}})", name)
            if match is None:
                continue  # the DEFAULT partition, or something we didn't create
            month = dt.date(int(match[1]), int(match[2]), 1)
            end = _next_month(month)
            if end > cutoff:
                continue
            with engine.connect() as conn:
                rows = conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()
            missing = [d for d in (month + dt.timedelta(days=i) for i in range((end - month).days)) if not bundled(d)]
            if missing and rows:
                log.warning("keeping %s: %d days have no bundles, e.g. %s", name, len(missing), missing[0])
                continue
            # Its own short transaction: DROP locks the parent table
            with engine.begin() as conn:
                conn.execute(text(f"DROP TABLE {name}"))
            log.info("dropped %s (%d rows; transitlive replay rebuilds it from the bundles)", name, rows)
            dropped.append(name)
    return dropped
