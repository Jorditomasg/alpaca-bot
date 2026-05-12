"""End-to-end import smoke check — confirms wiring doesn't break startup."""


def test_imports():
    import main  # noqa: F401
    from telegram_bot import client, config, formatter, notifier, commands, queries, poller  # noqa: F401
    from shared.control import flags
    assert flags is not None


def test_disabled_path_imports(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    import importlib
    from telegram_bot import config
    importlib.reload(config)
    assert config.is_enabled() is False
