"""Configuration: env vars, paths, and module-level constants.

Anything that reads from ``os.getenv`` or relies on the filesystem lives here.
This makes it obvious where defaults come from and keeps the rest of the
package decoupled from environment setup.
"""

from __future__ import annotations

import os
from pathlib import Path


# ============================================================
# ENVIRONMENT HELPERS
# ============================================================
def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_int_set(name: str, default: set[int]) -> set[int]:
    """Read a comma-separated set of Discord user IDs from the environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return {
        int(value.strip())
        for value in raw.split(",")
        if value.strip().isdigit()
    }


# ============================================================
# 9ROUTER (sole AI gateway)
# ============================================================
NINE_ROUTER_ENABLED = _env_bool("NINE_ROUTER_ENABLED", False)
NINE_ROUTER_BASE_URL = os.getenv("NINE_ROUTER_BASE_URL", "http://localhost:20128/v1")
NINE_ROUTER_API_KEY = os.getenv("NINE_ROUTER_API_KEY", "")
NINE_ROUTER_MODEL = os.getenv("NINE_ROUTER_MODEL", "kr/claude-sonnet-4.5")
NINE_ROUTER_API_TIMEOUT = _env_float("NINE_ROUTER_API_TIMEOUT", 60.0)
NINE_ROUTER_MAX_OUTPUT_TOKENS = _env_int("NINE_ROUTER_MAX_OUTPUT_TOKENS", 4000)
NINE_ROUTER_TEMPERATURE = _env_float("NINE_ROUTER_TEMPERATURE", 0.75)
NINE_ROUTER_TOP_P = _env_float("NINE_ROUTER_TOP_P", 0.9)
NINE_ROUTER_MAX_RETRIES = _env_int("NINE_ROUTER_MAX_RETRIES", 3)
NINE_ROUTER_RETRY_BACKOFF = _env_float("NINE_ROUTER_RETRY_BACKOFF", 1.0)

# Discord log webhook
DISCORD_LOG_WEBHOOK_URL = os.getenv("DISCORD_LOG_WEBHOOK_URL", "")
DISCORD_LOG_LEVEL = os.getenv("DISCORD_LOG_LEVEL", "WARNING")
DISCORD_LOG_THROTTLE = _env_float("DISCORD_LOG_THROTTLE_SECONDS", 5.0)

# Support / donation links
DONATE_KOFI_URL = os.getenv("DONATE_KOFI_URL", "https://ko-fi.com/vv3yy")
DONATE_PAYPAL_URL = os.getenv("DONATE_PAYPAL_URL", "")
DONATE_MESSAGE = os.getenv("DONATE_MESSAGE", "")

# Project metadata (used by /source)
REPO_URL = os.getenv("REPO_URL", "https://github.com/Vey-Project/tarot-bot-discord")
LICENSE_NAME = os.getenv("LICENSE_NAME", "MIT License")
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "vv3yy")

# Bot behavior
SYNC_SLASH_COMMANDS = _env_bool("SYNC_SLASH_COMMANDS", True)
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "id")
DEFAULT_READING_MODE = os.getenv("DEFAULT_READING_MODE", "deep")
# Users in this list may run bot admin commands without holding a Discord
# Administrator role. Override with a comma-separated BOT_ADMIN_IDS value.
BOT_ADMIN_IDS = _env_int_set("BOT_ADMIN_IDS", {789065787276132392})

# Firebase
FIREBASE_ENABLED = _env_bool("FIREBASE_ENABLED", False)
FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET", "")

# Set after we try to import firebase_admin (mirrors main.py semantics)
try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage  # noqa: F401
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False


# ============================================================
# PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"
FONTS_DIR = BASE_DIR / "fonts"
SAVES_DIR = BASE_DIR / "saves"
JOURNALS_DIR = SAVES_DIR / "journals"
SETTINGS_DIR = SAVES_DIR / "settings"


# ============================================================
# CARDS DATA — populated by ``load_tarot_cards()`` at startup.
# ============================================================
TAROT_CARDS: list = []


def load_tarot_cards() -> int:
    """Load card definitions from ``data/tarot_cards.json`` into TAROT_CARDS.

    Called once during startup; the result is cached on this module.
    """
    import json
    cards_path = DATA_DIR / "tarot_cards.json"
    with open(cards_path, encoding="utf-8") as f:
        TAROT_CARDS.clear()
        TAROT_CARDS.extend(json.load(f))
    return len(TAROT_CARDS)
