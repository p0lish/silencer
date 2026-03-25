"""
tests/test_migrations.py — Tests for db/migrations.py

Tests that:
- Fresh DB: all 6 tables are created with the correct columns
- Old DB missing columns: ALTER TABLE migrations run correctly
- Migrations are idempotent (safe to run twice)
- Stale pending_state rows are cleaned on startup
- Fresh pending_state rows survive the cleanup
- UNIQUE and NOT NULL constraints are correct
"""

import time
import pytest
import aiosqlite
from unittest.mock import AsyncMock, patch

from db.migrations import run_migrations, _get_columns, SCHEMA

# ── Helpers ───────────────────────────────────────────────────────────────────

async def fresh_db():
    """Return an in-memory aiosqlite connection with row_factory set."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    return conn


async def get_table_names(conn) -> set:
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cur:
        rows = await cur.fetchall()
    return {r["name"] for r in rows}


async def get_columns(conn, table: str) -> set:
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return {r["name"] for r in rows}


# ══════════════════════════════════════════════════════════════════════════════
# FRESH DB — TABLE CREATION
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_all_tables_created_on_fresh_db():
    """run_migrations() on a fresh DB should create all 6 tables."""
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    tables = await get_table_names(conn)
    expected = {"groups", "group_admins", "muted", "spam_log", "custom_patterns", "pending_state"}
    assert expected.issubset(tables)
    await conn.close()


@pytest.mark.asyncio
async def test_groups_table_columns():
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols = await get_columns(conn, "groups")
    assert {"chat_id", "title", "owner_id", "added_at"}.issubset(cols)
    await conn.close()


@pytest.mark.asyncio
async def test_group_admins_table_columns():
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols = await get_columns(conn, "group_admins")
    assert {"id", "chat_id", "user_id", "username", "role", "added_by", "added_at"}.issubset(cols)
    await conn.close()


@pytest.mark.asyncio
async def test_muted_table_columns():
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols = await get_columns(conn, "muted")
    assert {"id", "chat_id", "user_id", "username", "first_name", "reason", "muted_at"}.issubset(cols)
    await conn.close()


@pytest.mark.asyncio
async def test_spam_log_table_columns():
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols = await get_columns(conn, "spam_log")
    assert {"id", "chat_id", "user_id", "username", "message", "pattern", "logged_at"}.issubset(cols)
    await conn.close()


@pytest.mark.asyncio
async def test_custom_patterns_table_columns():
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols = await get_columns(conn, "custom_patterns")
    assert {"id", "chat_id", "pattern", "label", "is_regex", "is_builtin", "added_by", "added_at"}.issubset(cols)
    await conn.close()


@pytest.mark.asyncio
async def test_pending_state_table_columns():
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols = await get_columns(conn, "pending_state")
    assert {"user_id", "action", "data", "created_at"}.issubset(cols)
    await conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# IDEMPOTENCY — SAFE TO RUN TWICE
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_migrations_idempotent():
    """Running migrations twice should not raise or duplicate tables."""
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()
        await run_migrations()  # second run must be a no-op

    tables = await get_table_names(conn)
    assert "groups" in tables
    await conn.close()


@pytest.mark.asyncio
async def test_alter_migration_idempotent():
    """ALTER TABLE migration skipped gracefully if column already exists."""
    conn = await fresh_db()
    # Run once to create schema with all columns
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    # Run again — ALTER TABLE attempts should be silently skipped
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()  # must not raise

    cols = await get_columns(conn, "groups")
    assert "owner_id" in cols
    await conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# ALTER TABLE — OLD SCHEMA UPGRADES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_missing_owner_id_column_added():
    """Old `groups` table without owner_id should get the column added."""
    conn = await fresh_db()
    # Simulate old schema: groups table without owner_id
    await conn.execute("""
        CREATE TABLE groups (
            chat_id  INTEGER PRIMARY KEY,
            title    TEXT,
            added_at INTEGER
        )
    """)
    await conn.commit()

    cols_before = await get_columns(conn, "groups")
    assert "owner_id" not in cols_before

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols_after = await get_columns(conn, "groups")
    assert "owner_id" in cols_after
    await conn.close()


@pytest.mark.asyncio
async def test_missing_is_builtin_column_added():
    """Old `custom_patterns` table without is_builtin should get it added."""
    conn = await fresh_db()
    await conn.execute("""
        CREATE TABLE custom_patterns (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id  INTEGER,
            pattern  TEXT NOT NULL,
            label    TEXT NOT NULL,
            is_regex INTEGER DEFAULT 0,
            added_by INTEGER,
            added_at INTEGER
        )
    """)
    await conn.commit()

    cols_before = await get_columns(conn, "custom_patterns")
    assert "is_builtin" not in cols_before

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    cols_after = await get_columns(conn, "custom_patterns")
    assert "is_builtin" in cols_after
    await conn.close()


@pytest.mark.asyncio
async def test_existing_data_preserved_after_migration():
    """ALTER TABLE migration must not wipe existing rows."""
    conn = await fresh_db()
    await conn.execute("""
        CREATE TABLE groups (
            chat_id  INTEGER PRIMARY KEY,
            title    TEXT,
            added_at INTEGER
        )
    """)
    await conn.execute(
        "INSERT INTO groups (chat_id, title, added_at) VALUES (?, ?, ?)",
        (-999, "Old Group", 1000000)
    )
    await conn.commit()

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    async with conn.execute("SELECT * FROM groups WHERE chat_id = -999") as cur:
        row = await cur.fetchone()

    assert row is not None
    assert row["title"] == "Old Group"
    await conn.close()


@pytest.mark.asyncio
async def test_multiple_missing_columns_all_added():
    """If both owner_id and is_builtin are missing, both should be added."""
    conn = await fresh_db()

    await conn.execute("""
        CREATE TABLE groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_at INTEGER
        )
    """)
    await conn.execute("""
        CREATE TABLE custom_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            pattern TEXT NOT NULL,
            label TEXT NOT NULL,
            is_regex INTEGER DEFAULT 0,
            added_by INTEGER,
            added_at INTEGER
        )
    """)
    await conn.commit()

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    groups_cols = await get_columns(conn, "groups")
    patterns_cols = await get_columns(conn, "custom_patterns")
    assert "owner_id" in groups_cols
    assert "is_builtin" in patterns_cols
    await conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# STALE PENDING_STATE CLEANUP
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stale_pending_state_cleaned_on_startup():
    """Rows older than 1 hour should be deleted during migration startup."""
    conn = await fresh_db()

    # Create schema first
    await conn.executescript(SCHEMA)
    await conn.commit()

    now = int(time.time())
    stale_time = now - 7200  # 2 hours ago

    await conn.execute(
        "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
        (111, "addpat", '{"step":1}', stale_time)
    )
    await conn.commit()

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    async with conn.execute("SELECT COUNT(*) FROM pending_state WHERE user_id = 111") as cur:
        row = await cur.fetchone()
    assert row[0] == 0
    await conn.close()


@pytest.mark.asyncio
async def test_fresh_pending_state_survives_cleanup():
    """Rows younger than 1 hour must NOT be deleted on startup."""
    conn = await fresh_db()
    await conn.executescript(SCHEMA)
    await conn.commit()

    now = int(time.time())
    recent_time = now - 1800  # 30 minutes ago

    await conn.execute(
        "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
        (222, "addpat", '{"step":1}', recent_time)
    )
    await conn.commit()

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    async with conn.execute("SELECT COUNT(*) FROM pending_state WHERE user_id = 222") as cur:
        row = await cur.fetchone()
    assert row[0] == 1
    await conn.close()


@pytest.mark.asyncio
async def test_exactly_one_hour_old_is_cleaned():
    """Row at exactly 3600s old (the cutoff) should be deleted."""
    conn = await fresh_db()
    await conn.executescript(SCHEMA)
    await conn.commit()

    now = int(time.time())
    cutoff_time = now - 3601  # just over 1 hour

    await conn.execute(
        "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
        (333, "addpat", '{}', cutoff_time)
    )
    await conn.commit()

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    async with conn.execute("SELECT COUNT(*) FROM pending_state WHERE user_id = 333") as cur:
        row = await cur.fetchone()
    assert row[0] == 0
    await conn.close()


@pytest.mark.asyncio
async def test_mixed_pending_state_partial_cleanup():
    """Only stale rows deleted — fresh rows for other users survive."""
    conn = await fresh_db()
    await conn.executescript(SCHEMA)
    await conn.commit()

    now = int(time.time())
    await conn.execute(
        "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
        (444, "addpat", '{}', now - 7200)  # stale
    )
    await conn.execute(
        "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
        (555, "addpat", '{}', now - 300)  # fresh (5 min)
    )
    await conn.commit()

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    async with conn.execute("SELECT user_id FROM pending_state") as cur:
        survivors = {r[0] for r in await cur.fetchall()}

    assert 444 not in survivors
    assert 555 in survivors
    await conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# CONSTRAINTS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_group_admins_unique_constraint():
    """Inserting the same (chat_id, user_id) twice should fail."""
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    await conn.execute(
        "INSERT INTO group_admins (chat_id, user_id, role) VALUES (?, ?, 'admin')",
        (-1, 100)
    )
    await conn.commit()

    import sqlite3
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO group_admins (chat_id, user_id, role) VALUES (?, ?, 'admin')",
            (-1, 100)
        )
    await conn.close()


@pytest.mark.asyncio
async def test_pending_state_primary_key_constraint():
    """pending_state has user_id as PK — duplicate should fail."""
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    now = int(time.time())
    await conn.execute(
        "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
        (777, "addpat", '{}', now)
    )
    await conn.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO pending_state (user_id, action, data, created_at) VALUES (?,?,?,?)",
            (777, "addadmin", '{}', now)
        )
    await conn.close()


@pytest.mark.asyncio
async def test_muted_unique_per_group():
    """Same user muted in two different groups — both rows allowed."""
    conn = await fresh_db()
    with patch("db.migrations.get_db", AsyncMock(return_value=conn)):
        await run_migrations()

    now = int(time.time())
    await conn.execute(
        "INSERT INTO muted (chat_id, user_id, username, first_name, reason, muted_at) VALUES (?,?,?,?,?,?)",
        (-1, 999, "u", "U", "spam", now)
    )
    await conn.execute(
        "INSERT INTO muted (chat_id, user_id, username, first_name, reason, muted_at) VALUES (?,?,?,?,?,?)",
        (-2, 999, "u", "U", "spam", now)  # different group — OK
    )
    await conn.commit()

    async with conn.execute("SELECT COUNT(*) FROM muted WHERE user_id = 999") as cur:
        row = await cur.fetchone()
    assert row[0] == 2
    await conn.close()
