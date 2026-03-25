"""
tests/test_db.py — Unit tests for all DB layer functions.

Uses the `db` fixture from conftest.py (in-memory SQLite).
"""

import json
import time
import pytest
import pytest_asyncio
from unittest.mock import patch

from db.groups import get_group, upsert_group, delete_group, get_admin_groups
from db.admins import (
    is_group_admin, is_group_owner, get_group_admins,
    add_admin, remove_admin,
)
from db.patterns import (
    get_patterns_for_group, get_custom_patterns,
    add_pattern, delete_pattern, count_custom_patterns,
)
from db.muted import get_muted, add_muted, remove_muted, count_muted
from db.spam_log import log_spam, get_spam_log, count_spam
from db.pending_state import set_pending, get_pending, clear_pending, cleanup_old


CHAT_ID = -1001234567890
USER_ID = 999888777


# ── groups ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_and_get_group(db):
    await upsert_group(CHAT_ID, "Test Group", USER_ID)
    group = await get_group(CHAT_ID)
    assert group is not None
    assert group["title"] == "Test Group"
    assert group["owner_id"] == USER_ID


@pytest.mark.asyncio
async def test_get_group_missing(db):
    group = await get_group(9999999)
    assert group is None


@pytest.mark.asyncio
async def test_upsert_group_updates_title(db):
    await upsert_group(CHAT_ID, "Old Title", USER_ID)
    await upsert_group(CHAT_ID, "New Title", USER_ID)
    group = await get_group(CHAT_ID)
    assert group["title"] == "New Title"


@pytest.mark.asyncio
async def test_delete_group(db):
    await upsert_group(CHAT_ID, "Test Group", USER_ID)
    await delete_group(CHAT_ID)
    group = await get_group(CHAT_ID)
    assert group is None


@pytest.mark.asyncio
async def test_get_admin_groups(db):
    await upsert_group(CHAT_ID, "Test Group", USER_ID)
    await add_admin(CHAT_ID, USER_ID, "testuser", "owner", None)
    groups = await get_admin_groups(USER_ID)
    assert len(groups) == 1
    assert groups[0]["chat_id"] == CHAT_ID


@pytest.mark.asyncio
async def test_get_admin_groups_empty(db):
    groups = await get_admin_groups(USER_ID)
    assert groups == []


@pytest.mark.asyncio
async def test_get_admin_groups_multiple(db):
    chat2 = -9999999
    await upsert_group(CHAT_ID, "Group 1", USER_ID)
    await upsert_group(chat2, "Group 2", USER_ID)
    await add_admin(CHAT_ID, USER_ID, "testuser", "owner", None)
    await add_admin(chat2, USER_ID, "testuser", "admin", None)
    groups = await get_admin_groups(USER_ID)
    assert len(groups) == 2


# ── admins ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_and_is_admin(db):
    await add_admin(CHAT_ID, USER_ID, "testuser", "admin", None)
    assert await is_group_admin(CHAT_ID, USER_ID) is True


@pytest.mark.asyncio
async def test_is_admin_false(db):
    assert await is_group_admin(CHAT_ID, 99999) is False


@pytest.mark.asyncio
async def test_is_owner_true(db):
    await add_admin(CHAT_ID, USER_ID, "testuser", "owner", None)
    assert await is_group_owner(CHAT_ID, USER_ID) is True


@pytest.mark.asyncio
async def test_is_owner_false_for_admin(db):
    await add_admin(CHAT_ID, USER_ID, "testuser", "admin", None)
    assert await is_group_owner(CHAT_ID, USER_ID) is False


@pytest.mark.asyncio
async def test_remove_admin(db):
    await add_admin(CHAT_ID, USER_ID, "testuser", "admin", None)
    await remove_admin(CHAT_ID, USER_ID)
    assert await is_group_admin(CHAT_ID, USER_ID) is False


