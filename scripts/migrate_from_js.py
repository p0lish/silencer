#!/usr/bin/env python3
"""
migrate_from_js.py — One-shot migration from tgbot (JS) SQLite DB to silencer (Python) DB.

Usage:
    python3 scripts/migrate_from_js.py \
        --src /home/baldur/.openclaw/workspace/tgbot/spam.db \
        --dst /home/baldur/silencer-bot/spam.db \
        [--dry-run]

Safe to run multiple times — uses INSERT OR IGNORE throughout.
Built-in global patterns (chat_id IS NULL) in dst are never touched.
"""

import argparse
import sqlite3
import sys
from datetime import datetime


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def migrate(src_path: str, dst_path: str, dry_run: bool = False):
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dst_path)
    dst.row_factory = sqlite3.Row

    mode = "DRY RUN — " if dry_run else ""
    log(f"{mode}Migrating {src_path} → {dst_path}")

    # ── groups ────────────────────────────────────────────────────────────────
    rows = src.execute("SELECT chat_id, title, owner_id, added_at FROM groups").fetchall()
    log(f"  groups: {len(rows)} rows")
    if not dry_run:
        dst.executemany(
            "INSERT OR IGNORE INTO groups (chat_id, title, owner_id, added_at) VALUES (?,?,?,?)",
            [(r["chat_id"], r["title"], r["owner_id"], r["added_at"]) for r in rows],
        )

    # ── group_admins ──────────────────────────────────────────────────────────
    rows = src.execute(
        "SELECT chat_id, user_id, username, role, added_by, added_at FROM group_admins"
    ).fetchall()
    log(f"  group_admins: {len(rows)} rows")
    if not dry_run:
        dst.executemany(
            """INSERT OR IGNORE INTO group_admins
               (chat_id, user_id, username, role, added_by, added_at)
               VALUES (?,?,?,?,?,?)""",
            [(r["chat_id"], r["user_id"], r["username"], r["role"],
              r["added_by"], r["added_at"]) for r in rows],
        )

    # ── muted ─────────────────────────────────────────────────────────────────
    rows = src.execute(
        "SELECT chat_id, user_id, username, first_name, reason, muted_at FROM muted"
    ).fetchall()
    log(f"  muted: {len(rows)} rows")
    if not dry_run:
        dst.executemany(
            """INSERT OR IGNORE INTO muted
               (chat_id, user_id, username, first_name, reason, muted_at)
               VALUES (?,?,?,?,?,?)""",
            [(r["chat_id"], r["user_id"], r["username"], r["first_name"],
              r["reason"], r["muted_at"]) for r in rows],
        )

    # ── spam_log ──────────────────────────────────────────────────────────────
    rows = src.execute(
        "SELECT chat_id, user_id, username, message, pattern, logged_at FROM spam_log"
    ).fetchall()
    log(f"  spam_log: {len(rows)} rows")
    if not dry_run:
        dst.executemany(
            """INSERT OR IGNORE INTO spam_log
               (chat_id, user_id, username, message, pattern, logged_at)
               VALUES (?,?,?,?,?,?)""",
            [(r["chat_id"], r["user_id"], r["username"], r["message"],
              r["pattern"], r["logged_at"]) for r in rows],
        )

    # ── custom_patterns ───────────────────────────────────────────────────────
    # Skip built-in global patterns from src (chat_id NOT NULL in JS schema,
    # so all rows are group-scoped — but skip anything that would duplicate
    # a dst global pattern).
    dst_globals = {
        r["pattern"]
        for r in dst.execute(
            "SELECT pattern FROM custom_patterns WHERE chat_id IS NULL"
        ).fetchall()
    }

    rows = src.execute(
        "SELECT chat_id, pattern, label, is_regex, added_by, added_at FROM custom_patterns"
    ).fetchall()

    skipped = [r for r in rows if r["pattern"] in dst_globals]
    to_insert = [r for r in rows if r["pattern"] not in dst_globals]

    log(f"  custom_patterns: {len(to_insert)} to insert, {len(skipped)} skipped (duplicate globals)")
    if not dry_run:
        dst.executemany(
            """INSERT OR IGNORE INTO custom_patterns
               (chat_id, pattern, label, is_regex, is_builtin, added_by, added_at)
               VALUES (?,?,?,?,0,?,?)""",
            [(r["chat_id"], r["pattern"], r["label"], r["is_regex"],
              r["added_by"], r["added_at"]) for r in to_insert],
        )

    # ── pending_state — intentionally skipped ─────────────────────────────────
    log("  pending_state: skipped (JS state not applicable to Python bot)")

    if not dry_run:
        dst.commit()
        log("✅ Migration complete.")
    else:
        log("✅ Dry run complete — no changes written.")

    src.close()
    dst.close()


def verify(src_path: str, dst_path: str):
    """Print row counts for both DBs side by side."""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)

    tables = ["groups", "group_admins", "muted", "spam_log", "custom_patterns"]
    log("Verification:")
    print(f"  {'Table':<20} {'JS (src)':>10} {'Python (dst)':>14}")
    print(f"  {'-'*20} {'-'*10} {'-'*14}")
    for t in tables:
        src_count = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        dst_count = dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        flag = "" if dst_count >= src_count else " ⚠️"
        print(f"  {t:<20} {src_count:>10} {dst_count:>14}{flag}")

    src.close()
    dst.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate tgbot JS DB → silencer Python DB")
    parser.add_argument("--src", default="/home/baldur/.openclaw/workspace/tgbot/spam.db")
    parser.add_argument("--dst", default="/home/baldur/silencer-bot/spam.db")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--verify", action="store_true", help="Show row counts only")
    args = parser.parse_args()

    if args.verify:
        verify(args.src, args.dst)
    else:
        migrate(args.src, args.dst, dry_run=args.dry_run)
        verify(args.src, args.dst)
