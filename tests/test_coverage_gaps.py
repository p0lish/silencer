"""
tests/test_coverage_gaps.py — Targeted tests to close remaining coverage gaps.

Covers: exception paths, empty-state branches, edit=False render paths,
register_* functions, and remaining logic branches.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from handlers.admin.menu import show_main_menu, register_menu_handler
from handlers.admin.group_view import group_view_callback, menu_callback, register_group_view_handlers
from handlers.admin.muted import muted_list_callback, unmute_callback, ban_callback, register_muted_handlers
from handlers.admin.spam_log import spam_log_callback, register_spam_log_handlers
from handlers.admin.patterns import (
    patterns_callback, addpat_callback, delpat_callback,
    pattern_input_handler, register_patterns_handlers, _show_patterns,
)
from handlers.admin.admins import (
    admins_callback, addadmin_callback, removeadmin_callback,
    addadmin_message_handler, show_admins, register_admins_handlers,
)
from handlers.admin import register_admin_handlers
from handlers.membership import register_membership_handler
from handlers.messages import register_message_handler

CHAT_ID = -1001234567890
OWNER_ID = 11111
ADMIN_ID = 22222
USER_ID  = 33333

# ── Mock factories (same as test_admin_handlers.py) ───────────────────────────

def _user(uid=OWNER_ID, username="owner"):
    u = MagicMock(); u.id = uid; u.username = username; u.first_name = "Owner"
    return u

def _query(user=None, data=""):
    q = MagicMock(); q.answer = AsyncMock(); q.edit_message_text = AsyncMock()
    q.from_user = user or _user(); q.message = MagicMock()
    q.message.reply_text = AsyncMock(); q.data = data
    return q

def _update(user=None, query=None, chat_type="private"):
    upd = MagicMock(); upd.effective_user = user or _user()
    upd.effective_chat = MagicMock(); upd.effective_chat.type = chat_type
    upd.callback_query = query; upd.effective_message = MagicMock()
    upd.effective_message.reply_text = AsyncMock()
    upd.message = MagicMock(); upd.message.text = None
    upd.message.reply_text = AsyncMock()
    return upd

def _context(match_groups=(), bot=None):
    ctx = MagicMock(); m = MagicMock()
    m.group = lambda i: match_groups[i - 1] if match_groups else ""
    ctx.matches = [m]; ctx.bot = bot or MagicMock()
    ctx.bot.restrict_chat_member = AsyncMock()
    ctx.bot.ban_chat_member = AsyncMock()
    return ctx

def _mock_app():
    app = MagicMock(); app.add_handler = MagicMock()
    return app


# ══════════════════════════════════════════════════════════════════════════════
# REGISTER FUNCTIONS — just verify they don't crash and call add_handler
# ══════════════════════════════════════════════════════════════════════════════

def test_register_menu_handler():
    app = _mock_app()
    register_menu_handler(app)
    app.add_handler.assert_called()


def test_register_group_view_handlers():
    app = _mock_app()
    register_group_view_handlers(app)
    assert app.add_handler.call_count == 2


def test_register_muted_handlers():
    app = _mock_app()
    register_muted_handlers(app)
    assert app.add_handler.call_count == 3


def test_register_spam_log_handlers():
    app = _mock_app()
    register_spam_log_handlers(app)
    app.add_handler.assert_called_once()


def test_register_patterns_handlers():
    app = _mock_app()
    register_patterns_handlers(app)
    assert app.add_handler.call_count >= 3


def test_register_admins_handlers():
    app = _mock_app()
    register_admins_handlers(app)
    assert app.add_handler.call_count >= 3


def test_register_admin_handlers_all():
    """register_admin_handlers should call all six sub-registrations."""
    app = _mock_app()
    register_admin_handlers(app)
    assert app.add_handler.call_count >= 6


def test_register_membership_handler():
    app = _mock_app()
    register_membership_handler(app)
    app.add_handler.assert_called_once()


def test_register_message_handler():
    app = _mock_app()
    register_message_handler(app)
    app.add_handler.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# MENU — exception path + edit=True with no-groups
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_show_main_menu_edit_message_raises(db):
    """Exception in edit_message_text should be caught and logged, not raised."""
    q = _query()
    q.edit_message_text = AsyncMock(side_effect=Exception("Telegram error"))
    upd = _update(query=q)
    groups = [{"chat_id": CHAT_ID, "title": "G", "role": "owner"}]
    with patch("handlers.admin.menu.get_admin_groups", AsyncMock(return_value=groups)):
        await show_main_menu(upd, _context(), edit=True)  # must not raise


@pytest.mark.asyncio
async def test_show_main_menu_edit_no_groups(db):
    """edit=True with no groups should use edit_message_text, not reply_text."""
    q = _query()
    upd = _update(query=q)
    with patch("handlers.admin.menu.get_admin_groups", AsyncMock(return_value=[])):
        await show_main_menu(upd, _context(), edit=True)
    q.edit_message_text.assert_called_once()
    upd.effective_message.reply_text.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP VIEW — exception path
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_group_view_edit_raises(db):
    """Exception in edit_message_text should not propagate."""
    q = _query()
    q.edit_message_text = AsyncMock(side_effect=Exception("flood"))
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.group_view.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.group_view.get_group", AsyncMock(return_value={"title": "G"})), \
         patch("handlers.admin.group_view.count_muted", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.count_spam", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.count_custom_patterns", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.is_group_owner", AsyncMock(return_value=False)):
        await group_view_callback(upd, ctx)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# MUTED — exception paths + unauthorized auth
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_muted_list_edit_raises(db):
    """Exception during muted list render should be caught."""
    q = _query()
    q.edit_message_text = AsyncMock(side_effect=Exception("rate limit"))
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    rows = [{"user_id": 1, "username": "u", "first_name": "U", "reason": "spam", "muted_at": 1700000000, "id": 1}]
    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.get_muted", AsyncMock(return_value=rows)):
        await muted_list_callback(upd, ctx)  # must not raise


@pytest.mark.asyncio
async def test_unmute_unauthorized(db):
    """Non-admin should be rejected in unmute callback."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "999"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=False)):
        await unmute_callback(upd, ctx)

    ctx.bot.restrict_chat_member.assert_not_called()
    q.answer.assert_called_with("Not authorized", show_alert=True)


