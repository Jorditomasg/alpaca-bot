"""Long-poll loop. Filters by chat_id, dispatches commands to handlers,
sends replies. Backs off on errors; never dies.
"""
import asyncio

from telegram_bot import client, commands, config


async def dispatch(update: dict) -> None:
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = msg.get("text") or ""

    allowed = config.chat_id()
    if allowed is None or chat_id != allowed:
        print(f"[TELEGRAM] update from non-allowlisted chat {chat_id} — ignored")
        return

    cmd, args = commands.parse(text)
    if cmd is None:
        return

    try:
        reply = await commands.handle(cmd, args)
    except Exception as e:
        print(f"[TELEGRAM] command handler error: {e}")
        reply = "Command failed. See server logs."

    if reply:
        await client.send_message(reply)


async def run_poller() -> None:
    """Long-poll Telegram for new messages. Exits immediately if disabled."""
    if not config.is_enabled():
        print("[TELEGRAM] disabled (no token / chat_id) — poller not started")
        return

    print("[TELEGRAM] poller started")
    offset = 0
    backoff = 1
    while True:
        try:
            updates = await client.get_updates(offset=offset, timeout=30)
            if updates:
                backoff = 1
                for u in updates:
                    try:
                        await dispatch(u)
                    except Exception as e:
                        print(f"[TELEGRAM] dispatch error: {e}")
                    offset = max(offset, u.get("update_id", 0) + 1)
        except Exception as e:
            print(f"[TELEGRAM] poller error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
