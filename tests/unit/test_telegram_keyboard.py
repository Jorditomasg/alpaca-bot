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


def test_bot_menu_has_all_commands_with_descriptions():
    cmds = bot_menu_commands()
    names = {c["command"] for c in cmds}
    assert {"status", "positions", "pnl", "pause", "resume", "help"} <= names
    for c in cmds:
        assert c["description"]  # non-empty
        assert not c["command"].startswith("/")  # bot-menu commands are bare