@pytest.mark.asyncio
async def test_unmute_restrict_raises(db):
    """If restrict_chat_member fails, error path should be hit (not raise)."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "999"))
    ctx.bot.restrict_chat_member = AsyncMock(side_effect=Exception("no rights"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.remove_muted", AsyncMock()):
        await unmute_callback(upd, ctx)

    # Error path: query.answer called with show_alert=True
    calls = [str(c) for c in q.answer.call_args_list]
    assert any("show_alert" in c for c in calls)


@pytest.mark.asyncio
async def test_ban_unauthorized(db):
    """Non-admin should be rejected in ban callback."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "888"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=False)):
        await ban_callback(upd, ctx)

    ctx.bot.ban_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_ban_raises(db):
    """If ban_chat_member fails, error path fires."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "888"))
    ctx.bot.ban_chat_member = AsyncMock(side_effect=Exception("not admin"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.remove_muted", AsyncMock()):
        await ban_callback(upd, ctx)

    calls = [str(c) for c in q.answer.call_args_list]
    assert any("show_alert" in c for c in calls)


# ══════════════════════════════════════════════════════════════════════════════
# SPAM LOG — exception path
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_spam_log_edit_raises(db):
    """Exception during spam log render should be caught."""
    q = _query()
    q.edit_message_text = AsyncMock(side_effect=Exception("timeout"))
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    rows = [{"user_id": 1, "username": "u", "pattern": "p", "message": "m", "logged_at": 1700000000, "id": 1}]
    with patch("handlers.admin.spam_log.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.spam_log.get_spam_log", AsyncMock(return_value=rows)):
        await spam_log_callback(upd, ctx)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# PATTERNS — branches and exception paths
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_show_patterns_with_existing_rows(db):
    """_show_patterns renders pattern list when rows is non-empty."""
    q = _query()
    rows = [
        {"id": 1, "pattern": r"\bairdrop\b", "label": "crypto", "is_regex": 1},
        {"id": 2, "pattern": "click here", "label": "link bait", "is_regex": 0},
    ]
    with patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=rows)), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await _show_patterns(CHAT_ID, q, edit=True)

    text = q.edit_message_text.call_args[0][0]
    assert "airdrop" in text
    assert "regex" in text
    assert "click here" in text


@pytest.mark.asyncio
async def test_show_patterns_edit_false_uses_reply(db):
    """_show_patterns with edit=False should reply_text not edit_message_text."""
    q = _query()
    with patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=[])), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await _show_patterns(CHAT_ID, q, edit=False)

    q.message.reply_text.assert_called_once()
    q.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_show_patterns_edit_raises(db):
    """Exception in _show_patterns should be caught."""
    q = _query()
    q.edit_message_text = AsyncMock(side_effect=Exception("flood"))
    with patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=[])), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await _show_patterns(CHAT_ID, q, edit=True)  # must not raise


@pytest.mark.asyncio
async def test_delpat_pattern_not_found(db):
    """delpat callback should show 'Not found' alert if pattern doesn't exist."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "999"))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.patterns.delete_pattern", AsyncMock(return_value=False)), \
         patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=[])), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await delpat_callback(upd, ctx)

    calls = [str(c) for c in q.answer.call_args_list]
    assert any("Not found" in c for c in calls)


