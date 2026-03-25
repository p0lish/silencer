"""
tests/test_admin_handlers.py — Tests for handlers/admin/* (DM panel).

Covers: menu, group_view, muted, spam_log, patterns, admins.
All Telegram objects are mocked. DB fixture from conftest.py.
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from handlers.admin.menu import show_main_menu, start_command
from handlers.admin.group_view import group_view_callback, menu_callback
from handlers.admin.muted import muted_list_callback, unmute_callback, ban_callback, _ts_to_date, _user_label
from handlers.admin.spam_log import spam_log_callback
from handlers.admin.patterns import patterns_callback, addpat_callback, delpat_callback, pattern_input_handler
from handlers.admin.admins import admins_callback, addadmin_callback, removeadmin_callback, addadmin_message_handler

from db.groups import upsert_group
from db.admins import add_admin, get_group_admins, is_group_admin
from db.muted import add_muted, get_muted
from db.patterns import add_pattern, get_patterns_for_group, count_custom_patterns
from db.pending_state import set_pending, get_pending

CHAT_ID = -1001234567890
OWNER_ID = 11111
ADMIN_ID = 22222
USER_ID  = 33333

# ── Mock factories ─────────────────────────────────────────────────────────────

def _user(uid=OWNER_ID, username="owner"):
    u = MagicMock()
    u.id = uid
    u.username = username
    u.first_name = "Owner"
    return u


def _query(user=None, data=""):
    q = MagicMock()
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.from_user = user or _user()
    q.message = MagicMock()
    q.message.reply_text = AsyncMock()
    q.data = data
    return q


def _update(user=None, query=None, chat_type="private"):
    upd = MagicMock()
    upd.effective_user = user or _user()
    upd.effective_chat = MagicMock()
    upd.effective_chat.type = chat_type
    upd.callback_query = query
    upd.effective_message = MagicMock()
    upd.effective_message.reply_text = AsyncMock()
    upd.message = MagicMock()
    upd.message.text = None
    upd.message.reply_text = AsyncMock()
    return upd


def _context(match_groups=(), bot=None):
    ctx = MagicMock()
    m = MagicMock()
    m.group = lambda i: match_groups[i - 1] if match_groups else ""
    ctx.matches = [m]
    ctx.bot = bot or MagicMock()
    ctx.bot.restrict_chat_member = AsyncMock()
    ctx.bot.ban_chat_member = AsyncMock()
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# MENU — /start handler
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_start_ignored_in_group(db):
    """'/start' in a group chat must be silently ignored."""
    upd = _update(chat_type="supergroup")
    with patch("handlers.admin.menu.get_admin_groups") as mock_groups:
        await start_command(upd, _context())
    mock_groups.assert_not_called()


@pytest.mark.asyncio
async def test_start_shows_menu_in_private(db):
    """'/start' in private chat calls show_main_menu."""
    upd = _update(chat_type="private")
    with patch("handlers.admin.menu.get_admin_groups", AsyncMock(return_value=[])):
        await start_command(upd, _context())
    upd.effective_message.reply_text.assert_called_once()
    assert "not an admin" in upd.effective_message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_menu_shows_groups_when_admin(db):
    """Admin with groups should see group buttons."""
    upd = _update(chat_type="private")
    groups = [{"chat_id": CHAT_ID, "title": "Cool Group", "role": "owner"}]
    with patch("handlers.admin.menu.get_admin_groups", AsyncMock(return_value=groups)):
        await show_main_menu(upd, _context(), edit=False)

    call_args = upd.effective_message.reply_text.call_args
    assert "Cool Group" in str(call_args)


@pytest.mark.asyncio
async def test_menu_shows_no_groups_message(db):
    """Non-admin should see 'not an admin' message."""
    upd = _update()
    with patch("handlers.admin.menu.get_admin_groups", AsyncMock(return_value=[])):
        await show_main_menu(upd, _context(), edit=False)
    upd.effective_message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_menu_edit_uses_callback_query(db):
    """When edit=True, menu should edit existing message via callback_query."""
    q = _query()
    upd = _update(query=q)
    groups = [{"chat_id": CHAT_ID, "title": "G", "role": "admin"}]
    with patch("handlers.admin.menu.get_admin_groups", AsyncMock(return_value=groups)):
        await show_main_menu(upd, _context(), edit=True)
    q.edit_message_text.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP VIEW
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_group_view_unauthorized(db):
    """Non-admin should get an auth error, no group view."""
    q = _query(user=_user(uid=USER_ID))
    upd = _update(user=_user(uid=USER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.group_view.is_group_admin", AsyncMock(return_value=False)):
        await group_view_callback(upd, ctx)

    q.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_group_view_shows_stats(db):
    """Admin should see muted/spam/pattern counts."""
    q = _query(user=_user(uid=OWNER_ID))
    upd = _update(user=_user(uid=OWNER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.group_view.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.group_view.get_group", AsyncMock(return_value={"chat_id": CHAT_ID, "title": "My Group"})), \
         patch("handlers.admin.group_view.count_muted", AsyncMock(return_value=3)), \
         patch("handlers.admin.group_view.count_spam", AsyncMock(return_value=12)), \
         patch("handlers.admin.group_view.count_custom_patterns", AsyncMock(return_value=2)), \
         patch("handlers.admin.group_view.is_group_owner", AsyncMock(return_value=True)):
        await group_view_callback(upd, ctx)

    text = q.edit_message_text.call_args[0][0]
    assert "3" in text   # muted count
    assert "12" in text  # spam count
    assert "2" in text   # patterns count


@pytest.mark.asyncio
async def test_group_view_owner_sees_admins_button(db):
    """Owners should see the 'Manage admins' button, non-owners should not."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.group_view.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.group_view.get_group", AsyncMock(return_value={"title": "G"})), \
         patch("handlers.admin.group_view.count_muted", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.count_spam", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.count_custom_patterns", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.is_group_owner", AsyncMock(return_value=True)):
        await group_view_callback(upd, ctx)

    keyboard_str = str(q.edit_message_text.call_args)
    assert "admins" in keyboard_str


@pytest.mark.asyncio
async def test_group_view_non_owner_no_admins_button(db):
    """Non-owner admin should not see 'Manage admins' button."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.group_view.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.group_view.get_group", AsyncMock(return_value={"title": "G"})), \
         patch("handlers.admin.group_view.count_muted", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.count_spam", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.count_custom_patterns", AsyncMock(return_value=0)), \
         patch("handlers.admin.group_view.is_group_owner", AsyncMock(return_value=False)):
        await group_view_callback(upd, ctx)

    keyboard_str = str(q.edit_message_text.call_args)
    assert f"admins:{CHAT_ID}" not in keyboard_str


@pytest.mark.asyncio
async def test_menu_callback_calls_show_main_menu(db):
    """'menu' callback should trigger show_main_menu with edit=True."""
    q = _query()
    upd = _update(query=q)

    with patch("handlers.admin.group_view.show_main_menu", AsyncMock()) as mock_menu:
        await menu_callback(upd, _context())

    mock_menu.assert_called_once()
    _, call_kwargs = mock_menu.call_args[0], mock_menu.call_args[1] or {}
    assert mock_menu.call_args[1].get("edit", mock_menu.call_args[0][2] if len(mock_menu.call_args[0]) > 2 else None) is True


# ══════════════════════════════════════════════════════════════════════════════
# MUTED LIST
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_muted_list_empty(db):
    """Empty muted list should show 'No muted users'."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.get_muted", AsyncMock(return_value=[])):
        await muted_list_callback(upd, ctx)

    text = q.edit_message_text.call_args[0][0]
    assert "No muted" in text