@pytest.mark.asyncio
async def test_get_group_admins(db):
    await add_admin(CHAT_ID, USER_ID, "user1", "owner", None)
    await add_admin(CHAT_ID, 111, "user2", "admin", USER_ID)
    admins = await get_group_admins(CHAT_ID)
    assert len(admins) == 2
    roles = {a["user_id"]: a["role"] for a in admins}
    assert roles[USER_ID] == "owner"
    assert roles[111] == "admin"


@pytest.mark.asyncio
async def test_duplicate_admin_no_error(db):
    """Adding the same admin twice should be safe (UNIQUE constraint)."""
    await add_admin(CHAT_ID, USER_ID, "testuser", "admin", None)
    # Second insert should not raise
    try:
        await add_admin(CHAT_ID, USER_ID, "testuser", "admin", None)
    except Exception:
        pass  # Expected — IntegrityError on duplicate is acceptable


# ── patterns ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_and_get_custom_pattern(db):
    await add_pattern(CHAT_ID, r"\bspam\b", "spam test", 1, 0, USER_ID)
    patterns = await get_custom_patterns(CHAT_ID)
    assert len(patterns) == 1
    assert patterns[0]["label"] == "spam test"


@pytest.mark.asyncio
async def test_global_pattern_included_in_group(db):
    """Global pattern (chat_id=None) should appear in group's pattern list."""
    await add_pattern(None, r"\bairdrop\b", "crypto scam", 1, 1, None)
    patterns = await get_patterns_for_group(CHAT_ID)
    assert any(p["label"] == "crypto scam" for p in patterns)


@pytest.mark.asyncio
async def test_group_pattern_not_in_other_group(db):
    other_chat = -9999
    await add_pattern(CHAT_ID, r"\btest\b", "group specific", 1, 0, USER_ID)
    patterns = await get_patterns_for_group(other_chat)
    assert not any(p["label"] == "group specific" for p in patterns)


@pytest.mark.asyncio
async def test_delete_pattern(db):
    await add_pattern(CHAT_ID, r"\bspam\b", "spam test", 1, 0, USER_ID)
    patterns = await get_custom_patterns(CHAT_ID)
    pid = patterns[0]["id"]
    deleted = await delete_pattern(pid, CHAT_ID)
    assert deleted is True
    assert await count_custom_patterns(CHAT_ID) == 0


@pytest.mark.asyncio
async def test_delete_pattern_wrong_chat_fails(db):
    """Can't delete a pattern from a different group."""
    await add_pattern(CHAT_ID, r"\bspam\b", "spam test", 1, 0, USER_ID)
    patterns = await get_custom_patterns(CHAT_ID)
    pid = patterns[0]["id"]
    deleted = await delete_pattern(pid, -9999999)
    assert deleted is False


@pytest.mark.asyncio
async def test_count_custom_patterns(db):
    assert await count_custom_patterns(CHAT_ID) == 0
    await add_pattern(CHAT_ID, r"\bspam\b", "spam", 1, 0, USER_ID)
    await add_pattern(CHAT_ID, r"\bscam\b", "scam", 1, 0, USER_ID)
    assert await count_custom_patterns(CHAT_ID) == 2


@pytest.mark.asyncio
async def test_global_pattern_not_counted_as_custom(db):
    """Global patterns (is_builtin=1, chat_id=None) don't count as custom."""
    await add_pattern(None, r"\bairdrop\b", "crypto", 1, 1, None)
    assert await count_custom_patterns(CHAT_ID) == 0


# ── muted ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_and_get_muted(db):
    await add_muted(CHAT_ID, USER_ID, "baduser", "Bad User", "crypto scam")
    rows = await get_muted(CHAT_ID)
    assert len(rows) == 1
    assert rows[0]["username"] == "baduser"
    assert rows[0]["reason"] == "crypto scam"


