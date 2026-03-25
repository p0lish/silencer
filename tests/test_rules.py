"""
tests/test_rules.py — Tests for the built-in rules seeder.
"""

import pytest
from detection.rules import seed_builtin_rules
from db.patterns import get_patterns_for_group


@pytest.mark.asyncio
async def test_seed_inserts_builtin_rules(db):
    """Seeder should insert all 11 built-in patterns as global rows."""
    await seed_builtin_rules()
    patterns = await get_patterns_for_group(12345)  # any chat_id
    builtin = [p for p in patterns if p["is_builtin"] == 1]
    assert len(builtin) == 11


@pytest.mark.asyncio
async def test_seed_idempotent(db):
    """Running seeder twice should not create duplicates."""
    await seed_builtin_rules()
    await seed_builtin_rules()
    patterns = await get_patterns_for_group(12345)
    builtin = [p for p in patterns if p["is_builtin"] == 1]
    assert len(builtin) == 11


@pytest.mark.asyncio
async def test_seed_patterns_are_global(db):
    """All seeded patterns should have chat_id = NULL."""
    await seed_builtin_rules()
    patterns = await get_patterns_for_group(12345)
    for p in patterns:
        if p["is_builtin"]:
            assert p["chat_id"] is None


@pytest.mark.asyncio
async def test_seed_all_regex(db):
    """All built-in patterns should be regex (is_regex=1)."""
    await seed_builtin_rules()
    patterns = await get_patterns_for_group(12345)
    for p in [p for p in patterns if p["is_builtin"]]:
        assert p["is_regex"] == 1


@pytest.mark.asyncio
async def test_seed_expected_labels(db):
    """Verify expected label categories are present."""
    await seed_builtin_rules()
    patterns = await get_patterns_for_group(12345)
    labels = {p["label"] for p in patterns if p["is_builtin"]}
    assert "crypto scam" in labels
    assert "investment scam" in labels
    assert "fake job" in labels
    assert "scam link" in labels
    assert "telegram link" in labels
    assert "suspicious domain" in labels
