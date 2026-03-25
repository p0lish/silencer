"""
db/connection.py — Global aiosqlite connection singleton.

Usage:
    from db.connection import get_db, close_db

    db = await get_db()
    async with db.execute("SELECT ...") as cur:
        ...
"""

import aiosqlite
from config import DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """Return the shared aiosqlite connection, opening it on first call."""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrent read performance
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db() -> None:
    """Close the shared connection (call on shutdown)."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
