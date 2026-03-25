"""
db/muted.py — CRUD for the muted table.
"""

import time
from db.connection import get_db


async def get_muted(chat_id: int, limit: int = 15) -> list[dict]:
    """Return the most recently muted users for a group."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM muted WHERE chat_id = ? ORDER BY muted_at DESC LIMIT ?",
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def add_muted(
    chat_id: int,
    user_id: int,
    username: str | None,
    first_name: str | None,
    reason: str,
) -> None:
    """Insert or replace a muted record."""
    db = await get_db()
    await db.execute(
        """
        INSERT OR REPLACE INTO muted
            (chat_id, user_id, username, first_name, reason, muted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chat_id, user_id, username, first_name, reason, int(time.time())),
    )
    await db.commit()


async def remove_muted(chat_id: int, user_id: int) -> None:
    """Remove a user from the muted list."""
    db = await get_db()
    await db.execute(
        "DELETE FROM muted WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    )
    await db.commit()


async def count_muted(chat_id: int) -> int:
    """Count muted users in a group."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM muted WHERE chat_id = ?",
        (chat_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
