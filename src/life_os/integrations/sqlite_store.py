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
    # Schema creation is natively handled via Alembic, but we add a fallback
    # creation here to ensure that unit test fixtures utilizing tmp_path SQLite databases
    # can initialize properly without running an Alembic context.
    db = await get_db()
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            data JSON NOT NULL,
            source TEXT DEFAULT 'manual'
        )
        """
    )
    await db.commit()
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
        source_val = record.get("source", "manual")
        await db.execute(
            """
            INSERT INTO records (user_id, date, type, data, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                date_str,
                record.get("type", "unknown"),
                json.dumps(record, default=str),
                source_val,
            ),
        )
    await db.commit()
    log.info("saved_records_to_sqlite", count=len(records), user_id=user_id)

async def save_if_not_duplicate(user_id: str, record: dict[str, Any]) -> bool:
    """Check if an Apple Health sleep entry for the same day already exists."""
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT id FROM records 
        WHERE user_id=? AND date=? AND type=? AND source='apple_health'
        """,
        (user_id, record["date"], "sleep"),
    )
    if await cursor.fetchone():
        return False  # already have this day
    await save_records(user_id, [record])
    return True