@pytest.mark.asyncio
async def test_addpat_unauthorized(db):
    """Non-admin should be rejected in addpat callback."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "keyword"))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=False)):
        await addpat_callback(upd, ctx)

    q.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_delpat_unauthorized(db):
    """Non-admin should be rejected in delpat callback."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "1"))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=False)), \
         patch("handlers.admin.patterns.delete_pattern", AsyncMock()) as mock_del:
        await delpat_callback(upd, ctx)

    mock_del.assert_not_called()


@pytest.mark.asyncio
async def test_pattern_input_no_message_text(db):
    """pattern_input_handler with empty message text should return silently."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = None
    upd.effective_message.reply_text = AsyncMock()
    upd.effective_user = _user(uid=OWNER_ID)

    with patch("handlers.admin.patterns.get_pending", AsyncMock()) as mock_get:
        await pattern_input_handler(upd, _context())

    # get_pending not called because msg.text is falsy
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_pattern_input_step1_redos_rejected(db):
    """ReDoS-flagged regex should be rejected with an error message."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = r"(a+)+"  # nested quantifier
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat", "chat_id": CHAT_ID, "type": "regex"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.set_pending", AsyncMock()) as mock_set:
        await pattern_input_handler(upd, _context())

    mock_set.assert_not_called()
    assert "dangerous" in upd.effective_message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_pattern_input_step2_duplicate_pattern(db):
    """Duplicate pattern in step 2 should show 'already exists' warning."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "crypto scam"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat_label", "chat_id": CHAT_ID, "pattern": r"\bairdrop\b", "type": "regex"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.add_pattern",
               AsyncMock(side_effect=Exception("UNIQUE constraint failed"))):
        await pattern_input_handler(upd, _context())

    text = upd.effective_message.reply_text.call_args[0][0]
    assert "already exists" in text


@pytest.mark.asyncio
async def test_pattern_input_step2_other_error(db):
    """Unknown error in step 2 should show generic error message."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "my label"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat_label", "chat_id": CHAT_ID, "pattern": "spam", "type": "keyword"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.add_pattern",
               AsyncMock(side_effect=Exception("disk full"))):
        await pattern_input_handler(upd, _context())

    text = upd.effective_message.reply_text.call_args[0][0]
    assert "disk full" in text or "Error" in text


