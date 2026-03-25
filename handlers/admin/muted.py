"""
handlers/admin/muted.py — Muted users list, unmute, and ban callbacks.

Callbacks:
  muted:<chat_id>           — list muted users
  unmute:<chat_id>:<uid>    — restore permissions
  ban:<chat_id>:<uid>       — permanently ban
"""

import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from db.admins import is_group_admin
from db.muted import get_muted, remove_muted

logger = logging.getLogger(__name__)


def _ts_to_date(ts: int) -> str:
    """Convert a Unix timestamp to an ISO date string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _user_label(row: dict) -> str:
    if row.get("username"):
        return f"@{row['username']}"
    return row.get("first_name") or f"id:{row['user_id']}"


async def muted_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all muted users in a group with unmute/ban buttons."""
    query = update.callback_query
    await query.answer()

    chat_id = int(context.matches[0].group(1))
    user_id = update.effective_user.id

    if not await is_group_admin(chat_id, user_id):
        await query.answer("Not authorized", show_alert=True)
        return

    rows = await get_muted(chat_id, limit=15)
    back_btn = [[InlineKeyboardButton("« Back", callback_data=f"group:{chat_id}")]]

    if not rows:
        await query.edit_message_text(
            "✅ No muted users.",
            reply_markup=InlineKeyboardMarkup(back_btn),
        )
        return

    lines = []
    action_buttons = []
    for r in rows:
        name = _user_label(r)
        date = _ts_to_date(r["muted_at"])
        lines.append(f"• {name} — {r['reason']} ({date})\n  ID: `{r['user_id']}`")
        action_buttons.append([
            InlineKeyboardButton(f"✅ Unmute {name}", callback_data=f"unmute:{chat_id}:{r['user_id']}"),
            InlineKeyboardButton(f"🔨 Ban {name}", callback_data=f"ban:{chat_id}:{r['user_id']}"),
        ])

    text = "*Muted users:*\n\n" + "\n\n".join(lines)
    keyboard = InlineKeyboardMarkup(action_buttons + back_btn)

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"muted_list_callback error: {e}")


async def unmute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restore a muted user's permissions."""
    query = update.callback_query

    chat_id = int(context.matches[0].group(1))
    target_uid = int(context.matches[0].group(2))

    if not await is_group_admin(chat_id, update.effective_user.id):
        await query.answer("Not authorized", show_alert=True)
        return

    try:
        from telegram import ChatPermissions
        full_perms = ChatPermissions(
            can_send_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        await context.bot.restrict_chat_member(chat_id, target_uid, full_perms)
        await remove_muted(chat_id, target_uid)
        await query.answer(f"✅ User {target_uid} unmuted")
        await query.edit_message_text(
            f"✅ User {target_uid} has been unmuted.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back to muted list", callback_data=f"muted:{chat_id}")]]
            ),
        )
    except Exception as e:
        logger.error(f"unmute_callback error: {e}")
        await query.answer(f"Failed: {e}", show_alert=True)


async def ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permanently ban a muted user."""
    query = update.callback_query

    chat_id = int(context.matches[0].group(1))
    target_uid = int(context.matches[0].group(2))

    if not await is_group_admin(chat_id, update.effective_user.id):
        await query.answer("Not authorized", show_alert=True)
        return

    try:
        await context.bot.ban_chat_member(chat_id, target_uid)
        await remove_muted(chat_id, target_uid)
        await query.answer(f"🔨 User {target_uid} banned")
        await query.edit_message_text(
            f"🔨 User {target_uid} has been banned.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back to muted list", callback_data=f"muted:{chat_id}")]]
            ),
        )
    except Exception as e:
        logger.error(f"ban_callback error: {e}")
        await query.answer(f"Failed: {e}", show_alert=True)


def register_muted_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(muted_list_callback, pattern=r"^muted:(-?\d+)$"))
    app.add_handler(CallbackQueryHandler(unmute_callback, pattern=r"^unmute:(-?\d+):(\d+)$"))
    app.add_handler(CallbackQueryHandler(ban_callback, pattern=r"^ban:(-?\d+):(\d+)$"))
