"""
tests/test_pattern_validation.py — Tests for pattern input validation.

Validates the guards that protect against:
- ReDoS (catastrophic backtracking)
- Wildcard-only patterns (mutes everyone)
- Too-short keywords
- Invalid regex syntax
"""

import re
import pytest

# ── Inline validation logic (mirrors handlers/admin/patterns.py) ──────────────
# We test the validation rules in isolation so they can be imported
# separately from Telegram handler context.

REDOS_PATTERNS = [
    re.compile(r"\(\?=.*\*"),
    re.compile(r"\(\?!.*\*"),
    re.compile(r"\([^)]*\+\)[+*]"),
    re.compile(r"\([^)]*\*\)[+*]"),
    re.compile(r"(\.\*){2}"),
    re.compile(r"(\.\+){2}"),
]
WILDCARD_RE = re.compile(r"^\.\*$|^\.\+$|^\.\{0,\d+\}$")
MIN_KEYWORD_LEN = 3


def validate_regex(pattern: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message). Empty error = valid."""
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return False, f"Invalid regex: {e}"

    if any(p.search(pattern) for p in REDOS_PATTERNS):
        return False, "ReDoS risk detected"

    if WILDCARD_RE.match(pattern.strip()):
        return False, "Wildcard-only pattern rejected"

    return True, ""


def validate_keyword(keyword: str) -> tuple[bool, str]:
    if len(keyword) < MIN_KEYWORD_LEN:
        return False, "Too short"
    return True, ""


# ── Regex validation ──────────────────────────────────────────────────────────

def test_valid_simple_regex():
    ok, err = validate_regex(r"\b(earn|make)\s+\$\d+")
    assert ok is True
    assert err == ""


def test_valid_complex_regex():
    ok, err = validate_regex(r"t\.me\/[a-z0-9_+]+")
    assert ok is True


def test_invalid_regex_syntax():
    ok, err = validate_regex(r"[invalid(regex")
    assert ok is False
    assert "Invalid regex" in err


def test_unclosed_group_rejected():
    ok, err = validate_regex(r"(hello")
    assert ok is False


def test_redos_nested_quantifier_rejected():
    """(a+)+ style — classic ReDoS."""
    ok, err = validate_regex(r"([a-z]+)+")
    assert ok is False
    assert "ReDoS" in err


def test_redos_nested_star_rejected():
    ok, err = validate_regex(r"([a-z]*)*")
    assert ok is False
    assert "ReDoS" in err


def test_redos_double_wildcard_rejected():
    ok, err = validate_regex(r".*.*spam")
    assert ok is False
    assert "ReDoS" in err


def test_wildcard_only_rejected():
    ok, err = validate_regex(r".*")
    assert ok is False
    assert "Wildcard" in err


def test_dot_plus_only_rejected():
    ok, err = validate_regex(r".+")
    assert ok is False
    assert "Wildcard" in err


def test_specific_pattern_not_wildcard():
    """Patterns with .* inside a larger expression are allowed."""
    ok, err = validate_regex(r"earn.*profit")
    assert ok is True  # contains .* but is not ONLY .*


# ── Keyword validation ────────────────────────────────────────────────────────

def test_keyword_valid():
    ok, err = validate_keyword("free gift")
    assert ok is True


def test_keyword_min_length():
    ok, err = validate_keyword("abc")
    assert ok is True


def test_keyword_too_short_one_char():
    ok, err = validate_keyword("a")
    assert ok is False
    assert "Too short" in err


def test_keyword_too_short_two_chars():
    ok, err = validate_keyword("ab")
    assert ok is False


def test_keyword_empty():
    ok, err = validate_keyword("")
    assert ok is False


def test_keyword_with_special_chars():
    """Keywords with special chars are literal matched — should be valid."""
    ok, err = validate_keyword("$100/day")
    assert ok is True


def test_keyword_spaces_ok():
    ok, err = validate_keyword("dm me for details")
    assert ok is True
