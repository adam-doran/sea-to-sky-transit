"""A throwaway PostgreSQL for integration tests (needs Docker).

Run with: uv run pytest -m integration   (or: make test-integration)
Set TRANSITLIVE_TEST_DATABASE_URL to use an existing empty database instead.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from transitlive.db.engine import ensure_partitions, make_engine, migrate


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("TRANSITLIVE_TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    """A freshly migrated, empty schema for each test."""
    engine = make_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    migrate(database_url)
    ensure_partitions(engine)
    yield engine
    engine.dispose()
