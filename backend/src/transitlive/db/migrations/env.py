"""Alembic environment: the database URL comes from TRANSITLIVE_DATABASE_URL."""

from alembic import context
from sqlalchemy import create_engine

from transitlive.db.engine import database_url

config = context.config


def run_migrations_online() -> None:
    url = config.attributes.get("url") or database_url()
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
