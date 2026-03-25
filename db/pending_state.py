"""
db/pending_state.py — Transient per-user state for multi-step DM flows.

State is stored in SQLite so it survives hot-reloads, but cleaned up
after max_age_seconds (default 1 hour) to prevent stale prompts.
"""

import json
import time
from db.connection import get_db


async def set_pending(user_id: int, action: str, data: dict) -> None:
    """Upsert a pending state record for a user."""
    db = await get_db()
    await db.execute(
        """
        INSERT OR REPLACE INTO pending_state (user_id, action, data, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, action, json.dumps(data), int(time.time())),
    )
    await db.commit()


async def get_pending(user_id: int) -> dict | None:
    """
    Return the pending state dict for a user, or None if absent.
    The returned dict includes 'action' and all fields from 'data'.
    """
    db = await get_db()
    async with db.execute(
        "SELECT action, data FROM pending_state WHERE user_id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return None

    result = json.loads(row["data"])
    result["action"] = row["action"]
    return result


async def clear_pending(user_id: int) -> None:
    """Remove the pending state for a user."""
    db = await get_db()
    await db.execute("DELETE FROM pending_state WHERE user_id = ?", (user_id,))
    await db.commit()


async def cleanup_old(max_age_seconds: int = 3600) -> int:
    """Delete pending_state rows older than max_age_seconds. Returns count removed."""
    db = await get_db()
    cutoff = int(time.time()) - max_age_seconds
    async with db.execute(
        "DELETE FROM pending_state WHERE created_at < ?", (cutoff,)
    ) as cur:
        removed = cur.rowcount
    await db.commit()
    return removed
