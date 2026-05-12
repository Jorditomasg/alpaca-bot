"""Read Telegram bot configuration from env. Disabled = empty token."""
import os


def bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def chat_id() -> int | None:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_enabled() -> bool:
    return bool(bot_token()) and chat_id() is not None
