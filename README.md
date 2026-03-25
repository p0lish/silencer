# Silencer — Anti-Spam Bot

Multi-tenant Telegram anti-spam bot. Each group gets its own admin team, custom patterns, muted list, and spam log. Built with `python-telegram-bot` v21 + `aiosqlite`.

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set BOT_TOKEN

# 3. Run
python bot.py
```

---

## Adding to a Group

1. Add the bot to your group
2. **Promote it to administrator** with permissions:
   - Delete messages
   - Restrict members
3. Whoever adds the bot becomes **owner** of that group automatically
4. Send `/start` to the bot in DM to open the admin panel

---

## Admin Panel (DM)

Send `/start` to the bot privately.

| Symbol | Role |
|--------|------|
| 👑 | Owner — full control, can manage admins |
| 🔑 | Admin — can manage muted users and patterns |

### Group View

| Button | Action |
|--------|--------|
| 🔇 Muted users | List + unmute/ban |
| 📋 Spam log | Last 10 caught messages |
| 🧩 Patterns | Per-group custom patterns |
| 👥 Manage admins | Add/remove admins (owner only) |

### Patterns

- **Built-in (global):** Crypto scam, investment scam, fake job, scam links — seeded into DB on first run, editable
- **Custom (per-group):** Add keywords or regex via the panel
- **Scoring:** A message needs score ≥ 2 to trigger action
  - Each pattern match: +1
  - More than 2 unique emoji types: +1
  - Message longer than 100 chars: +1
  - Messages under 20 chars: never checked

---

## Multi-Tenancy

- Each group is isolated: own admins, own patterns, own data
- Patterns with `chat_id = NULL` are global (apply to all groups)
- Built-in rules are global with `is_builtin = 1`
- Group owners can add/remove admins for their own group only

---

## Database

SQLite file (`spam.db` by default). Tables:

| Table | Contents |
|-------|----------|
| `groups` | Registered groups |
| `group_admins` | Per-group admin list with roles |
| `custom_patterns` | Per-group + global spam patterns |
| `muted` | Currently muted users per group |
| `spam_log` | Caught spam messages |
| `pending_state` | Multi-step admin flow state (auto-cleaned) |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | required | Telegram bot token |
| `DB_PATH` | `spam.db` | SQLite database path |
