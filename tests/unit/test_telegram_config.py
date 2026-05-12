import importlib
from telegram_bot import config


def test_disabled_when_token_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    importlib.reload(config)
    assert config.is_enabled() is False
    assert config.bot_token() == ""
    assert config.chat_id() is None


def test_enabled_when_both_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    importlib.reload(config)
    assert config.is_enabled() is True
    assert config.bot_token() == "123:abc"
    assert config.chat_id() == 42


def test_disabled_when_chat_id_invalid(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-number")
    importlib.reload(config)
    assert config.is_enabled() is False
    assert config.chat_id() is None