@pytest.mark.asyncio
async def test_muted_list_shows_users(db):
    """Muted list should render each user's name + reason."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    rows = [
        {"user_id": 111, "username": "spammer1", "first_name": "S1", "reason": "crypto", "muted_at": 1700000000, "id": 1},
        {"user_id": 222, "username": None,        "first_name": "S2", "reason": "fake job", "muted_at": 1700000001, "id": 2},
    ]
    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.get_muted", AsyncMock(return_value=rows)):
        await muted_list_callback(upd, ctx)

    text = q.edit_message_text.call_args[0][0]
    assert "@spammer1" in text
    assert "crypto" in text


@pytest.mark.asyncio
async def test_muted_list_unauthorized(db):
    """Non-admin should not see the muted list."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=False)):
        await muted_list_callback(upd, ctx)

    q.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_unmute_calls_restrict(db):
    """Unmute should call restrict_chat_member with full permissions."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "999"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.remove_muted", AsyncMock()):
        await unmute_callback(upd, ctx)

    ctx.bot.restrict_chat_member.assert_called_once()
    assert ctx.bot.restrict_chat_member.call_args[0][1] == 999


@pytest.mark.asyncio
async def test_unmute_removes_from_db(db):
    """Unmute should call remove_muted to clean up the DB record."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "999"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.remove_muted", AsyncMock()) as mock_rm:
        await unmute_callback(upd, ctx)

    mock_rm.assert_called_once_with(CHAT_ID, 999)


