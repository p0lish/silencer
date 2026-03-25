"""
handlers/admin/spam_log.py — Spam log viewer callback.

Callback:
  spamlog:<chat_id>  — show recent spam events
"""

import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from db.admins import is_group_admin
from db.spam_log import get_spam_log

logger = logging.getLogger(__name__)


async def spam_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display recent spam log entries for a group."""
    query = update.callback_query
    await query.answer()

    chat_id = int(context.matches[0].group(1))
    user_id = update.effective_user.id

    if not await is_group_admin(chat_id, user_id):
        await query.answer("Not authorized", show_alert=True)
        return

    rows = await get_spam_log(chat_id, limit=10)
    back_btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Back", callback_data=f"group:{chat_id}")]]
    )

    if not rows:
        await query.edit_message_text("No spam logged yet.", reply_markup=back_btn)
        return

    lines = []
    for i, r in enumerate(rows, start=1):
        name = f"@{r['username']}" if r.get("username") else f"id:{r['user_id']}"
        ts = datetime.fromtimestamp(r["logged_at"], tz=timezone.utc).strftime("%H:%M")
        preview = (r["message"] or "")[:50].replace("\n", " ")
        lines.append(f"{i}. [{ts}] {name} ({r['pattern']})\n   \"{preview}\"")

    text = "*Recent spam:*\n\n" + "\n\n".join(lines)

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_btn)
    except Exception as e:
        logger.error(f"spam_log_callback error: {e}")


def register_spam_log_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(spam_log_callback, pattern=r"^spamlog:(-?\d+)$"))
