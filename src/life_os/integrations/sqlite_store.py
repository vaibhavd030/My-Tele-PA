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
    '''Initialize the SQLite database with required tables.'''
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    finally:
        await db.close()
    log.info('sqlite_db_initialized', path=settings.db_path)

async def get_db() -> aiosqlite.Connection:
    """Get an async connection to the SQLite database."""
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    conn = await aiosqlite.connect(settings.db_path)
    conn.row_factory = aiosqlite.Row
    return conn


async def save_records(user_id: str, records: list[dict[str, Any]]) -> None:
    '''Save structured records into SQLite.'''
    db = await get_db()
    try:
        for record in records:
            # We store records in a simple JSON blob table for flexibility
            await db.execute(
                """
                INSERT INTO records (user_id, date, type, data)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id, 
                    date.today().isoformat(), 
                    record.get("type", "unknown"), 
                    json.dumps(record, default=str)
                )
            )
        await db.commit()
    finally:
        await db.close()
    log.info('saved_records_to_sqlite', count=len(records), user_id=user_id)
