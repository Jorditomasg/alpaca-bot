"""Reply-keyboard and bot-menu definitions for the Telegram UI."""


def default_reply_keyboard() -> dict:
    """Persistent reply keyboard with one-tap access to common commands.

    `is_persistent=True` keeps it visible across messages once shown.
    Buttons that include an argument (e.g. `/pause wheel`) send the
    full text — the existing parser handles them with no changes.
    """
    return {
        "keyboard": [
            [{"text": "/status"}, {"text": "/positions"}],
            [{"text": "/pnl"}, {"text": "/help"}],
            [{"text": "/pause wheel"}, {"text": "/resume wheel"}],
            [{"text": "/pause all"}, {"text": "/resume all"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def bot_menu_commands() -> list[dict]:
    """Commands shown in Telegram's native bot menu (setMyCommands).

    The icon appears next to the input field. Tapping a row inserts the
    command into the input box; the user confirms with send.
    """
    return [
        {"command": "status", "description": "Snapshot of all strategies"},
        {"command": "positions", "description": "Open positions + unrealized PnL"},
        {"command": "pnl", "description": "Day PnL and equity"},
        {"command": "pause", "description": "Pause a strategy (e.g. /pause wheel)"},
        {"command": "resume", "description": "Resume a strategy"},
        {"command": "help", "description": "List all commands"},
    ]
