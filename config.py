"""
config.py — Load .env manually and expose BOT_TOKEN, DB_PATH.
No python-dotenv required.
"""

import os
import sys

def _load_env(path: str) -> None:
    """Parse a .env file and inject values into os.environ."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass  # .env is optional; env vars may already be set


# Load from .env in the same directory as this file
_load_env(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
DB_PATH: str = os.environ.get("DB_PATH", "spam.db")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set. Create a .env file or export BOT_TOKEN=...", file=sys.stderr)
    sys.exit(1)
