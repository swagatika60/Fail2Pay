"""Database initialisation / migration helper.

Idempotent and additive — safe to run any time:
- creates any missing tables from the ORM models
- adds any missing columns to existing tables
- never drops or alters existing data

Run with:
    python -m app.init_db
"""

import logging

from sqlalchemy import text

import app.models  # noqa: F401  # register all models on Base.metadata
from app.database import Base, engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _existing_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table"
        ),
        {"table": table_name},
    )
    return {row[0] for row in rows}


def _column_definition(column) -> str:
    """SQL type for a column, best-effort (no constraints) so existing rows
    are never blocked by a new NOT NULL / DEFAULT."""
    return column.type.compile(dialect=engine.dialect)


def init_db() -> None:
    if engine is None:
        raise RuntimeError("DATABASE_URL not configured — cannot initialise database")

    with engine.begin() as conn:
        existing_tables = set(engine.dialect.get_table_names(conn))

        # 1) Create missing tables (e.g. webhook_events, scheduled_actions,
        #    emails, promises added after the DB was first created).
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                table.create(conn)
                logger.info("created table %s", table.name)

        # 2) Add missing columns to existing tables (e.g. recovery_cases.metadata).
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue

            existing_columns = _existing_columns(conn, table.name)
            for column in table.columns:
                if column.name not in existing_columns:
                    conn.execute(
                        text(
                            f"ALTER TABLE {table.name} "
                            f"ADD COLUMN {column.name} {_column_definition(column)}"
                        )
                    )
                    logger.info("added column %s.%s", table.name, column.name)

    logger.info("database schema is up to date")


if __name__ == "__main__":
    init_db()
