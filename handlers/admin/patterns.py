"""
handlers/admin/patterns.py — Custom pattern management for a group.

Callbacks:
  patterns:<chat_id>           — list custom patterns
  addpat:<chat_id>:keyword     — start add-keyword flow
  addpat:<chat_id>:regex       — start add-regex flow
  delpat:<chat_id>:<pid>       — delete pattern by id

Pending flows (handled via MessageHandler in private chat):
  Step 1 (action=addpat):       user sends the pattern text
  Step 2 (action=addpat_label): user sends the label
"""

import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

from db.admins import is_group_admin
from db.groups import get_group
from db.patterns import get_custom_patterns, add_pattern, delete_pattern
from db.pending_state import set_pending, get_pending, clear_pending

logger = logging.getLogger(__name__)

# ReDoS guard — patterns that indicate catastrophic backtracking risk
_REDOS_GUARDS = [
    re.compile(r"\(\?=.*\*"),
    re.compile(r"\(\?!.*\*"),
    re.compile(r"\([^)]*\+\)[+*]"),
    re.compile(r"\([^)]*\*\)[+*]"),
    re.compile(r"(\.\*){2}"),
    re.compile(r"(\.\+){2}"),
]

# Pure wildcard patterns that would match everything
_WILDCARD_RE = re.compile(r"^\.\*$|^\.\+$|^\.\{0,\d+\}$")


