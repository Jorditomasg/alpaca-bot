"""Thin async wrappers over Telegram Bot API. One retry on transient errors,
no exceptions propagated to callers.
"""
import asyncio
import httpx

from telegram_bot import config

_BASE = "https://api.telegram.org"
_TIMEOUT = httpx.Timeout(connect=10.0, read=35.0, write=10.0, pool=10.0)


async def send_message(text: str) -> bool:
    """Send `text` to the configured chat. Returns True on success."""
    if not config.is_enabled():
        return False

    url = f"{_BASE}/bot{config.bot_token()}/sendMessage"
    payload = {
        "chat_id": config.chat_id(),
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as h:
                resp = await h.post(url, json=payload)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", "1"))
                    await asyncio.sleep(min(retry_after, 30))
                    continue
                if resp.status_code >= 500:
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    return False
                if resp.status_code != 200:
                    print(f"[TELEGRAM] send_message {resp.status_code}: {resp.text[:200]}")
                    return False
                return True
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            print(f"[TELEGRAM] send_message network error: {e}")
            return False
    return False


async def get_updates(offset: int, timeout: int = 30) -> list[dict]:
    """Long-poll for updates starting from `offset`. Returns updates list or []."""
    if not config.is_enabled():
        return []

    url = f"{_BASE}/bot{config.bot_token()}/getUpdates"
    params = {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}
    try:
        local_timeout = httpx.Timeout(connect=10.0, read=timeout + 10, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=local_timeout) as h:
            resp = await h.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
            if not data.get("ok"):
                return []
            return data.get("result", [])
    except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
        return []
