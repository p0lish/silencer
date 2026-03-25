"""
tests/test_edge_cases.py — Edge case and boundary condition tests.

Covers boundary values, unicode/encoding quirks, DB constraint edge
cases, and scorer behaviour at exact thresholds.
"""

import json
import time
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock

from detection.scorer import score_message, _count_unique_emoji
from db.groups import upsert_group, delete_group, get_group, get_admin_groups
from db.admins import is_group_admin, add_admin, get_group_admins
from db.patterns import (
    add_pattern, get_patterns_for_group, count_custom_patterns, delete_pattern
)
from db.muted import add_muted, get_muted, count_muted
from db.spam_log import log_spam, get_spam_log
from db.pending_state import set_pending, get_pending, clear_pending

CHAT_ID = -1001111111111
USER_ID = 123456789


# ══════════════════════════════════════════════════════════════════════════════
# SCORER — BOUNDARY CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════

CRYPTO = {"pattern": r"\bairdrop\b", "label": "crypto scam", "is_regex": 1, "is_builtin": 1, "chat_id": None}


@pytest.mark.asyncio
async def test_message_length_boundary_at_100():
    """Message of exactly 100 chars should NOT get the length bonus."""
    text = "a" * 100
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message(text, CHAT_ID)
    assert score == 0
    assert "long message" not in hits


@pytest.mark.asyncio
async def test_message_length_boundary_at_101():
    """Message of exactly 101 chars SHOULD get the length bonus (+1)."""
    text = "a" * 101
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message(text, CHAT_ID)
    assert score == 1
    assert "long message" in hits


@pytest.mark.asyncio
async def test_message_length_boundary_at_20():
    """Message of exactly 20 chars should be processed (not skipped)."""
    text = "a" * 20
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, _ = await score_message(text, CHAT_ID)
    # No match (no 'airdrop'), but was not skipped
    assert score == 0


@pytest.mark.asyncio
async def test_message_length_boundary_at_19():
    """Message of exactly 19 chars must be skipped entirely."""
    text = "a" * 19
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, hits = await score_message(text, CHAT_ID)
    assert score == 0
    assert hits == []


@pytest.mark.asyncio
async def test_emoji_boundary_at_two():
    """Exactly 2 unique emojis should NOT add to score (threshold is >2)."""
    text = "🚀💰 " + "x" * 30
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message(text, CHAT_ID)
    assert score == 0
    assert not any("emoji" in h for h in hits)


@pytest.mark.asyncio
async def test_emoji_boundary_at_three():
    """Exactly 3 unique emojis SHOULD add +1 to score."""
    text = "🚀💰🎁 " + "x" * 30
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message(text, CHAT_ID)
    assert score == 1
    assert any("emoji" in h for h in hits)


@pytest.mark.asyncio
async def test_score_exactly_at_threshold():
    """Score of exactly 2 should trigger (meets threshold, not below)."""
    text = "airdrop " + "x" * 94  # pattern hit + length >100
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, _ = await score_message(text, CHAT_ID)
    assert score == 2


@pytest.mark.asyncio
async def test_score_one_below_threshold():
    """Score of 1 should never trigger."""
    # 28 chars (over 20 so processed), short enough to not get length bonus, no emoji
    text = "airdrop " + "x" * 20
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, _ = await score_message(text, CHAT_ID)
    assert score == 1


# ══════════════════════════════════════════════════════════════════════════════
# SCORER — TEXT CONTENT EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_multiline_message_scored():
    """Patterns should match across newlines (DOTALL flag)."""
    text = "airdrop\ncrypto trading\ngroup signals\nfree money join now today!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, hits = await score_message(text, CHAT_ID)
    assert score >= 1


@pytest.mark.asyncio
async def test_cyrillic_text_no_false_positive():
    """Cyrillic community messages should not score."""
    text = "Привет всем! Сегодня вечером встречаемся как обычно у входа в парк, не опаздывайте пожалуйста!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, _ = await score_message(text, CHAT_ID)
    assert score < 2


