"""
tests/test_scorer.py — Unit tests for the spam scoring engine.

Tests cover:
- Short message bypass
- Single signal (no trigger)
- Pattern + length = trigger
- Pattern + emoji = trigger
- Multiple pattern hits
- The $1150/week scam message (regression)
- Emoji counting
- Global vs group patterns
- Bad/malformed patterns don't crash scorer
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock

from detection.scorer import score_message, _count_unique_emoji


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_pattern(pattern, label, is_regex=1, is_builtin=1, chat_id=None):
    return {
        "pattern": pattern,
        "label": label,
        "is_regex": is_regex,
        "is_builtin": is_builtin,
        "chat_id": chat_id,
    }


CRYPTO_PATTERN = make_pattern(
    r"\b(airdrop|crypto (signal|project|group|trading)|nft (mint|drop|project))\b",
    "crypto scam"
)
INVESTMENT_PATTERN = make_pattern(
    r"\b(earn|make|earnings?)\s+\$\d+|\$\d+[\s\S]{0,15}per\s+(day|week|month|hour)",
    "investment scam"
)
FAKE_JOB_PATTERN = make_pattern(
    r"\b(work from home|work at home|only (a |your )?(phone|smartphone|laptop))\b",
    "fake job"
)
SCAM_LINK_PATTERN = make_pattern(
    r"\b(click (here|link|below)|join (now|today)|free (money|gift|prize|reward))\b",
    "scam link"
)


# ── Tests: basic thresholds ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_short_message_skipped():
    """Messages under 20 chars are never checked."""
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message("Buy now!", 123)
    assert score == 0
    assert hits == []


@pytest.mark.asyncio
async def test_exactly_19_chars_skipped():
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message("a" * 19, 123)
    assert score == 0


@pytest.mark.asyncio
async def test_exactly_20_chars_processed():
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO_PATTERN]):
        score, hits = await score_message("a" * 20, 123)
    assert score == 0  # no match, but was processed


@pytest.mark.asyncio
async def test_single_pattern_no_trigger():
    """One pattern hit alone doesn't reach threshold (score = 1)."""
    text = "Join our crypto trading group today for profits"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO_PATTERN]):
        score, hits = await score_message(text, 123)
    assert score == 1
    assert "crypto scam" in hits


@pytest.mark.asyncio
async def test_pattern_plus_length_triggers():
    """Pattern + long message = score 2, should trigger."""
    text = "Join our crypto trading group today for amazing profits. " \
           "We have been running for 5 years and have thousands of members globally."
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO_PATTERN]):
        score, hits = await score_message(text, 123)
    assert score >= 2
    assert "crypto scam" in hits
    assert "long message" in hits


@pytest.mark.asyncio
async def test_pattern_plus_emoji_triggers():
    """Pattern + 3+ unique emojis = score 2."""
    text = "🚀💰🎁 Join our crypto trading group for amazing profits!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[CRYPTO_PATTERN]):
        score, hits = await score_message(text, 123)
    assert score >= 2
    assert "crypto scam" in hits
    assert any("emoji" in h for h in hits)


@pytest.mark.asyncio
async def test_two_patterns_triggers():
    """Two separate pattern matches = score 2."""
    text = "Work from home and join our crypto trading group now"
    patterns = [CRYPTO_PATTERN, FAKE_JOB_PATTERN]
    with patch("detection.scorer.get_patterns_for_group", return_value=patterns):
        score, hits = await score_message(text, 123)
    assert score >= 2


# ── Tests: specific scam messages ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dollar_per_week_scam_triggers():
    """Regression: '$1150 per week' scam must trigger (was broken by \\b + \\$)."""
    text = (
        "We are looking for 2–3 people to join the project.\n"
        "Clear instructions provided.\n"
        "Earnings from $1150 per week.\n"
        "Details: write \"+\" in private messages to"
    )
    patterns = [INVESTMENT_PATTERN]
    with patch("detection.scorer.get_patterns_for_group", return_value=patterns):
        score, hits = await score_message(text, 123)
    assert score >= 2, f"Expected score >=2, got {score} with hits {hits}"
    assert "investment scam" in hits


@pytest.mark.asyncio
async def test_earn_dollar_pattern():
    """'Earn $500/day' phrasing."""
    text = "You can earn $500 per day from your phone, no experience needed at all!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[INVESTMENT_PATTERN]):
        score, hits = await score_message(text, 123)
    assert score >= 1
    assert "investment scam" in hits


@pytest.mark.asyncio
async def test_full_scam_message_high_score():
    """A realistic full spam message should score 4+."""
    text = (
        "🚀💰✨ PASSIVE INCOME OPPORTUNITY! Earn $500 per day with our proven "
        "trading signals. No experience needed, only your smartphone required. "
        "Guaranteed profit — join our group now! t.me/totallylegit"
    )
    all_patterns = [
        INVESTMENT_PATTERN,
        FAKE_JOB_PATTERN,
        SCAM_LINK_PATTERN,
        make_pattern(r"\b(passive income|guaranteed (profit|return|income)|trading (signal|bot|group))\b", "investment scam"),
        make_pattern(r"t\.me\/[a-z0-9_+]+", "telegram link"),
    ]
    with patch("detection.scorer.get_patterns_for_group", return_value=all_patterns):
        score, hits = await score_message(text, 123)
    assert score >= 4