@pytest.mark.asyncio
async def test_pattern_input_step2_rerenders_panel(db):
    """After successful add, patterns panel should be re-rendered."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "scam label"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat_label", "chat_id": CHAT_ID, "pattern": "spam phrase", "type": "keyword"}
    rows = [{"id": 1, "pattern": "spam phrase", "label": "scam label", "is_regex": 0}]
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.add_pattern", AsyncMock()), \
         patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=rows)), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await pattern_input_handler(upd, _context())

    # Should have called reply_text twice: success msg + panel re-render
    assert upd.effective_message.reply_text.call_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# ADMINS — empty list, addadmin unauthorized, exception paths
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_show_admins_empty_list(db):
    """show_admins with empty list should show 'No admins found'."""
    q = _query()
    upd = _update(query=q)

    with patch("handlers.admin.admins.get_group_admins", AsyncMock(return_value=[])), \
         patch("handlers.admin.admins.get_group", AsyncMock(return_value={"title": "G"})):
        await show_admins(upd, CHAT_ID, edit=True)

    text = q.edit_message_text.call_args[0][0]
    assert "No admins found" in text


@pytest.mark.asyncio
async def test_addadmin_callback_unauthorized(db):
    """Non-owner should be rejected in addadmin callback."""
    q = _query(user=_user(uid=ADMIN_ID))
    q.from_user = _user(uid=ADMIN_ID)
    upd = _update(user=_user(uid=ADMIN_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.admins.is_group_owner", AsyncMock(return_value=False)), \
         patch("handlers.admin.admins.set_pending", AsyncMock()) as mock_set:
        await addadmin_callback(upd, ctx)

    mock_set.assert_not_called()
    q.answer.assert_called_with("Owners only.")


@pytest.mark.asyncio
async def test_addadmin_message_handler_duplicate_admin(db):
    """Adding an existing admin should show 'already an admin' message."""
    upd = _update()
    upd.message.text = str(ADMIN_ID)
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addadmin", "chat_id": CHAT_ID}
    with patch("handlers.admin.admins.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.admins.clear_pending", AsyncMock()), \
         patch("handlers.admin.admins.add_admin",
               AsyncMock(side_effect=Exception("UNIQUE constraint failed"))):
        await addadmin_message_handler(upd, _context())

    text = upd.message.reply_text.call_args[0][0]
    assert "already an admin" in text


@pytest.mark.asyncio
async def test_addadmin_message_handler_generic_error(db):
    """Unknown DB error in addadmin should show generic error."""
    upd = _update()
    upd.message.text = "123456"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addadmin", "chat_id": CHAT_ID}
    with patch("handlers.admin.admins.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.admins.clear_pending", AsyncMock()), \
         patch("handlers.admin.admins.add_admin",
               AsyncMock(side_effect=Exception("I/O error"))):
        await addadmin_message_handler(upd, _context())

    text = upd.message.reply_text.call_args[0][0]
    assert "Error" in text or "I/O" in text


@pytest.mark.asyncio
async def test_migration_alter_exception_logged():
    """ALTER TABLE exception path: column already exists triggers SQLite error, caught gracefully."""
    import aiosqlite
    from db.migrations import run_migrations, SCHEMA

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    # Schema with owner_id already present (fresh DB)
    await conn.executescript(SCHEMA)
    await conn.commit()

    # Pretend owner_id is missing so ALTER is attempted — but it'll fail
    # because the column actually exists → hits the except/logger.warning branch
    async def fake_get_columns(table):
        async with conn.execute(f"PRAGMA table_info({table})") as cur:
            rows = await cur.fetchall()
        cols = {r["name"] for r in rows}
        if table == "groups":
            cols.discard("owner_id")  # lie: claim column missing
        return cols

    with patch("db.migrations.get_db", AsyncMock(return_value=conn)), \
         patch("db.migrations._get_columns", side_effect=fake_get_columns):
        # ALTER TABLE groups ADD COLUMN owner_id will fail (col exists)
        # The except block logs a warning — must not raise
        await run_migrations()

    await conn.close()
