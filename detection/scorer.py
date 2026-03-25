"""
detection/scorer.py — Async spam scoring function.

score_message(text, chat_id) -> (score, hits[:3])

Scoring rules:
  +1  per matching pattern (built-in or group custom)
  +1  if unique emoji count > 2
  +1  if message length > 100 chars
  >=2 → spam
"""

import re
import logging
from db.patterns import get_patterns_for_group

logger = logging.getLogger(__name__)

# Unicode ranges covering most emoji
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF"   # Misc symbols, emoticons, transport, etc.
    "\U00002600-\U000027BF"    # Misc symbols (sun, stars, etc.)
    "\U0001FA00-\U0001FA6F"    # Chess, symbols
    "\U0001FA70-\U0001FAFF"    # Symbols and pictographs extended-A
    "\U00002702-\U000027B0"    # Dingbats
    "\U000024C2-\U0001F251"    # Enclosed chars + transport
    "]",
    re.UNICODE,
)


def _count_unique_emoji(text: str) -> int:
    """Return the number of distinct emoji characters in text."""
    return len(set(_EMOJI_RE.findall(text)))


def _safe_compile(pattern: str, is_regex: int) -> re.Pattern | None:
    """
    Compile a pattern safely.
    - If is_regex=0, the pattern is treated as a literal keyword (escaped).
    - Returns None on compilation error (e.g. malformed regex).
    """
    try:
        if is_regex:
            return re.compile(pattern, re.IGNORECASE | re.DOTALL)
        else:
            return re.compile(re.escape(pattern), re.IGNORECASE)
    except re.error as e:
        logger.debug(f"Skipping bad pattern '{pattern}': {e}")
        return None


async def score_message(text: str, chat_id: int) -> tuple[int, list[str]]:
    """
    Score a message for spam signals.

    Returns:
        (score, hits) where hits is a list of matched labels (up to 3).
        Returns (0, []) for messages shorter than 20 chars.
    """
    if len(text) < 20:
        return 0, []

    score = 0
    hits: list[str] = []

    # Load all patterns (global built-ins + group custom)
    try:
        patterns = await get_patterns_for_group(chat_id)
    except Exception as e:
        logger.error(f"Failed to load patterns for chat {chat_id}: {e}")
        patterns = []

    for row in patterns:
        compiled = _safe_compile(row["pattern"], row["is_regex"])
        if compiled is None:
            continue
        if compiled.search(text):
            score += 1
            label = row["label"]
            if not row.get("is_builtin"):
                label = f"custom: {label}"
            hits.append(label)

    # Emoji density signal
    unique_emoji = _count_unique_emoji(text)
    if unique_emoji > 2:
        score += 1
        hits.append(f"{unique_emoji} emojis")

    # Long message signal (spammers pad for context)
    if len(text) > 100:
        score += 1
        hits.append("long message")

    return score, hits[:3]
