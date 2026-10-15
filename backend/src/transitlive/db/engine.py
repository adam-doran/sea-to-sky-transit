"""Database connection, migrations and monthly partitions."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, text

MIGRATIONS = Path(__file__).parent / "migrations"
PARTITIONED = ("vehicle_positions", "stop_predictions")


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
                    conn.execute(
                        text(
                            f"CREATE TABLE {name} PARTITION OF {table} "
                            f"FOR VALUES FROM ('{month.isoformat()} 00:00+00') TO ('{nxt.isoformat()} 00:00+00')"
                        )
                    )
                    created.append(name)
            month = nxt
    return created