async def _show_patterns(
    chat_id: int,
    query,
    edit: bool = True,
) -> None:
    """Render the patterns panel."""
    rows = await get_custom_patterns(chat_id)
    group = await get_group(chat_id)
    title = group["title"] if group else str(chat_id)

    header_lines = [
        f"*Custom Patterns — {title}* ({len(rows)})\n",
        "Built-in: crypto/nft, fake job, investment scam, scam links",
        "⚖️ Score ≥ 2 to trigger (patterns + emojis >2 + length >100)",
        "📏 Messages under 20 chars never checked\n",
    ]
    if rows:
        for i, r in enumerate(rows, 1):
            regex_tag = " *(regex)*" if r["is_regex"] else ""
            header_lines.append(f"{i}. `{r['pattern']}` — {r['label']}{regex_tag}")
    else:
        header_lines.append("_No custom patterns yet_")

    header = "\n".join(header_lines)

    delete_buttons = [
        [InlineKeyboardButton(f"🗑 {r['label']}", callback_data=f"delpat:{chat_id}:{r['id']}")]
        for r in rows
    ]
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add keyword", callback_data=f"addpat:{chat_id}:keyword"),
                InlineKeyboardButton("➕ Add regex", callback_data=f"addpat:{chat_id}:regex"),
            ],
            *delete_buttons,
            [InlineKeyboardButton("« Back", callback_data=f"group:{chat_id}")],
        ]
    )

    try:
        if edit:
            await query.edit_message_text(header, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await query.message.reply_text(header, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"_show_patterns error: {e}")


async def patterns_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the patterns panel."""
    query = update.callback_query
    await query.answer()

    chat_id = int(context.matches[0].group(1))
    if not await is_group_admin(chat_id, update.effective_user.id):
        await query.answer("Not authorized", show_alert=True)
        return

    await _show_patterns(chat_id, query, edit=True)


async def addpat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initiate the add-pattern flow (step 1)."""
    query = update.callback_query
    await query.answer()

    chat_id = int(context.matches[0].group(1))
    pat_type = context.matches[0].group(2)  # 'keyword' or 'regex'

    if not await is_group_admin(chat_id, update.effective_user.id):
        await query.answer("Not authorized", show_alert=True)
        return

    await set_pending(update.effective_user.id, "addpat", {"chat_id": chat_id, "type": pat_type})

    if pat_type == "keyword":
        prompt = (
            "✏️ Send the keyword or phrase to block:\n\n"
            "Example: `free gift` or `dm me for details`"
        )
    else:
        prompt = (
            "✏️ Send the regex pattern to block:\n\n"
            "Example: `earn \\d+.{0,5}per (day|week)`"
        )

    await query.message.reply_text(prompt, parse_mode="Markdown")


async def delpat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a custom pattern."""
    query = update.callback_query

    chat_id = int(context.matches[0].group(1))
    pattern_id = int(context.matches[0].group(2))

    if not await is_group_admin(chat_id, update.effective_user.id):
        await query.answer("Not authorized", show_alert=True)
        return

    deleted = await delete_pattern(pattern_id, chat_id)
    if deleted:
        await query.answer("🗑 Pattern deleted")
    else:
        await query.answer("Not found", show_alert=True)

    await _show_patterns(chat_id, query, edit=True)


async def pattern_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle free-text input for add-pattern flow (private chat only).
    Step 1: receive pattern → ask for label
    Step 2: receive label → save pattern
    """
    if update.effective_chat.type != "private":
        return

    msg = update.effective_message
    if not msg or not msg.text:
        return

    user_id = update.effective_user.id
    pending = await get_pending(user_id)

    if not pending or pending["action"] not in ("addpat", "addpat_label"):
        return

    await clear_pending(user_id)
    text = msg.text.strip()

    # ── Step 1: got the pattern ───────────────────────────────
    if pending["action"] == "addpat":
        chat_id = pending["chat_id"]
        pat_type = pending["type"]

        if pat_type == "regex":
            # Validate compiles
            try:
                re.compile(text, re.IGNORECASE)
            except re.error:
                await msg.reply_text("❌ Invalid regex. Try again from the patterns panel.")
                return

            # ReDoS guard
            if any(g.search(text) for g in _REDOS_GUARDS):
                await msg.reply_text(
                    "❌ Pattern looks potentially dangerous (catastrophic backtracking risk). "
                    "Use a simpler expression."
                )
                return

            # Pure wildcard rejection
            if _WILDCARD_RE.match(text.strip()):
                await msg.reply_text(
                    "❌ Wildcard-only patterns would match everything and mute all users. "
                    "Be more specific."
                )
                return
        else:
            # Keyword — minimum 3 characters
            if len(text) < 3:
                await msg.reply_text("❌ Keyword too short (minimum 3 characters).")
                return

        # Move to step 2
        await set_pending(
            user_id,
            "addpat_label",
            {"chat_id": chat_id, "pattern": text, "type": pat_type},
        )
        await msg.reply_text(
            f"Pattern: `{text}`\n\nNow send a short label (e.g. \"fake job\"):",
            parse_mode="Markdown",
        )
        return

    # ── Step 2: got the label ─────────────────────────────────
    if pending["action"] == "addpat_label":
        chat_id = pending["chat_id"]
        pattern = pending["pattern"]
        pat_type = pending["type"]
        label = text[:50]

        try:
            await add_pattern(
                chat_id=chat_id,
                pattern=pattern,
                label=label,
                is_regex=1 if pat_type == "regex" else 0,
                is_builtin=0,
                added_by=user_id,
            )
            await msg.reply_text(
                f"✅ Pattern added!\n\nPattern: `{pattern}`\nLabel: {label}\nType: {pat_type}",
                parse_mode="Markdown",
            )
        except Exception as e:
            if "UNIQUE" in str(e):
                await msg.reply_text("⚠️ That pattern already exists in this group.")
            else:
                await msg.reply_text(f"Error: {e}")
            return

        # Re-show patterns panel
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        rows = await get_custom_patterns(chat_id)
        group = await get_group(chat_id)
        title = group["title"] if group else str(chat_id)
        lines = [f"*Custom Patterns — {title}* ({len(rows)})\n"]
        for i, r in enumerate(rows, 1):
            rtag = " *(regex)*" if r["is_regex"] else ""
            lines.append(f"{i}. `{r['pattern']}` — {r['label']}{rtag}")
        delete_buttons = [
            [InlineKeyboardButton(f"🗑 {r['label']}", callback_data=f"delpat:{chat_id}:{r['id']}")]
            for r in rows
        ]
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("➕ Add keyword", callback_data=f"addpat:{chat_id}:keyword"),
                    InlineKeyboardButton("➕ Add regex", callback_data=f"addpat:{chat_id}:regex"),
                ],
                *delete_buttons,
                [InlineKeyboardButton("« Back", callback_data=f"group:{chat_id}")],
            ]
        )
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


def register_patterns_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(patterns_callback, pattern=r"^patterns:(-?\d+)$"))
    app.add_handler(CallbackQueryHandler(addpat_callback, pattern=r"^addpat:(-?\d+):(keyword|regex)$"))
    app.add_handler(CallbackQueryHandler(delpat_callback, pattern=r"^delpat:(-?\d+):(\d+)$"))
    # Text input handler — must be low priority so spam detection runs first
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, pattern_input_handler),
        group=10,
    )
