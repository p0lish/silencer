#!/usr/bin/env python3
"""
Anti-Spam Bot — Python edition
Entry point: initialises DB, seeds rules, registers handlers, starts polling.
"""

import asyncio
import logging

from telegram.ext import Application

import config
from db.connection import get_db, close_db
from db.migrations import run_migrations
from db.pending_state import cleanup_old
from detection.rules import seed_builtin_rules
from handlers.membership import register as register_membership
from handlers.messages import register as register_messages
from handlers.admin import register_admin_handlers

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Run after the Application is built but before polling starts."""
    logger.info("Initialising database...")
    await run_migrations()
    await seed_builtin_rules()
    await cleanup_old()
    logger.info("Database ready.")


async def post_shutdown(application: Application) -> None:
    """Clean up DB connection on shutdown."""
    await close_db()
    logger.info("Database connection closed.")


def main() -> None:
    token = config.BOT_TOKEN

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register handlers — order matters
    register_membership(app)   # my_chat_member: group register/remove
    register_messages(app)     # group spam detection + auto-register
    register_admin_handlers(app)  # DM panel: /start + all callbacks + pending flows

    logger.info("Bot starting (multi-tenant Python edition)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
