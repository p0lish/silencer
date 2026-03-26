"""
handlers/messages.py — Group message handler for spam detection.

Rules:
  - Skip private chats
  - Skip commands (/ prefix)
  - Skip Telegram admins/creators
  - Score the message
  - Probation: new members (<24h) have stricter threshold
  - If score >= threshold: delete, restrict, record, reply
  - Auto-register unknown groups on first message
"""

import logging
from datetime import datetime, timezone

from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes, MessageHandler, filters

from db.groups import get_group, upsert_group
from db.muted import add_muted
from db.spam_log import log_spam
from detection.scorer import score_message

logger = logging.getLogger(__name__)

# ─── Probation settings ───────────────────────────────────────
PROBATION_SECONDS = 86400   # 24 hours
PROBATION_THRESHOLD = 1     # spam score threshold for new members
NORMAL_THRESHOLD = 2        # spam score threshold for established members


def _display_name(user) -> str:
    """Return a human-readable name for a Telegram user."""
    if user is None:
        return "Unknown"
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"id:{user.id}"


async def _get_chat_member(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """Fetch ChatMember object, or None on failure."""
    try:
        return await context.bot.get_chat_member(chat_id, user_id)
    except Exception:
        return None


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle every group message for spam detection."""
    msg = update.effective_message
    chat = update.effective_chat

    # Only handle groups/supergroups
    if chat is None or chat.type == "private":
        return

    # Skip commands
    if msg.text and msg.text.startswith("/"):
        return

    user = msg.from_user
    if user is None:
        return

    # Auto-register unknown groups (bot may have missed the my_chat_member event)
    group = await get_group(chat.id)
    if group is None:
        await upsert_group(chat.id, chat.title or f"Chat {chat.id}", None)
        logger.info(f"Auto-registered group {chat.id} ({chat.title})")

    # Fetch member info (reused for admin check + probation)
    member = await _get_chat_member(context, chat.id, user.id)

    # Skip Telegram admins — they can't be auto-muted
    if member and member.status in ("administrator", "creator"):
        return

    # Determine probation status
    joined_at = getattr(member, "date", None) if member else None
    if joined_at is None:
        is_new = False  # can't determine join date → treat as trusted
    else:
        is_new = (datetime.now(timezone.utc) - joined_at).total_seconds() < PROBATION_SECONDS

    threshold = PROBATION_THRESHOLD if is_new else NORMAL_THRESHOLD

    text = msg.text or msg.caption or ""
    score, hits = await score_message(text, chat.id)

    if score < threshold:
        return

    # ── Spam detected ──────────────────────────────────────────
    hit_str = " + ".join(hits)
    status = "probation" if is_new else "established"
    logger.info(f"Spam in {chat.id} from {user.id} ({status}): score={score}/{threshold}, hits={hits}")

    # Log to DB first (so we have a record even if actions fail)
    await log_spam(
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        message=text,
        pattern=hit_str,
    )

    # Delete message
    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    # Restrict user (mute)
    no_perms = ChatPermissions(
        can_send_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )
    try:
        await context.bot.restrict_chat_member(chat.id, user.id, no_perms)
        await add_muted(
            chat_id=chat.id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            reason=hit_str,
        )
        # Notify the group
        await context.bot.send_message(
            chat.id,
            f"🚫 {_display_name(user)} muted for spam ({hit_str}).",
        )
    except Exception as e:
        logger.error(f"Could not mute user {user.id} in {chat.id}: {e}")


def register_message_handler(app) -> None:
    """Register the group message handler on the PTB Application."""
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.UpdateType.MESSAGE,
            on_group_message,
        )
    )
