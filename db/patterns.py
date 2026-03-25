"""
db/patterns.py — CRUD for the custom_patterns table.
"""

import time
from db.connection import get_db


async def get_patterns_for_group(chat_id: int) -> list[dict]:
    """
    Return all patterns that apply to a group:
    - Global built-in patterns (chat_id IS NULL)
    - Group-specific custom patterns (chat_id = chat_id)
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT * FROM custom_patterns
        WHERE chat_id IS NULL OR chat_id = ?
        ORDER BY is_builtin DESC, added_at
        """,
        (chat_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def get_custom_patterns(chat_id: int) -> list[dict]:
    """Return only the group-specific (non-builtin) patterns for a group."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM custom_patterns WHERE chat_id = ? ORDER BY added_at DESC",
        (chat_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def add_pattern(
    chat_id: int | None,
    pattern: str,
    label: str,
    is_regex: int,
    is_builtin: int,
    added_by: int | None,
) -> None:
    """
    Insert a pattern. Raises aiosqlite.IntegrityError on duplicate.
    Use None for chat_id to create a global (built-in) pattern.
    """
    db = await get_db()
    await db.execute(
        """
        INSERT INTO custom_patterns
            (chat_id, pattern, label, is_regex, is_builtin, added_by, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (chat_id, pattern, label, is_regex, is_builtin, added_by, int(time.time())),
    )
    await db.commit()


async def delete_pattern(pattern_id: int, chat_id: int) -> bool:
    """
    Delete a custom pattern by id, scoped to chat_id for safety.
    Returns True if a row was deleted.
    """
    db = await get_db()
    async with db.execute(
        "DELETE FROM custom_patterns WHERE id = ? AND chat_id = ?",
        (pattern_id, chat_id),
    ) as cur:
        deleted = cur.rowcount > 0
    await db.commit()
    return deleted


async def count_custom_patterns(chat_id: int) -> int:
    """Count the group-specific (non-builtin) patterns for a group."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM custom_patterns WHERE chat_id = ?",
        (chat_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
