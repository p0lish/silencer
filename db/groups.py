"""
db/groups.py — CRUD for the groups table.
"""

import time
from db.connection import get_db


async def get_group(chat_id: int) -> dict | None:
    """Return a group row as a dict, or None if not found."""
    db = await get_db()
    async with db.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def upsert_group(chat_id: int, title: str, owner_id: int | None) -> None:
    """Insert or replace a group record."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO groups (chat_id, title, owner_id, added_at) VALUES (?, ?, ?, ?)",
        (chat_id, title, owner_id, int(time.time())),
    )
    await db.commit()


async def delete_group(chat_id: int) -> None:
    """Remove a group and all its admins."""
    db = await get_db()
    await db.execute("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
    await db.execute("DELETE FROM group_admins WHERE chat_id = ?", (chat_id,))
    await db.commit()


async def get_admin_groups(user_id: int) -> list[dict]:
    """Return groups where user_id is in group_admins, including their role."""
    db = await get_db()
    async with db.execute(
        """
        SELECT g.*, ga.role
        FROM groups g
        JOIN group_admins ga ON g.chat_id = ga.chat_id
        WHERE ga.user_id = ?
        ORDER BY g.title
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]
