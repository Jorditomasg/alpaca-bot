"""Long-poll loop. Filters by chat_id, dispatches commands to handlers,
sends replies (with a persistent reply keyboard). Backs off on errors; never dies.

On startup it also registers the native bot-menu commands via setMyCommands.
"""
import asyncio

from telegram_bot import client, commands, config
from telegram_bot.keyboard import default_reply_keyboard, bot_menu_commands


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
        # Attach the reply keyboard so it remains visible / one-tap accessible.
        await client.send_message(reply, reply_markup=default_reply_keyboard())


async def run_poller() -> None:
    """Long-poll Telegram for new messages. Exits immediately if disabled."""
    if not config.is_enabled():
        print("[TELEGRAM] disabled (no token / chat_id) — poller not started")
        return

    # Register the native command menu once at startup. Failure is logged
    # but non-fatal — the reply keyboard still works without it.
    try:
        await client.set_my_commands(bot_menu_commands())
    except Exception as e:
        print(f"[TELEGRAM] setMyCommands failed: {e}")

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
