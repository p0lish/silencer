"""
handlers/admin/menu.py — /start command (private only).

Shows the main admin panel: a list of groups the user manages.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

from db.groups import get_admin_groups

logger = logging.getLogger(__name__)


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool = False,
) -> None:
    """
    Build and send (or edit) the main menu message.
    Called from /start and from the 'menu' callback.
    """
    user_id = update.effective_user.id
    groups = await get_admin_groups(user_id)

    if not groups:
        text = (
            "⛔ You are not an admin of any group this bot is in.\n\n"
            "To become an admin: add this bot to your group and promote it to administrator. "
            "You will be automatically registered as owner."
        )
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.effective_message.reply_text(text)
        return

    buttons = []
    for g in groups:
        crown = "👑" if g["role"] == "owner" else "🔑"
        buttons.append(
            [InlineKeyboardButton(f"{crown} {g['title']}", callback_data=f"group:{g['chat_id']}")]
        )

    text = "*Anti-Spam Admin Panel*\n\nYour groups (👑 owner · 🔑 admin):"
    keyboard = InlineKeyboardMarkup(buttons)

    try:
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            await update.effective_message.reply_text(
                text, parse_mode="Markdown", reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"show_main_menu error: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — only respond in private chats."""
    if update.effective_chat.type != "private":
        return
    await show_main_menu(update, context, edit=False)


def register_menu_handler(app) -> None:
    app.add_handler(CommandHandler("start", start_command))
