from telegram_bot.keyboard import default_reply_keyboard, bot_menu_commands


def test_default_keyboard_has_persistent_flag():
    kb = default_reply_keyboard()
    assert kb["is_persistent"] is True
    assert kb["resize_keyboard"] is True


def test_default_keyboard_includes_core_commands():
    kb = default_reply_keyboard()
    texts = [btn["text"] for row in kb["keyboard"] for btn in row]
    assert "/status" in texts
    assert "/positions" in texts
    assert "/pnl" in texts
    assert "/help" in texts
    assert "/pause wheel" in texts
    assert "/resume wheel" in texts


def test_bot_menu_only_has_read_only_commands():
    """Pause/resume are excluded from the native bot menu — they live in
    the reply keyboard surfaced by /help.
    """
    cmds = bot_menu_commands()
    names = {c["command"] for c in cmds}
    assert names == {"status", "positions", "pnl", "help"}
    assert "pause" not in names
    assert "resume" not in names
    for c in cmds:
        assert c["description"]
        assert not c["command"].startswith("/")
