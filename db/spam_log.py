"""
db/spam_log.py — Write/read the spam_log table.
"""

import time
from db.connection import get_db


async def log_spam(
    chat_id: int,
    user_id: int,
    username: str | None,
    message: str,
    pattern: str,
) -> None:
    """Append a spam detection event to the log."""
    db = await get_db()
    await db.execute(
        """
        INSERT INTO spam_log (chat_id, user_id, username, message, pattern, logged_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chat_id, user_id, username, message[:500], pattern, int(time.time())),
    )
    await db.commit()


async def get_spam_log(chat_id: int, limit: int = 10) -> list[dict]:
    """Return the most recent spam log entries for a group."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM spam_log WHERE chat_id = ? ORDER BY logged_at DESC LIMIT ?",
        (chat_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def count_spam(chat_id: int) -> int:
    """Count total spam events logged for a group."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM spam_log WHERE chat_id = ?",
        (chat_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
