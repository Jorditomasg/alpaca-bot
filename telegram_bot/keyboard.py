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

    Read-only / discovery commands only. Pause/resume are excluded from
    the menu — they appear in the reply keyboard that `/help` brings up.
    """
    return [
        {"command": "status", "description": "Snapshot of all strategies"},
        {"command": "positions", "description": "Open positions + unrealized PnL"},
        {"command": "pnl", "description": "Day PnL and equity"},
        {"command": "help", "description": "Show command panel"},
    ]