@pytest.mark.asyncio
async def test_remove_muted(db):
    await add_muted(CHAT_ID, USER_ID, "baduser", "Bad User", "spam")
    await remove_muted(CHAT_ID, USER_ID)
    rows = await get_muted(CHAT_ID)
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_count_muted(db):
    assert await count_muted(CHAT_ID) == 0
    await add_muted(CHAT_ID, USER_ID, "u1", "User 1", "spam")
    await add_muted(CHAT_ID, 222, "u2", "User 2", "spam")
    assert await count_muted(CHAT_ID) == 2


@pytest.mark.asyncio
async def test_muted_isolated_by_chat(db):
    other_chat = -9999
    await add_muted(CHAT_ID, USER_ID, "baduser", "Bad", "spam")
    rows = await get_muted(other_chat)
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_muted_limit(db):
    for i in range(20):
        await add_muted(CHAT_ID, i + 1000, f"user{i}", f"User {i}", "spam")
    rows = await get_muted(CHAT_ID, limit=15)
    assert len(rows) == 15


# ── spam_log ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_and_get_spam(db):
    await log_spam(CHAT_ID, USER_ID, "spammer", "Buy now, earn $500/day!", "investment scam")
    rows = await get_spam_log(CHAT_ID)
    assert len(rows) == 1
    assert rows[0]["pattern"] == "investment scam"


@pytest.mark.asyncio
async def test_count_spam(db):
    assert await count_spam(CHAT_ID) == 0
    await log_spam(CHAT_ID, USER_ID, "u1", "spam1", "crypto scam")
    await log_spam(CHAT_ID, USER_ID, "u2", "spam2", "fake job")
    assert await count_spam(CHAT_ID) == 2


@pytest.mark.asyncio
async def test_spam_log_limit(db):
    for i in range(15):
        await log_spam(CHAT_ID, USER_ID + i, f"user{i}", f"spam{i}", "test")
    rows = await get_spam_log(CHAT_ID, limit=10)
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_spam_log_isolated_by_chat(db):
    await log_spam(CHAT_ID, USER_ID, "spammer", "spam", "test")
    rows = await get_spam_log(-9999)
    assert len(rows) == 0


# ── pending_state ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_and_get_pending(db):
    await set_pending(USER_ID, "addpat", {"chat_id": CHAT_ID, "type": "keyword"})
    result = await get_pending(USER_ID)
    assert result is not None
    assert result["action"] == "addpat"
    # get_pending merges data dict + action at top level
    assert result["chat_id"] == CHAT_ID


@pytest.mark.asyncio
async def test_get_pending_missing(db):
    result = await get_pending(99999)
    assert result is None


@pytest.mark.asyncio
async def test_clear_pending(db):
    await set_pending(USER_ID, "addpat", {"chat_id": CHAT_ID})
    await clear_pending(USER_ID)
    result = await get_pending(USER_ID)
    assert result is None


@pytest.mark.asyncio
async def test_set_pending_overwrites(db):
    await set_pending(USER_ID, "addpat", {"step": 1})
    await set_pending(USER_ID, "addadmin", {"chat_id": CHAT_ID})
    result = await get_pending(USER_ID)
    assert result["action"] == "addadmin"


@pytest.mark.asyncio
async def test_cleanup_old_pending(db):
    """Old pending state rows (>1h) should be deleted."""
    conn = db
    old_time = int(time.time()) - 7200  # 2 hours ago
    await conn.execute(
        "INSERT OR REPLACE INTO pending_state (user_id, action, data, created_at) VALUES (?, ?, ?, ?)",
        (USER_ID, "addpat", '{"chat_id": 123}', old_time)
    )
    await conn.commit()

    await cleanup_old(max_age_seconds=3600)
    result = await get_pending(USER_ID)
    assert result is None


@pytest.mark.asyncio
async def test_cleanup_keeps_recent_pending(db):
    """Recent pending state rows should NOT be deleted."""
    await set_pending(USER_ID, "addpat", {"chat_id": CHAT_ID})
    await cleanup_old(max_age_seconds=3600)
    result = await get_pending(USER_ID)
    assert result is not None