@pytest.mark.asyncio
async def test_ban_calls_ban_chat_member(db):
    """Ban should call bot.ban_chat_member."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "888"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.remove_muted", AsyncMock()):
        await ban_callback(upd, ctx)

    ctx.bot.ban_chat_member.assert_called_once_with(CHAT_ID, 888)


@pytest.mark.asyncio
async def test_ban_removes_from_muted_db(db):
    """Ban should also remove the user from muted DB."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "888"))

    with patch("handlers.admin.muted.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.muted.remove_muted", AsyncMock()) as mock_rm:
        await ban_callback(upd, ctx)

    mock_rm.assert_called_once_with(CHAT_ID, 888)


# ══════════════════════════════════════════════════════════════════════════════
# SPAM LOG
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_spam_log_empty(db):
    """Empty spam log should show 'No spam logged yet'."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.spam_log.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.spam_log.get_spam_log", AsyncMock(return_value=[])):
        await spam_log_callback(upd, ctx)

    text = q.edit_message_text.call_args[0][0]
    assert "No spam" in text


@pytest.mark.asyncio
async def test_spam_log_shows_entries(db):
    """Spam log should render each entry's user, pattern, message preview."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    rows = [{"user_id": 111, "username": "badguy", "pattern": "crypto scam",
             "message": "Join our channel!", "logged_at": 1700000000, "id": 1}]
    with patch("handlers.admin.spam_log.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.spam_log.get_spam_log", AsyncMock(return_value=rows)):
        await spam_log_callback(upd, ctx)

    text = q.edit_message_text.call_args[0][0]
    assert "@badguy" in text
    assert "crypto scam" in text


@pytest.mark.asyncio
async def test_spam_log_unauthorized(db):
    """Non-admin should not see spam log."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.spam_log.is_group_admin", AsyncMock(return_value=False)):
        await spam_log_callback(upd, ctx)

    q.edit_message_text.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_patterns_callback_unauthorized(db):
    """Non-admin should not see patterns panel."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=False)):
        await patterns_callback(upd, ctx)

    q.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_patterns_callback_shows_panel(db):
    """Admin should see the patterns panel."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=[])), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await patterns_callback(upd, ctx)

    q.edit_message_text.assert_called_once()


@pytest.mark.asyncio
async def test_addpat_sets_pending_state(db):
    """addpat callback should create a pending_state record for the user."""
    q = _query(user=_user(uid=OWNER_ID))
    upd = _update(user=_user(uid=OWNER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "keyword"))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=True)), \
         patch("db.pending_state.get_db", AsyncMock(return_value=db)):
        await addpat_callback(upd, ctx)

    pending = await get_pending(OWNER_ID)
    assert pending is not None
    assert pending["action"] == "addpat"
    assert pending["type"] == "keyword"


@pytest.mark.asyncio
async def test_addpat_prompts_user(db):
    """addpat callback should send a prompt message."""
    q = _query(user=_user(uid=OWNER_ID))
    upd = _update(user=_user(uid=OWNER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "regex"))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.patterns.set_pending", AsyncMock()):
        await addpat_callback(upd, ctx)

    q.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_delpat_callback_deletes_pattern(db):
    """delpat callback should call delete_pattern with correct IDs."""
    q = _query()
    upd = _update(query=q)
    ctx = _context(match_groups=(str(CHAT_ID), "42"))

    with patch("handlers.admin.patterns.is_group_admin", AsyncMock(return_value=True)), \
         patch("handlers.admin.patterns.delete_pattern", AsyncMock(return_value=True)) as mock_del, \
         patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=[])), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await delpat_callback(upd, ctx)

    mock_del.assert_called_once_with(42, CHAT_ID)


@pytest.mark.asyncio
async def test_pattern_input_step1_keyword_valid(db):
    """Valid keyword in step 1 should move to step 2 (ask for label)."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "earn money fast"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat", "chat_id": CHAT_ID, "type": "keyword"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.set_pending", AsyncMock()) as mock_set:
        await pattern_input_handler(upd, _context())

    mock_set.assert_called_once()
    set_args = mock_set.call_args[0]
    assert set_args[1] == "addpat_label"