@pytest.mark.asyncio
async def test_legit_message_no_trigger():
    """Normal Hungarian community message must not trigger."""
    text = (
        "Srácok, ma este megint összejön a Csillámfaszláma csapat a szokásos helyén! "
        "Aki még nem tudja, minden szerdán tartunk egy kis összejövetelt ahol mindenki "
        "elmondhatja mi van nála."
    )
    all_patterns = [CRYPTO_PATTERN, INVESTMENT_PATTERN, FAKE_JOB_PATTERN, SCAM_LINK_PATTERN]
    with patch("detection.scorer.get_patterns_for_group", return_value=all_patterns):
        score, hits = await score_message(text, 123)
    assert score < 2, f"Legit message falsely scored {score}: {hits}"


@pytest.mark.asyncio
async def test_empty_patterns_only_structural_signals():
    """With no patterns, only length/emoji can score — max 2."""
    text = "💰🚀🎁 " + "x" * 200
    with patch("detection.scorer.get_patterns_for_group", return_value=[]):
        score, hits = await score_message(text, 123)
    assert score == 2  # emoji (3 unique) + long


# ── Tests: emoji counting ─────────────────────────────────────────────────────

def test_count_unique_emoji_none():
    assert _count_unique_emoji("hello world") == 0


def test_count_unique_emoji_two():
    assert _count_unique_emoji("hello 🎉 world 🎊") == 2


def test_count_unique_emoji_three():
    assert _count_unique_emoji("🚀💰🎁 click here") == 3


def test_count_unique_emoji_repeated():
    """Same emoji repeated = still 1 unique."""
    assert _count_unique_emoji("🚀🚀🚀🚀🚀") == 1


def test_count_unique_emoji_mixed():
    assert _count_unique_emoji("💰💰🚀🚀🎁") == 3


# ── Tests: bad patterns don't crash ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_malformed_regex_skipped():
    """Malformed regex pattern should be silently skipped, not crash."""
    bad_pattern = make_pattern(r"[invalid(regex", "bad", is_regex=1)
    text = "This is a message that is long enough to be checked by the scorer."
    with patch("detection.scorer.get_patterns_for_group", return_value=[bad_pattern]):
        score, hits = await score_message(text, 123)
    # Should not raise, bad pattern contributes 0
    assert isinstance(score, int)


@pytest.mark.asyncio
async def test_keyword_pattern_literal_match():
    """Keyword patterns (is_regex=0) are matched literally, not as regex."""
    pattern = make_pattern("free gift", "scam", is_regex=0)
    text = "Get your free gift now by joining our amazing telegram group today here!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[pattern]):
        score, hits = await score_message(text, 123)
    assert score >= 1
    assert "scam" in hits[0] or "custom" in hits[0]


@pytest.mark.asyncio
async def test_keyword_regex_chars_not_interpreted():
    """Keyword with regex special chars matches literally."""
    pattern = make_pattern("$100/day", "scam", is_regex=0)
    text = "Make $100/day from home working with us, no experience required at all!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[pattern]):
        score, hits = await score_message(text, 123)
    assert score >= 1


# ── Tests: hits truncated to 3 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hits_capped_at_three():
    """Hits list should never exceed 3 entries."""
    patterns = [
        make_pattern(r"\bairdrop\b", "crypto scam"),
        make_pattern(r"\bpassive income\b", "investment scam"),
        make_pattern(r"\bwork from home\b", "fake job"),
        make_pattern(r"\bclick here\b", "scam link"),
    ]
    text = "🚀💰🎁 airdrop passive income work from home click here — amazing opportunity!"
    with patch("detection.scorer.get_patterns_for_group", return_value=patterns):
        score, hits = await score_message(text, 123)
    assert len(hits) <= 3


# ── Tests: custom vs builtin label prefix ─────────────────────────────────────

@pytest.mark.asyncio
async def test_custom_pattern_label_prefixed():
    """Custom (non-builtin) pattern labels get 'custom: ' prefix."""
    pattern = make_pattern(r"\bspecial offer\b", "my label", is_builtin=0)
    text = "This is a special offer for all members of our amazing group join now please!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[pattern]):
        score, hits = await score_message(text, 123)
    assert any("custom: my label" in h for h in hits)


@pytest.mark.asyncio
async def test_builtin_pattern_no_prefix():
    """Built-in pattern labels are used as-is."""
    pattern = make_pattern(r"\bairdrop\b", "crypto scam", is_builtin=1)
    text = "Join our amazing airdrop today and earn money from home easily and quickly!"
    with patch("detection.scorer.get_patterns_for_group", return_value=[pattern]):
        score, hits = await score_message(text, 123)
    assert any(h == "crypto scam" for h in hits)
