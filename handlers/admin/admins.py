"""
Admin management handler — owners only.
Callbacks: admins:<chat_id>, addadmin:<chat_id>, removeadmin:<chat_id>:<user_id>
Pending flow: addadmin (1 step: user ID input)
"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

from db.admins import is_group_owner, get_group_admins, add_admin, remove_admin
from db.groups import get_group
from db.pending_state import get_pending, set_pending, clear_pending

logger = logging.getLogger(__name__)


def _back_button(chat_id: int) -> list:
    return [InlineKeyboardButton("« Back", callback_data=f"group:{chat_id}")]


async def show_admins(update: Update, chat_id: int, edit: bool = True) -> None:
    admins = await get_group_admins(chat_id)
    group = await get_group(chat_id)
    group_title = group["title"] if group else str(chat_id)

    if admins:
        lines = []
        for a in admins:
            crown = "👑" if a["role"] == "owner" else "🔑"
            name = f"@{a['username']}" if a["username"] else f"id:{a['user_id']}"
            lines.append(f"{crown} {name} ({a['user_id']})")
        text = f"*Admins — {group_title}*\n\n" + "\n".join(lines)
    else:
        text = f"*Admins — {group_title}*\n\n_No admins found._"

    # Remove buttons for self to avoid accidental self-removal
    caller_id = update.effective_user.id
    remove_buttons = [
        [InlineKeyboardButton(
            f"🗑 Remove @{a['username'] or a['user_id']}",
            callback_data=f"removeadmin:{chat_id}:{a['user_id']}"
        )]
        for a in admins if a["user_id"] != caller_id
    ]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add admin", callback_data=f"addadmin:{chat_id}")],
        *remove_buttons,
        [_back_button(chat_id)[0]],
    ])

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = int(context.matches[0].group(1))

    if not await is_group_owner(chat_id, query.from_user.id):
        await query.answer("Owners only.")
        return

    await query.answer()
    await show_admins(update, chat_id)


async def addadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = int(context.matches[0].group(1))

    if not await is_group_owner(chat_id, query.from_user.id):
        await query.answer("Owners only.")
        return

    await set_pending(query.from_user.id, "addadmin", {"chat_id": chat_id})
    await query.answer()
    await query.message.reply_text(
        "✏️ Send the Telegram *user ID* of the new admin:\n\n"
        "They can get their ID by messaging @userinfobot\n\n"
        "Format: just the number, e.g. `123456789`",
        parse_mode="Markdown"
    )


async def removeadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = int(context.matches[0].group(1))
    user_id = int(context.matches[0].group(2))

    if not await is_group_owner(chat_id, query.from_user.id):
        await query.answer("Owners only.")
        return

    await remove_admin(chat_id, user_id)
    await query.answer(f"🗑 Admin {user_id} removed.")
    await show_admins(update, chat_id)


async def addadmin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input for the addadmin pending flow."""
    user_id = update.effective_user.id
    pending = await get_pending(user_id)

    if not pending or pending.get("action") != "addadmin":
        return

    text = update.message.text.strip() if update.message.text else ""
    chat_id = pending["chat_id"]

    try:
        new_user_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid user ID — must be a number. Try again from the admin panel."
        )
        await clear_pending(user_id)
        return

    await clear_pending(user_id)

    try:
        await add_admin(chat_id, new_user_id, None, "admin", user_id)
        await update.message.reply_text(
            f"✅ User `{new_user_id}` added as admin.\n\n"
            "They can now manage this group by sending /start to the bot.",
            parse_mode="Markdown"
        )
        await show_admins(update, chat_id, edit=False)
    except Exception as e:
        if "UNIQUE" in str(e):
            await update.message.reply_text("⚠️ That user is already an admin of this group.")
        else:
            logger.error("addadmin error: %s", e)
            await update.message.reply_text(f"❌ Error: {e}")


def register_admins_handlers(app) -> None:
    import re
    from telegram.ext import MessageHandler, filters
    app.add_handler(CallbackQueryHandler(admins_callback, pattern=re.compile(r"^admins:(-?\d+)$")))
    app.add_handler(CallbackQueryHandler(addadmin_callback, pattern=re.compile(r"^addadmin:(-?\d+)$")))
    app.add_handler(CallbackQueryHandler(removeadmin_callback, pattern=re.compile(r"^removeadmin:(-?\d+):(\d+)$")))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, addadmin_message_handler))