@pytest.mark.asyncio
async def test_pattern_input_step1_keyword_too_short(db):
    """Keyword under 3 chars should be rejected."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "ab"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat", "chat_id": CHAT_ID, "type": "keyword"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.set_pending", AsyncMock()) as mock_set:
        await pattern_input_handler(upd, _context())

    mock_set.assert_not_called()
    upd.effective_message.reply_text.assert_called_once()
    assert "short" in upd.effective_message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_pattern_input_step1_invalid_regex(db):
    """Invalid regex in step 1 should return an error, not proceed."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = r"[invalid(regex"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat", "chat_id": CHAT_ID, "type": "regex"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.set_pending", AsyncMock()) as mock_set:
        await pattern_input_handler(upd, _context())

    mock_set.assert_not_called()
    assert "invalid regex" in upd.effective_message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_pattern_input_step1_wildcard_rejected(db):
    """Pure wildcard regex should be rejected."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = ".*"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat", "chat_id": CHAT_ID, "type": "regex"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.set_pending", AsyncMock()) as mock_set:
        await pattern_input_handler(upd, _context())

    mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_pattern_input_step2_saves_to_db(db):
    """Step 2 (label) should call add_pattern and confirm success."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "investment scam"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addpat_label", "chat_id": CHAT_ID, "pattern": r"\bairdrop\b", "type": "regex"}
    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.patterns.clear_pending", AsyncMock()), \
         patch("handlers.admin.patterns.add_pattern", AsyncMock()) as mock_add, \
         patch("handlers.admin.patterns.get_custom_patterns", AsyncMock(return_value=[])), \
         patch("handlers.admin.patterns.get_group", AsyncMock(return_value={"title": "G"})):
        await pattern_input_handler(upd, _context())

    mock_add.assert_called_once()
    call_kwargs = mock_add.call_args[1]
    assert call_kwargs["pattern"] == r"\bairdrop\b"
    assert call_kwargs["label"] == "investment scam"


@pytest.mark.asyncio
async def test_pattern_input_no_pending_ignored(db):
    """Text with no pending state should be silently ignored."""
    upd = _update(chat_type="private")
    upd.effective_chat.type = "private"
    upd.effective_message.text = "random text"
    upd.effective_user = _user(uid=OWNER_ID)

    with patch("handlers.admin.patterns.get_pending", AsyncMock(return_value=None)), \
         patch("handlers.admin.patterns.add_pattern", AsyncMock()) as mock_add:
        await pattern_input_handler(upd, _context())

    mock_add.assert_not_called()


@pytest.mark.asyncio
async def test_pattern_input_group_chat_ignored(db):
    """Text from a group chat should be ignored even with pending state."""
    upd = _update(chat_type="supergroup")
    upd.effective_chat.type = "supergroup"
    upd.effective_message.text = "valid keyword"
    upd.effective_user = _user(uid=OWNER_ID)

    with patch("handlers.admin.patterns.get_pending", AsyncMock()) as mock_get:
        await pattern_input_handler(upd, _context())

    mock_get.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# ADMINS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_admins_callback_owners_only(db):
    """admins callback should reject non-owners."""
    q = _query(user=_user(uid=ADMIN_ID))
    upd = _update(user=_user(uid=ADMIN_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.admins.is_group_owner", AsyncMock(return_value=False)):
        await admins_callback(upd, ctx)

    q.edit_message_text.assert_not_called()
    q.answer.assert_called_with("Owners only.")


@pytest.mark.asyncio
async def test_admins_callback_shows_list(db):
    """Owner should see the admin list."""
    q = _query(user=_user(uid=OWNER_ID))
    upd = _update(user=_user(uid=OWNER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    admins = [
        {"user_id": OWNER_ID, "username": "owner", "role": "owner"},
        {"user_id": ADMIN_ID,  "username": "admin1", "role": "admin"},
    ]
    with patch("handlers.admin.admins.is_group_owner", AsyncMock(return_value=True)), \
         patch("handlers.admin.admins.get_group_admins", AsyncMock(return_value=admins)), \
         patch("handlers.admin.admins.get_group", AsyncMock(return_value={"title": "G"})):
        await admins_callback(upd, ctx)

    text = q.edit_message_text.call_args[0][0]
    assert "@admin1" in text


@pytest.mark.asyncio
async def test_addadmin_callback_sets_pending(db):
    """addadmin callback should set pending state for the owner."""
    q = _query(user=_user(uid=OWNER_ID))
    upd = _update(user=_user(uid=OWNER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID),))

    with patch("handlers.admin.admins.is_group_owner", AsyncMock(return_value=True)), \
         patch("db.pending_state.get_db", AsyncMock(return_value=db)):
        await addadmin_callback(upd, ctx)

    pending = await get_pending(OWNER_ID)
    assert pending is not None
    assert pending["action"] == "addadmin"
    assert pending["chat_id"] == CHAT_ID


@pytest.mark.asyncio
async def test_removeadmin_callback_owners_only(db):
    """removeadmin should reject non-owners."""
    q = _query(user=_user(uid=ADMIN_ID))
    upd = _update(user=_user(uid=ADMIN_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID), str(USER_ID)))

    with patch("handlers.admin.admins.is_group_owner", AsyncMock(return_value=False)):
        await removeadmin_callback(upd, ctx)

    q.answer.assert_called_with("Owners only.")


@pytest.mark.asyncio
async def test_removeadmin_callback_removes(db):
    """removeadmin should call remove_admin with correct IDs."""
    q = _query(user=_user(uid=OWNER_ID))
    upd = _update(user=_user(uid=OWNER_ID), query=q)
    ctx = _context(match_groups=(str(CHAT_ID), str(ADMIN_ID)))

    admins = [{"user_id": OWNER_ID, "username": "owner", "role": "owner"}]
    with patch("handlers.admin.admins.is_group_owner", AsyncMock(return_value=True)), \
         patch("handlers.admin.admins.remove_admin", AsyncMock()) as mock_rm, \
         patch("handlers.admin.admins.get_group_admins", AsyncMock(return_value=admins)), \
         patch("handlers.admin.admins.get_group", AsyncMock(return_value={"title": "G"})):
        await removeadmin_callback(upd, ctx)

    mock_rm.assert_called_once_with(CHAT_ID, ADMIN_ID)


@pytest.mark.asyncio
async def test_addadmin_message_handler_valid_id(db):
    """Valid user ID in addadmin flow should call add_admin."""
    upd = _update()
    upd.message.text = "987654"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addadmin", "chat_id": CHAT_ID}
    admins = [{"user_id": OWNER_ID, "username": "owner", "role": "owner"}]
    with patch("handlers.admin.admins.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.admins.clear_pending", AsyncMock()), \
         patch("handlers.admin.admins.add_admin", AsyncMock()) as mock_add, \
         patch("handlers.admin.admins.get_group_admins", AsyncMock(return_value=admins)), \
         patch("handlers.admin.admins.get_group", AsyncMock(return_value={"title": "G"})):
        await addadmin_message_handler(upd, _context())

    mock_add.assert_called_once_with(CHAT_ID, 987654, None, "admin", OWNER_ID)


@pytest.mark.asyncio
async def test_addadmin_message_handler_invalid_id(db):
    """Non-numeric input should show error and clear pending state."""
    upd = _update()
    upd.message.text = "notanumber"
    upd.effective_user = _user(uid=OWNER_ID)

    pending_data = {"action": "addadmin", "chat_id": CHAT_ID}
    with patch("handlers.admin.admins.get_pending", AsyncMock(return_value=pending_data)), \
         patch("handlers.admin.admins.clear_pending", AsyncMock()) as mock_clear, \
         patch("handlers.admin.admins.add_admin", AsyncMock()) as mock_add:
        await addadmin_message_handler(upd, _context())

    mock_add.assert_not_called()
    mock_clear.assert_called_once()
    upd.message.reply_text.assert_called_once()
    assert "invalid" in upd.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_addadmin_message_handler_no_pending_ignored(db):
    """Text with no addadmin pending state should be ignored."""
    upd = _update()
    upd.message.text = "123456"
    upd.effective_user = _user(uid=OWNER_ID)

    with patch("handlers.admin.admins.get_pending", AsyncMock(return_value=None)), \
         patch("handlers.admin.admins.add_admin", AsyncMock()) as mock_add:
        await addadmin_message_handler(upd, _context())

    mock_add.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def test_ts_to_date():
    assert _ts_to_date(0) == "1970-01-01"
    assert _ts_to_date(1700000000) == "2023-11-14"


def test_user_label_username():
    row = {"username": "cooluser", "first_name": "Cool", "user_id": 123}
    assert _user_label(row) == "@cooluser"


def test_user_label_first_name():
    row = {"username": None, "first_name": "Alice", "user_id": 123}
    assert _user_label(row) == "Alice"


def test_user_label_fallback_id():
    row = {"username": None, "first_name": None, "user_id": 123}
    assert _user_label(row) == "id:123"
