"""
db/migrations.py — All CREATE TABLE IF NOT EXISTS and ALTER TABLE migrations.

Run `await run_migrations()` once at startup.
"""

import logging
from db.connection import get_db

logger = logging.getLogger(__name__)

# Full schema — all tables
SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    chat_id   INTEGER PRIMARY KEY,
    title     TEXT,
    owner_id  INTEGER,
    added_at  INTEGER
);

CREATE TABLE IF NOT EXISTS group_admins (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    username  TEXT,
    role      TEXT DEFAULT 'admin',
    added_by  INTEGER,
    added_at  INTEGER,
    UNIQUE(chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS muted (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    first_name TEXT,
    reason     TEXT,
    muted_at   INTEGER NOT NULL,
    UNIQUE(chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS spam_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER,
    user_id   INTEGER,
    username  TEXT,
    message   TEXT,
    pattern   TEXT,
    logged_at INTEGER
);

CREATE TABLE IF NOT EXISTS custom_patterns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER,
    pattern    TEXT NOT NULL,
    label      TEXT NOT NULL,
    is_regex   INTEGER DEFAULT 0,
    is_builtin INTEGER DEFAULT 0,
    added_by   INTEGER,
    added_at   INTEGER,
    UNIQUE(chat_id, pattern)
);

CREATE TABLE IF NOT EXISTS pending_state (
    user_id    INTEGER PRIMARY KEY,
    action     TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""

# columns that may be missing from older DBs: (table, column, definition)
_MIGRATIONS = [
    ("groups",          "owner_id",   "INTEGER"),
    ("custom_patterns", "is_builtin", "INTEGER DEFAULT 0"),
    ("custom_patterns", "chat_id",    "INTEGER"),  # make nullable if old schema had NOT NULL
]


async def _get_columns(table: str) -> set[str]:
    """Return the set of column names in a table."""
    db = await get_db()
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return {row["name"] for row in rows}


async def run_migrations() -> None:
    """Create tables, add missing columns, clean up stale pending_state rows."""
    db = await get_db()

    # Create all tables
    await db.executescript(SCHEMA)
    await db.commit()
    logger.info("Schema applied.")

    # Add missing columns (ALTER TABLE is idempotent via the check below)
    for table, column, definition in _MIGRATIONS:
        cols = await _get_columns(table)
        if column not in cols:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                await db.commit()
                logger.info(f"Migration: added column {table}.{column}")
            except Exception as e:
                logger.warning(f"Migration skipped ({table}.{column}): {e}")

    # Clean up stale pending_state rows older than 1 hour
    import time
    cutoff = int(time.time()) - 3600
    await db.execute("DELETE FROM pending_state WHERE created_at < ?", (cutoff,))
    await db.commit()
    logger.info("Cleaned up stale pending_state rows.")
