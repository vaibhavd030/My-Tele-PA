"""SQLite persistence layer for Life OS.

Provides async access to the primary SQLite database.
Stores wellness logs, user streaks, and raw journal entries.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import aiosqlite
import structlog

from life_os.config.settings import settings

log = structlog.get_logger(__name__)


async def init_db() -> None:
    """Initialize the SQLite database with required tables."""
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    # Schema creation is now handled natively via Alembic migrations.
    # Retrieve connection to ensure DB file is created/accessible.
    db = await get_db()
    log.info("sqlite_db_initialized", path=settings.db_path)


_connection: aiosqlite.Connection | None = None

async def get_db() -> aiosqlite.Connection:
    """Get an async connection to the SQLite database."""
    global _connection
    if _connection is None:
        os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
        _connection = await aiosqlite.connect(settings.db_path)
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA busy_timeout=5000")
    return _connection


async def save_records(user_id: str, records: list[dict[str, Any]]) -> None:
    """Save structured records into SQLite."""
    db = await get_db()
    for record in records:
        date_str = record.get("date", date.today().isoformat())
        if isinstance(date_str, date):
            date_str = date_str.isoformat()
        
        # We store records in a simple JSON blob table for flexibility
        await db.execute(
            """
            INSERT INTO records (user_id, date, type, data)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                date_str,
                record.get("type", "unknown"),
                json.dumps(record, default=str),
            ),
        )
    await db.commit()
    log.info("saved_records_to_sqlite", count=len(records), user_id=user_id)