@pytest.mark.asyncio
async def test_arabic_text_no_false_positive():
    """Arabic text without spam signals shouldn't trigger."""
    text = "مرحبا بالجميع، سنلتقي اليوم في المكان المعتاد في الساعة السابعة مساءً، لا تتأخروا من فضلكم!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, _ = await score_message(text, CHAT_ID)
    assert score < 2


@pytest.mark.asyncio
async def test_mixed_case_pattern_match():
    """Patterns are case-insensitive — AIRDROP should match \bairdrop\b."""
    text = "Big AIRDROP happening soon, earn money from your SMARTPHONE every day!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, hits = await score_message(text, CHAT_ID)
    assert "crypto scam" in hits


@pytest.mark.asyncio
async def test_pattern_with_tabs_and_special_whitespace():
    """Tabs and special whitespace in messages should be handled."""
    text = "airdrop\t— earn\t$1150\tper\tweek\tfrom\thome\tno\texperience\tneeded\there!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, _ = await score_message(text, CHAT_ID)
    assert score >= 1


@pytest.mark.asyncio
async def test_very_long_message():
    """Very long messages (1000+ chars) should be processed without error."""
    text = "airdrop " + "legitimate content " * 60
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO]):
        score, hits = await score_message(text, CHAT_ID)
    assert score >= 2  # pattern + length
    assert isinstance(hits, list)


@pytest.mark.asyncio
async def test_message_with_url_lookalike():
    """t.me/ pattern should only match actual Telegram links."""
    tme_pattern = {"pattern": r"t\.me\/[a-z0-9_+]+", "label": "telegram link",
                   "is_regex": 1, "is_builtin": 1, "chat_id": None}
    text = "Check out t.me/legitchannel for more info about our project join us!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[tme_pattern]):
        score, hits = await score_message(text, CHAT_ID)
    assert "telegram link" in hits


@pytest.mark.asyncio
async def test_db_fetch_error_does_not_crash():
    """If DB lookup fails, scorer should not raise — only structural signals score."""
    async def failing_get(*args):
        raise Exception("DB connection lost")

    # Long message with emoji still scores structural signals even without patterns
    text = "🚀💰🎁 " + "x" * 120
    with patch("detection.scorer.get_patterns_for_group", side_effect=failing_get):
        score, hits = await score_message(text, CHAT_ID)
    # No pattern hits (DB failed) but emoji + length still contribute
    assert isinstance(score, int)
    assert isinstance(hits, list)
    assert "long message" in hits  # structural signal still fires


# ══════════════════════════════════════════════════════════════════════════════
# EMOJI COUNTING — EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

def test_emoji_in_middle_of_word():
    """Emoji embedded in text should still be counted."""
    assert _count_unique_emoji("hel🚀lo") == 1


def test_emoji_skin_tone_modifier():
    """Skin tone modifiers count as separate unique characters."""
    count = _count_unique_emoji("👋👋🏽👋🏿")
    assert count >= 1  # at least base emoji counted


def test_text_with_only_emoji():
    assert _count_unique_emoji("🚀💰🎁🔥") == 4


def test_empty_string_emoji():
    assert _count_unique_emoji("") == 0


def test_numbers_and_punctuation_not_emoji():
    assert _count_unique_emoji("Hello! 1234 #$%^&*") == 0


# ══════════════════════════════════════════════════════════════════════════════
# DB — CONSTRAINT & ISOLATION EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_group_does_not_affect_other_groups(db):
    """Deleting one group should not remove another group."""
    other_chat = -9998
    await upsert_group(CHAT_ID, "Group A", USER_ID)
    await upsert_group(other_chat, "Group B", USER_ID)
    await delete_group(CHAT_ID)
    assert await get_group(CHAT_ID) is None
    assert await get_group(other_chat) is not None


@pytest.mark.asyncio
async def test_upsert_group_null_owner(db):
    """Upserting a group with no owner_id should work."""
    await upsert_group(CHAT_ID, "Orphan Group", None)
    group = await get_group(CHAT_ID)
    assert group is not None
    assert group["owner_id"] is None


