"""
db/admins.py — CRUD for the group_admins table.
"""

import time
from db.connection import get_db


async def is_group_admin(chat_id: int, user_id: int) -> bool:
    """Return True if user_id is an admin (any role) of chat_id."""
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM group_admins WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return row is not None


async def is_group_owner(chat_id: int, user_id: int) -> bool:
    """Return True if user_id is the owner of chat_id."""
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM group_admins WHERE chat_id = ? AND user_id = ? AND role = 'owner'",
        (chat_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return row is not None


async def get_group_admins(chat_id: int) -> list[dict]:
    """Return all admins for a group, owners first."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM group_admins WHERE chat_id = ? ORDER BY role DESC, added_at",
        (chat_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def add_admin(
    chat_id: int,
    user_id: int,
    username: str | None,
    role: str = "admin",
    added_by: int | None = None,
) -> None:
    """Insert a new admin (ignores duplicates)."""
    db = await get_db()
    await db.execute(
        """
        INSERT OR IGNORE INTO group_admins
            (chat_id, user_id, username, role, added_by, added_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chat_id, user_id, username, role, added_by, int(time.time())),
    )
    await db.commit()


async def remove_admin(chat_id: int, user_id: int) -> None:
    """Remove an admin from a group."""
    db = await get_db()
    await db.execute(
        "DELETE FROM group_admins WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    )
    await db.commit()
