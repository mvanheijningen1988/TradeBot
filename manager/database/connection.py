"""SQLite database connection manager.

Uses aiosqlite for async access.  The schema is auto-created on first
connect when the database file does not yet exist.
"""

import logging
from typing import Optional

import aiosqlite

from manager.database.schema import TABLES

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self.legacy_admin_password_reset_required = False

    async def connect(self) -> None:
        """Open the database and ensure schema exists."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

        await self._create_schema()
        await self._run_migrations()
        logger.info("Database connected: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("Database closed.")

    async def _create_schema(self) -> None:
        """Execute all CREATE TABLE statements."""
        for ddl in TABLES:
            await self._db.execute(ddl)
        await self._db.commit()
        logger.info("Database schema created.")

    async def _run_migrations(self) -> None:
        """Apply lightweight schema migrations for existing databases."""
        await self._ensure_column(
            "users",
            "time_display",
            "TEXT NOT NULL DEFAULT 'local'",
        )
        await self._ensure_column(
            "users",
            "must_change_password",
            "INTEGER NOT NULL DEFAULT 0",
        )
        await self._ensure_column(
            "news_feeds",
            "source_type",
            "TEXT NOT NULL DEFAULT 'rss'",
        )
        await self._ensure_column(
            "news_feeds",
            "weight",
            "REAL NOT NULL DEFAULT 1.0",
        )

    async def _ensure_column(
        self,
        table: str,
        column: str,
        column_def: str,
    ) -> None:
        """Add a column when it does not yet exist."""
        rows = await self.fetch_all(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in rows}
        if column in existing:
            return

        await self._db.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"
        )
        await self._db.commit()
        logger.info("Migration applied: added %s.%s", table, column)
        if table == "users" and column == "must_change_password":
            self.legacy_admin_password_reset_required = True

    async def execute(
        self, sql: str, params: tuple = ()
    ) -> aiosqlite.Cursor:
        """Execute a single parameterized statement."""
        return await self._db.execute(sql, params)

    async def execute_many(
        self, sql: str, params_seq: list[tuple]
    ) -> None:
        """Execute a statement with multiple parameter sets."""
        await self._db.executemany(sql, params_seq)

    async def fetch_one(
        self, sql: str, params: tuple = ()
    ) -> Optional[aiosqlite.Row]:
        """Execute and return a single row."""
        cursor = await self._db.execute(sql, params)
        return await cursor.fetchone()

    async def fetch_all(
        self, sql: str, params: tuple = ()
    ) -> list[aiosqlite.Row]:
        """Execute and return all matching rows."""
        cursor = await self._db.execute(sql, params)
        return await cursor.fetchall()

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._db.commit()
