"""
detection/rules.py — Seed built-in spam patterns into the DB on startup.

Patterns are inserted as global rows (chat_id=NULL, is_builtin=1).
INSERT OR IGNORE ensures idempotency — safe to call every boot.
"""

import logging
import time
from db.connection import get_db

logger = logging.getLogger(__name__)

# Built-in patterns: (pattern, label, is_regex)
BUILTIN_PATTERNS = [
    (
        r"\b(airdrop|crypto (signal|project|group|trading)|nft (mint|drop|project)|defi (earn|invest|pool)|token sale|presale)\b",
        "crypto scam",
        1,
    ),
    (
        r"\b(binance|usdt|btc).{0,30}(earn|profit|invest|send|transfer)",
        "crypto scam",
        1,
    ),
    (
        r"\b(passive income|guaranteed (profit|return|income)|trading (signal|bot|group)|double your (money|investment)|roi)\b",
        "investment scam",
        1,
    ),
    (
        r"\b(earn|make|earnings?)\s+\$\d+|\$\d+[\s\S]{0,15}per\s+(day|week|month|hour)",
        "investment scam",
        1,
    ),
    (
        r"\b(work from home|work at home|only (a |your )?(phone|smartphone|laptop))\b",
        "fake job",
        1,
    ),
    (
        r"\b(no experience (needed|required)|daily (income|earnings|profit))\b",
        "fake job",
        1,
    ),
    (
        r"\b(urgent (hiring|vacancy)|dm me (for|to) (details|apply)|limited (slots|spots|positions))\b",
        "fake job",
        1,
    ),
    (
        r"\b(part.?time|full.?time).{0,30}(earn|income|\$\d+)",
        "fake job",
        1,
    ),
    (
        r"\b(click (here|link|below)|join (now|today)|free (money|gift|prize|reward))\b",
        "scam link",
        1,
    ),
    (
        r"t\.me\/[a-z0-9_+]+",
        "telegram link",
        1,
    ),
    (
        r"https?:\/\/(?!t\.me\/)[a-z0-9-]+\.(xyz|top|click|ru|cn|tk|pw|cc|icu)",
        "suspicious domain",
        1,
    ),
]


async def seed_builtin_rules() -> None:
    """Insert built-in patterns if they don't exist yet. Idempotent."""
    db = await get_db()
    now = int(time.time())
    inserted = 0

    for pattern, label, is_regex in BUILTIN_PATTERNS:
        try:
            # SQLite treats NULL != NULL in UNIQUE constraints, so
            # INSERT OR IGNORE won't prevent duplicates for global patterns.
            # Explicitly check existence before inserting.
            async with db.execute(
                "SELECT 1 FROM custom_patterns WHERE chat_id IS NULL AND pattern = ?",
                (pattern,),
            ) as cur:
                exists = await cur.fetchone()

            if not exists:
                await db.execute(
                    """
                    INSERT INTO custom_patterns
                        (chat_id, pattern, label, is_regex, is_builtin, added_by, added_at)
                    VALUES (NULL, ?, ?, ?, 1, NULL, ?)
                    """,
                    (pattern, label, is_regex, now),
                )
                inserted += 1
        except Exception as e:
            logger.warning(f"Failed to seed pattern '{label}': {e}")

    await db.commit()
    if inserted:
        logger.info(f"Seeded {inserted} built-in spam pattern(s).")
    else:
        logger.info("Built-in patterns already present — skipping seed.")
