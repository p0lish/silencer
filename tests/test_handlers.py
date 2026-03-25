"""
tests/test_handlers.py — Tests for group message and membership handlers.

Uses the `db` fixture (in-memory SQLite) from conftest.py.
Telegram objects (Update, Message, Chat, User, Bot) are mocked.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

from handlers.messages import on_group_message, _display_name
from handlers.membership import on_my_chat_member
from db.muted import get_muted, count_muted
from db.spam_log import get_spam_log, count_spam
from db.groups import get_group
from db.admins import is_group_admin, is_group_owner

CHAT_ID = -1001234567890
USER_ID = 55555
BOT_ID  = 8722226336

# ── Telegram mock factories ────────────────────────────────────────────────────

def _user(user_id=USER_ID, username="spammer", first_name="Spammer", is_bot=False):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = first_name
    u.is_bot = is_bot
    return u


def _chat(chat_id=CHAT_ID, title="Test Group", chat_type="supergroup"):
    c = MagicMock()
    c.id = chat_id
    c.title = title
    c.type = chat_type
    return c


def _message(text="hello", user=None, chat=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.from_user = user or _user()
    msg.chat = chat or _chat()
    msg.delete = AsyncMock()
    msg.reply_text = AsyncMock()
    return msg


def _update(message=None, chat=None, user=None):
    upd = MagicMock()
    upd.effective_message = message or _message()
    upd.effective_chat = chat or _chat()
    upd.effective_user = user or _user()
    upd.my_chat_member = None
    upd.message = upd.effective_message
    return upd


def _context(is_admin=False):
    ctx = MagicMock()
    member = MagicMock()
    member.status = "administrator" if is_admin else "member"
    ctx.bot = MagicMock()
    ctx.bot.get_chat_member = AsyncMock(return_value=member)
    ctx.bot.restrict_chat_member = AsyncMock()
    ctx.bot.ban_chat_member = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def _member_update(new_status, chat=None, added_by=None):
    """Simulate a my_chat_member update (bot status changed)."""
    event = MagicMock()
    event.chat = chat or _chat()
    event.from_user = added_by or _user(user_id=99999, username="groupowner")
    event.new_chat_member = MagicMock()
    event.new_chat_member.status = new_status
    upd = MagicMock()
    upd.my_chat_member = event
    upd.effective_user = event.from_user
    return upd


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER — SPAM DETECTED
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_spam_message_deleted(db):
    """When score >= 2, the message should be deleted."""
    msg = _message(text="🚀💰🎁 Join our crypto trading group now, earn $500 per day guaranteed!")
    upd = _update(message=msg)
    ctx = _context(is_admin=False)

    with patch("handlers.messages.score_message", return_value=(3, ["crypto scam", "investment scam", "3 emojis"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("handlers.messages.add_muted", AsyncMock()):
        await on_group_message(upd, ctx)

    msg.delete.assert_called_once()


@pytest.mark.asyncio
async def test_spam_message_user_restricted(db):
    """When spam detected, restrict_chat_member should be called."""
    msg = _message(text="🚀💰🎁 Join our crypto trading group now earn $500 per day!")
    upd = _update(message=msg)
    ctx = _context(is_admin=False)

    with patch("handlers.messages.score_message", return_value=(3, ["crypto scam", "3 emojis"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("handlers.messages.add_muted", AsyncMock()):
        await on_group_message(upd, ctx)

    ctx.bot.restrict_chat_member.assert_called_once()
    call_args = ctx.bot.restrict_chat_member.call_args
    assert call_args[0][0] == CHAT_ID
    assert call_args[0][1] == USER_ID


@pytest.mark.asyncio
async def test_spam_message_logged_to_db(db):
    """Spam detection should write a record to spam_log."""
    msg = _message(text="🚀💰🎁 Join our crypto trading group now earn $500 per day!")
    msg.from_user = _user(user_id=USER_ID, username="badactor")
    upd = _update(message=msg, chat=_chat(CHAT_ID))

    # Patch DB calls but let spam_log write through to real DB
    with patch("handlers.messages.score_message", return_value=(3, ["crypto scam", "3 emojis"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.add_muted", AsyncMock()), \
         patch("db.spam_log.get_db", AsyncMock(return_value=db)):
        await on_group_message(upd, _context())

    rows = await get_spam_log(CHAT_ID)
    assert len(rows) == 1
    assert rows[0]["user_id"] == USER_ID


@pytest.mark.asyncio
async def test_spam_message_muted_in_db(db):
    """Spam user should be added to muted table."""
    msg = _message(text="🚀💰🎁 airdrop crypto trading earn money guaranteed profit now!")
    msg.from_user = _user(user_id=USER_ID, username="spammer99")
    upd = _update(message=msg, chat=_chat(CHAT_ID))

    with patch("handlers.messages.score_message", return_value=(3, ["crypto scam", "3 emojis"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("db.muted.get_db", AsyncMock(return_value=db)):
        await on_group_message(upd, _context())

    rows = await get_muted(CHAT_ID)
    assert len(rows) == 1
    assert rows[0]["user_id"] == USER_ID
    assert rows[0]["username"] == "spammer99"


@pytest.mark.asyncio
async def test_spam_message_group_notified(db):
    """After muting, bot should send a notification in the group."""
    msg = _message()
    upd = _update(message=msg)
    ctx = _context()

    with patch("handlers.messages.score_message", return_value=(2, ["crypto scam", "long message"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("handlers.messages.add_muted", AsyncMock()):
        await on_group_message(upd, ctx)

    ctx.bot.send_message.assert_called_once()
    args = ctx.bot.send_message.call_args[0]
    assert args[0] == CHAT_ID
    assert "muted" in args[1].lower()


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER — SHOULD NOT TRIGGER
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_telegram_admin_not_muted(db):
    """Telegram admins/creators must never be muted, even if message scores high."""
    msg = _message(text="🚀💰🎁 airdrop crypto group earn money passive income guaranteed!")
    upd = _update(message=msg)
    ctx = _context(is_admin=True)  # user IS a Telegram admin

    with patch("handlers.messages.score_message") as mock_score, \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}):
        await on_group_message(upd, ctx)

    # Scorer should not even be called for admins
    mock_score.assert_not_called()
    msg.delete.assert_not_called()
    ctx.bot.restrict_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_private_message_ignored(db):
    """Private chat messages should be completely ignored."""
    private_chat = _chat(chat_id=USER_ID, chat_type="private")
    msg = _message(chat=private_chat)
    upd = _update(message=msg, chat=private_chat)

    with patch("handlers.messages.score_message") as mock_score:
        await on_group_message(upd, _context())

    mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_command_message_ignored(db):
    """/commands in groups must be skipped."""
    msg = _message(text="/start")
    upd = _update(message=msg)

    with patch("handlers.messages.score_message") as mock_score, \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}):
        await on_group_message(upd, _context())

    mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_low_score_message_not_actioned(db):
    """Score of 1 should not trigger delete/mute."""
    msg = _message(text="airdrop happening soon somewhere check it out please!")
    upd = _update(message=msg)
    ctx = _context()

    with patch("handlers.messages.score_message", return_value=(1, ["crypto scam"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}):
        await on_group_message(upd, ctx)

    msg.delete.assert_not_called()
    ctx.bot.restrict_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_no_user_message_ignored(db):
    """Messages with no from_user (channel posts) should be skipped."""
    msg = _message()
    msg.from_user = None
    upd = _update(message=msg)

    with patch("handlers.messages.score_message") as mock_score, \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}):
        await on_group_message(upd, _context())

    mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_caption_scored_not_just_text(db):
    """If message has no text but has a caption, caption should be scored."""
    msg = _message(text=None)
    msg.caption = "🚀💰🎁 Earn $500 per day from home with our crypto trading signals!"
    upd = _update(message=msg)
    ctx = _context()

    scored_text = None
    async def capture_score(text, chat_id):
        nonlocal scored_text
        scored_text = text
        return 2, ["investment scam", "3 emojis"]

    with patch("handlers.messages.score_message", side_effect=capture_score), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("handlers.messages.add_muted", AsyncMock()):
        await on_group_message(upd, ctx)

    assert scored_text == msg.caption


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER — RESILIENCE
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_failure_does_not_crash(db):
    """If message deletion fails (e.g. no permission), handler should continue."""
    msg = _message()
    msg.delete = AsyncMock(side_effect=Exception("Message not found"))
    upd = _update(message=msg)
    ctx = _context()

    with patch("handlers.messages.score_message", return_value=(3, ["crypto scam", "3 emojis"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("handlers.messages.add_muted", AsyncMock()):
        # Should not raise
        await on_group_message(upd, ctx)


@pytest.mark.asyncio
async def test_restrict_failure_does_not_crash(db):
    """If restrict_chat_member fails (bot not admin), handler should not crash."""
    msg = _message()
    upd = _update(message=msg)
    ctx = _context()
    ctx.bot.restrict_chat_member = AsyncMock(side_effect=Exception("Not enough rights"))

    with patch("handlers.messages.score_message", return_value=(3, ["crypto scam", "3 emojis"])), \
         patch("handlers.messages.get_group", return_value={"chat_id": CHAT_ID}), \
         patch("handlers.messages.log_spam", AsyncMock()), \
         patch("handlers.messages.add_muted", AsyncMock()):
        await on_group_message(upd, ctx)  # must not raise


@pytest.mark.asyncio
async def test_auto_registers_unknown_group(db):
    """First message in an unregistered group should auto-register it."""
    upd = _update(message=_message(text="hello there friend how are you doing today"))

    with patch("handlers.messages.score_message", return_value=(0, [])), \
         patch("handlers.messages.get_group", return_value=None), \
         patch("db.groups.get_db", AsyncMock(return_value=db)):
        await on_group_message(upd, _context())

    group = await get_group(CHAT_ID)
    assert group is not None
    assert group["title"] == "Test Group"


# ══════════════════════════════════════════════════════════════════════════════
# MEMBERSHIP HANDLER
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bot_added_registers_group(db):
    """When bot is added to a group, the group should be registered in DB."""
    owner = _user(user_id=99999, username="groupowner")
    upd = _member_update("administrator", chat=_chat(CHAT_ID, "My Group"), added_by=owner)

    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(upd, _context())

    group = await get_group(CHAT_ID)
    assert group is not None
    assert group["title"] == "My Group"


@pytest.mark.asyncio
async def test_bot_added_registers_owner(db):
    """The user who added the bot should become owner of the group."""
    owner = _user(user_id=99999, username="groupowner")
    upd = _member_update("member", chat=_chat(CHAT_ID), added_by=owner)

    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(upd, _context())

    assert await is_group_owner(CHAT_ID, 99999) is True


@pytest.mark.asyncio
async def test_bot_added_as_member_also_registers(db):
    """Status 'member' (not just 'administrator') should also register."""
    owner = _user(user_id=88888, username="adder")
    upd = _member_update("member", chat=_chat(CHAT_ID), added_by=owner)

    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(upd, _context())

    assert await get_group(CHAT_ID) is not None
    assert await is_group_owner(CHAT_ID, 88888) is True


@pytest.mark.asyncio
async def test_bot_removed_deletes_group(db):
    """When bot is kicked, the group should be removed from DB."""
    # First register the group
    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        owner = _user(user_id=99999, username="owner")
        upd_add = _member_update("administrator", chat=_chat(CHAT_ID), added_by=owner)
        await on_my_chat_member(upd_add, _context())

    assert await get_group(CHAT_ID) is not None

    # Now remove
    upd_remove = _member_update("kicked", chat=_chat(CHAT_ID))
    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(upd_remove, _context())

    assert await get_group(CHAT_ID) is None


@pytest.mark.asyncio
async def test_bot_left_deletes_group(db):
    """Status 'left' should also remove the group."""
    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        owner = _user(user_id=99999)
        await on_my_chat_member(_member_update("administrator", added_by=owner), _context())

    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(_member_update("left", chat=_chat(CHAT_ID)), _context())

    assert await get_group(CHAT_ID) is None


@pytest.mark.asyncio
async def test_bot_removed_deletes_group_admins(db):
    """Removing bot should also clean up group_admins."""
    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        owner = _user(user_id=99999, username="owner")
        await on_my_chat_member(_member_update("administrator", added_by=owner), _context())

    assert await is_group_admin(CHAT_ID, 99999) is True

    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(_member_update("kicked"), _context())

    assert await is_group_admin(CHAT_ID, 99999) is False


@pytest.mark.asyncio
async def test_private_chat_membership_ignored(db):
    """Membership changes in private chats should be ignored."""
    private = _chat(chat_id=USER_ID, chat_type="private")
    upd = _member_update("member", chat=private)

    with patch("db.groups.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(upd, _context())

    # Private chat should NOT be registered as a group
    assert await get_group(USER_ID) is None


@pytest.mark.asyncio
async def test_bot_added_without_adder_info(db):
    """Bot added with no from_user (edge case) — group registered, no owner."""
    event = MagicMock()
    event.chat = _chat(CHAT_ID, "No Owner Group")
    event.from_user = None
    event.new_chat_member = MagicMock()
    event.new_chat_member.status = "administrator"
    upd = MagicMock()
    upd.my_chat_member = event

    with patch("db.groups.get_db", AsyncMock(return_value=db)), \
         patch("db.admins.get_db", AsyncMock(return_value=db)):
        await on_my_chat_member(upd, _context())

    group = await get_group(CHAT_ID)
    assert group is not None
    assert group["owner_id"] is None


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY NAME HELPER
# ══════════════════════════════════════════════════════════════════════════════

def test_display_name_with_username():
    user = _user(username="cooluser", first_name="Cool")
    assert _display_name(user) == "@cooluser"


def test_display_name_without_username():
    user = _user(username=None, first_name="Alice")
    assert _display_name(user) == "Alice"


def test_display_name_fallback_to_id():
    user = _user(user_id=12345, username=None, first_name=None)
    user.first_name = None
    assert _display_name(user) == "id:12345"


def test_display_name_none_user():
    assert _display_name(None) == "Unknown"
