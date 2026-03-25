"""
conftest.py — Shared fixtures for the test suite.

Key fixture: `db` — spins up an in-memory aiosqlite database,
runs migrations, and patches db.connection.get_db so all DB
functions use it. Cleaned up after each test.
"""

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
import aiosqlite

# Set dummy token before any config import triggers sys.exit
os.environ.setdefault("BOT_TOKEN", "test:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

# ── Schema (duplicated here so tests don't depend on migrations running) ──────
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


@pytest_asyncio.fixture
async def db():
    """
    In-memory aiosqlite DB, schema applied, patched into every module
    that imports get_db directly (from db.connection import get_db).
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()

    # AsyncMock so `await get_db()` returns the connection
    mock_get_db = AsyncMock(return_value=conn)

    # Patch every module-level get_db reference
    patches = [
        patch("db.connection.get_db",    mock_get_db),
        patch("db.groups.get_db",        mock_get_db),
        patch("db.admins.get_db",        mock_get_db),
        patch("db.patterns.get_db",      mock_get_db),
        patch("db.muted.get_db",         mock_get_db),
        patch("db.spam_log.get_db",      mock_get_db),
        patch("db.pending_state.get_db", mock_get_db),
        patch("detection.rules.get_db",  mock_get_db),
    ]

    for p in patches:
        p.start()

    yield conn

    for p in patches:
        p.stop()

    await conn.close()


# ── Telegram mock helpers ──────────────────────────────────────────────────────

def make_user(user_id=111, username="testuser", first_name="Test"):
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = first_name
    user.is_bot = False
    return user


def make_chat(chat_id=-1001234567890, title="Test Group", chat_type="supergroup"):
    chat = MagicMock()
    chat.id = chat_id
    chat.title = title
    chat.type = chat_type
    return chat


def make_message(text="hello", user=None, chat=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.from_user = user or make_user()
    msg.chat = chat or make_chat()
    msg.message_id = 42
    msg.delete = AsyncMock()
    msg.reply_text = AsyncMock()
    return msg


def make_update(message=None, callback_query=None, user=None):
    update = MagicMock()
    update.effective_user = user or make_user()
    update.effective_message = message or make_message()
    update.message = message
    update.callback_query = callback_query
    return update


def make_context(bot=None):
    ctx = MagicMock()
    ctx.bot = bot or MagicMock()
    ctx.bot.get_chat_member = AsyncMock()
    ctx.bot.restrict_chat_member = AsyncMock()
    ctx.bot.ban_chat_member = AsyncMock()
    ctx.matches = []
    return ctx
