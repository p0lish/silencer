# Probation System — Spec

## Overview

New members get stricter spam detection for their first 24 hours.
First-message spammers get instant action with zero tolerance.

## Database Changes

New table `member_activity`:
```sql
CREATE TABLE IF NOT EXISTS member_activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    joined_at  INTEGER NOT NULL,
    msg_count  INTEGER DEFAULT 0,
    first_msg_at INTEGER,
    trusted_at INTEGER,           -- NULL until probation ends
    UNIQUE(chat_id, user_id)
);
```

## Probation Rules

### Thresholds
- **Probation period:** 24 hours from join OR 5 clean messages (whichever comes first)
- **Trusted:** after probation, normal scoring (threshold=2) applies
- **During probation:** spam threshold drops from 2 → 1 (any single pattern match = spam)

### First Message Trap
- If a user's **first ever message** in the group matches ANY spam pattern → instant delete + mute
- No score threshold needed — first message + any hit = spam
- Rationale: legitimate new members almost never spam on their first message

### Join Tracking
- On `ChatMemberUpdated` (new member joins): insert into `member_activity` with `joined_at=now`
- On each message from a non-trusted user: increment `msg_count`, set `first_msg_at` if NULL
- On 5th clean message OR 24h elapsed: set `trusted_at=now`

### Scoring Integration (scorer.py)

```python
async def score_message(text, chat_id, user_id) -> (score, hits, is_probation):
    member = get_member_activity(chat_id, user_id)
    
    # Calculate base score (existing logic)
    score, hits = ... 
    
    if member is None or member.trusted_at is None:
        # Probation mode
        is_first_msg = (member is None) or (member.msg_count == 0)
        
        if is_first_msg and score >= 1:
            # First message trap — any single hit = spam
            return score, hits, True
        
        if score >= 1:
            # Probation — lower threshold
            return score, hits, True
    
    # Normal mode — threshold stays at 2
    return score, hits, False
```

### Message Handler Changes (messages.py)

- Pass `user_id` to `score_message()`
- After scoring, if not spam: call `increment_msg_count(chat_id, user_id)`
- Check trust promotion: if msg_count >= 5 or joined_at > 24h ago → set trusted

### What Changes for Trusted Users
- Normal scoring (threshold=2)
- Skip `member_activity` updates (save DB writes)

## Edge Cases

- **Bot added to existing group:** existing members won't have `member_activity` rows. Treat missing row as probation with `joined_at=now` on first message. They'll graduate after 5 clean messages.
- **User leaves and rejoins:** reset `member_activity` row (new probation period).
- **Telegram admins:** skip probation entirely (already skipped in current code).

## Files to Change

1. `db/migrations.py` — add `member_activity` table
2. `db/members.py` — new file: get/upsert/increment/promote functions
3. `detection/scorer.py` — accept `user_id`, check probation status
4. `handlers/messages.py` — pass user_id, update activity after clean messages
5. `handlers/membership.py` — track joins in `member_activity`