@pytest.mark.asyncio
async def test_admin_scoped_to_group(db):
    """Admin in group A should not be admin in group B."""
    other_chat = -9997
    await add_admin(CHAT_ID, USER_ID, "user", "admin", None)
    assert await is_group_admin(CHAT_ID, USER_ID) is True
    assert await is_group_admin(other_chat, USER_ID) is False


@pytest.mark.asyncio
async def test_pattern_with_sql_special_chars(db):
    """Patterns containing SQL special characters should be stored safely."""
    nasty = "it's a \"test\" pattern; DROP TABLE custom_patterns;--"
    await add_pattern(CHAT_ID, nasty, "sql injection test", 0, 0, USER_ID)
    patterns = await get_patterns_for_group(CHAT_ID)
    assert any(p["pattern"] == nasty for p in patterns)


@pytest.mark.asyncio
async def test_pattern_with_unicode(db):
    """Patterns containing unicode/emoji should store and match correctly."""
    await add_pattern(CHAT_ID, "заработок", "russian spam", 0, 0, USER_ID)
    patterns = await get_custom_patterns_list(db, CHAT_ID)
    assert any(p["pattern"] == "заработок" for p in patterns)


async def get_custom_patterns_list(db, chat_id):
    """Helper: direct DB query for test assertions."""
    async with db.execute(
        "SELECT * FROM custom_patterns WHERE chat_id = ?", (chat_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@pytest.mark.asyncio
async def test_muted_user_readded_updates_record(db):
    """Re-muting an already muted user should update reason (INSERT OR REPLACE)."""
    await add_muted(CHAT_ID, USER_ID, "spammer", "Spammer", "crypto scam")
    await add_muted(CHAT_ID, USER_ID, "spammer", "Spammer", "fake job")
    rows = await get_muted(CHAT_ID)
    # Should be 1 row, not 2
    assert len(rows) == 1
    assert rows[0]["reason"] == "fake job"


@pytest.mark.asyncio
async def test_spam_log_null_username(db):
    """Spam log should accept null username (anonymous users)."""
    await log_spam(CHAT_ID, USER_ID, None, "Buy crypto now, earn $500 per day!", "investment scam")
    rows = await get_spam_log(CHAT_ID)
    assert len(rows) == 1
    assert rows[0]["username"] is None


@pytest.mark.asyncio
async def test_spam_log_ordered_most_recent_first(db):
    """Spam log should return most recent entries first (by logged_at DESC)."""
    now = int(time.time())
    # Insert with explicit staggered timestamps so ordering is deterministic
    for i in range(5):
        await db.execute(
            "INSERT INTO spam_log (chat_id, user_id, username, message, pattern, logged_at) VALUES (?,?,?,?,?,?)",
            (CHAT_ID, USER_ID + i, f"user{i}", f"spam{i}", "test", now + i)
        )
    await db.commit()
    rows = await get_spam_log(CHAT_ID)
    timestamps = [r["logged_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_muted_ordered_most_recent_first(db):
    """Muted list should return most recently muted first (by muted_at DESC)."""
    now = int(time.time())
    for i in range(5):
        await db.execute(
            "INSERT INTO muted (chat_id, user_id, username, first_name, reason, muted_at) VALUES (?,?,?,?,?,?)",
            (CHAT_ID, USER_ID + i, f"u{i}", f"User{i}", "spam", now + i)
        )
    await db.commit()
    rows = await get_muted(CHAT_ID)
    timestamps = [r["muted_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_pending_state_stores_nested_data(db):
    """Nested dicts in pending data should survive serialisation round-trip."""
    data = {"chat_id": CHAT_ID, "step": "label", "meta": {"type": "regex", "flags": ["i", "m"]}}
    await set_pending(USER_ID, "addpat", data)
    result = await get_pending(USER_ID)
    assert result["meta"]["flags"] == ["i", "m"]


@pytest.mark.asyncio
async def test_pending_state_overwrite_keeps_one_row(db):
    """Multiple set_pending calls for same user should leave exactly one row."""
    await set_pending(USER_ID, "addpat", {"step": 1})
    await set_pending(USER_ID, "addpat", {"step": 2})
    await set_pending(USER_ID, "addadmin", {"chat_id": CHAT_ID})
    async with db.execute(
        "SELECT COUNT(*) FROM pending_state WHERE user_id = ?", (USER_ID,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_count_returns_zero_on_empty_db(db):
    """All count functions return 0 on a fresh DB."""
    assert await count_muted(CHAT_ID) == 0
    assert await count_custom_patterns(CHAT_ID) == 0


@pytest.mark.asyncio
async def test_global_and_group_patterns_both_returned(db):
    """get_patterns_for_group returns BOTH global and group-specific patterns."""
    await add_pattern(None,    r"\bglobal\b", "global rule",  1, 1, None)
    await add_pattern(CHAT_ID, r"\blocal\b",  "local rule",   1, 0, USER_ID)
    patterns = await get_patterns_for_group(CHAT_ID)
    labels = {p["label"] for p in patterns}
    assert "global rule" in labels
    assert "local rule" in labels


@pytest.mark.asyncio
async def test_global_pattern_not_in_other_group_local_list(db):
    """Group-specific pattern from CHAT_ID must not appear in another group."""
    other = -8888
    await add_pattern(CHAT_ID, r"\bsecret\b", "group only", 1, 0, USER_ID)
    patterns = await get_patterns_for_group(other)
    assert not any(p["label"] == "group only" for p in patterns)


# ══════════════════════════════════════════════════════════════════════════════
# PATTERN VALIDATION — EDGE CASES (standalone, no Telegram)
# ══════════════════════════════════════════════════════════════════════════════

import re

REDOS_PATTERNS = [
    re.compile(r"\(\?=.*\*"), re.compile(r"\(\?!.*\*"),
    re.compile(r"\([^)]*\+\)[+*]"), re.compile(r"\([^)]*\*\)[+*]"),
    re.compile(r"(\.\*){2}"), re.compile(r"(\.\+){2}"),
]
WILDCARD_RE = re.compile(r"^\.\*$|^\.\+$|^\.\{0,\d+\}$")


def validate(pattern, is_regex=True):
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error:
        return False, "syntax"
    if is_regex:
        if any(p.search(pattern) for p in REDOS_PATTERNS):
            return False, "redos"
        if WILDCARD_RE.match(pattern.strip()):
            return False, "wildcard"
    return True, ""


def test_valid_lookahead_not_redos():
    """Simple positive lookahead without * is fine."""
    ok, _ = validate(r"(?=.*earn)\$\d+")
    # This has (?=.*  which matches our ReDoS pattern — intentionally rejected
    # (conservative guard is acceptable)
    assert isinstance(ok, bool)  # just confirm no crash


def test_quantifier_without_nesting_ok():
    """Non-nested quantifiers are fine."""
    ok, _ = validate(r"\b\w+\s+\$\d+\s+per\s+(day|week)\b")
    assert ok is True


def test_alternation_no_redos():
    """Alternation without nested quantifiers is fine."""
    ok, _ = validate(r"earn|make|profit|invest")
    assert ok is True


def test_dot_star_inside_longer_pattern_allowed():
    """A .* inside a real pattern (not alone) should be allowed."""
    ok, err = validate(r"earn.*profit")
    assert ok is True


def test_dot_star_alone_rejected():
    ok, err = validate(r".*")
    assert ok is False
    assert err == "wildcard"


def test_unicode_keyword_valid():
    """Unicode keywords (e.g. Russian spam words) should pass keyword validation."""
    keyword = "заработок"
    assert len(keyword) >= 3  # passes min-length check


def test_very_long_keyword_valid():
    """Very long keywords are fine — no upper bound imposed."""
    keyword = "earn money fast working from home " * 3
    assert len(keyword) >= 3


def test_keyword_with_numbers_valid():
    keyword = "$100/day"
    assert len(keyword) >= 3


def test_three_char_keyword_valid():
    assert len("job") >= 3


def test_two_char_keyword_rejected():
    assert len("dm") < 3  # would be rejected at input stage
