"""
handlers/membership.py — Handle bot being added/removed from groups.

When added:   upsert the group, register the adder as owner.
When removed: delete group + group_admins records.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ChatMemberHandler

from db.groups import upsert_group, delete_group
from db.admins import add_admin

logger = logging.getLogger(__name__)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Triggered when the bot's membership status changes in a chat.
    PTB fires this for `my_chat_member` updates.
    """
    event = update.my_chat_member
    if event is None:
        return

    chat = event.chat
    # Only handle groups/supergroups
    if chat.type == "private":
        return

    new_status = event.new_chat_member.status
    added_by = event.from_user  # the user who triggered the action

    if new_status in ("member", "administrator"):
        # Bot was added or promoted
        title = chat.title or f"Chat {chat.id}"
        owner_id = added_by.id if added_by else None

        await upsert_group(chat.id, title, owner_id)
        logger.info(f"Added to group: {title} ({chat.id}) by {added_by}")

        # Register the person who added the bot as owner
        if added_by:
            await add_admin(
                chat_id=chat.id,
                user_id=added_by.id,
                username=added_by.username,
                role="owner",
                added_by=None,
            )

    elif new_status in ("left", "kicked"):
        # Bot was removed
        logger.info(f"Removed from group: {chat.title} ({chat.id})")
        await delete_group(chat.id)


def register_membership_handler(app) -> None:
    """Register the membership handler on the PTB Application."""
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
