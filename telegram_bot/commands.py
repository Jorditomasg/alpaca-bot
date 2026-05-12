"""Parse and handle inbound Telegram commands. Handlers return strings
that the poller forwards to `client.send_message` (HTML parse mode).
"""
from __future__ import annotations
from typing import Optional

from shared.control import ControlFlags, flags as default_flags

_VALID_STRATEGIES = {"trailing", "copy", "wheel", "all"}

_HELP_TEXT = (
    "<b>Available commands</b>\n"
    "/status — snapshot of all strategies\n"
    "/positions — open positions + unrealized PnL\n"
    "/pnl — day PnL and equity\n"
    "/pause &lt;trailing|copy|wheel|all&gt; — pause a strategy\n"
    "/resume &lt;trailing|copy|wheel|all&gt; — resume a strategy\n"
    "/help — this message"
)


def parse(text: str) -> tuple[Optional[str], list[str]]:
    """Returns (command, args) or (None, []) if `text` isn't a command."""
    if not text or not text.startswith("/"):
        return None, []
    tokens = text.strip().split()
    head = tokens[0][1:]
    head = head.split("@", 1)[0].lower()
    return head, tokens[1:]


async def handle(command: str, args: list[str], *, control_flags: ControlFlags | None = None) -> str:
    cf = control_flags or default_flags
    if command == "help":
        return _HELP_TEXT
    if command == "pause":
        return _do_pause(args, cf)
    if command == "resume":
        return _do_resume(args, cf)
    if command == "status":
        from telegram_bot import queries
        return await queries.format_status()
    if command == "positions":
        from telegram_bot import queries
        return await queries.format_positions()
    if command == "pnl":
        from telegram_bot import queries
        return await queries.format_pnl()
    return "Unknown command. Try /help."


def _do_pause(args: list[str], cf: ControlFlags) -> str:
    if not args or args[0] not in _VALID_STRATEGIES:
        return "Invalid argument. Use /pause &lt;trailing|copy|wheel|all&gt;."
    cf.pause(args[0])
    return f"Paused {args[0]}"


def _do_resume(args: list[str], cf: ControlFlags) -> str:
    if not args or args[0] not in _VALID_STRATEGIES:
        return "Invalid argument. Use /resume &lt;trailing|copy|wheel|all&gt;."
    cf.resume(args[0])
    return f"Resumed {args[0]}"
