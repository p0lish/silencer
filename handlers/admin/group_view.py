"""
handlers/admin/group_view.py — Group detail view and back-to-menu callbacks.

Callbacks:
  group:<chat_id>  — show group stats + action buttons
  menu             — return to main menu
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from db.admins import is_group_admin, is_group_owner
from db.groups import get_group
from db.muted import count_muted
from db.spam_log import count_spam
from db.patterns import count_custom_patterns
from handlers.admin.menu import show_main_menu

logger = logging.getLogger(__name__)


async def group_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show stats + action buttons for a specific group."""
    query = update.callback_query
    await query.answer()

    chat_id = int(context.matches[0].group(1))
    user_id = update.effective_user.id

    if not await is_group_admin(chat_id, user_id):
        await query.answer("Not authorized", show_alert=True)
        return

    group = await get_group(chat_id)
    muted_count = await count_muted(chat_id)
    spam_count = await count_spam(chat_id)
    pattern_count = await count_custom_patterns(chat_id)
    owner = await is_group_owner(chat_id, user_id)

    title = group["title"] if group else str(chat_id)

    # Check if the bot itself has admin rights in the group
    bot_is_admin = False
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        bot_is_admin = bot_member.status in ("administrator", "creator")
    except Exception:
        pass

    warning = "" if bot_is_admin else "\n\n⚠️ *Bot is not an admin* — promote it to enable spam deletion and muting."

    buttons = [
        [InlineKeyboardButton(f"🔇 Muted users ({muted_count})", callback_data=f"muted:{chat_id}")],
        [InlineKeyboardButton(f"📋 Spam log ({spam_count})", callback_data=f"spamlog:{chat_id}")],
        [InlineKeyboardButton(f"🧩 Patterns ({pattern_count} custom)", callback_data=f"patterns:{chat_id}")],
    ]
    if owner:
        buttons.append([InlineKeyboardButton("👥 Manage admins", callback_data=f"admins:{chat_id}")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu")])

    text = (
        f"*{title}*\n\n"
        f"🔇 Muted: {muted_count}  "
        f"🗂 Spam caught: {spam_count}  "
        f"🧩 Custom patterns: {pattern_count}"
        f"{warning}"
    )

    try:
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"group_view_callback error: {e}")


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to the main admin menu."""
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context, edit=True)


def register_group_view_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(group_view_callback, pattern=r"^group:(-?\d+)$"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu$"))
