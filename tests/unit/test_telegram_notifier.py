from unittest.mock import AsyncMock, patch
import pytest

from telegram_bot import notifier


async def test_notify_trade_calls_client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with patch("telegram_bot.notifier.client.send_message", new=AsyncMock(return_value=True)) as send:
        await notifier.notify_trade(
            strategy="trailing", side="buy", symbol="TSLA",
            qty=0.12, price=245.30, reason="Ladder -22%",
        )
    send.assert_called_once()
    sent_text = send.call_args.args[0]
    assert "TRAILING" in sent_text and "TSLA" in sent_text


async def test_notify_swallows_exceptions(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with patch("telegram_bot.notifier.client.send_message",
              new=AsyncMock(side_effect=RuntimeError("kaboom"))):
        await notifier.notify_trade(strategy="trailing", side="buy",
                                     symbol="TSLA", qty=0.1, price=1.0)


async def test_notify_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with patch("telegram_bot.notifier.client.send_message", new=AsyncMock(return_value=True)) as send:
        await notifier.notify_trade(strategy="trailing", side="buy",
                                     symbol="TSLA", qty=0.1, price=1.0)
    send.assert_not_called()


async def test_notify_error_uses_alarm_format(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with patch("telegram_bot.notifier.client.send_message", new=AsyncMock(return_value=True)) as send:
        await notifier.notify_error(task="wheel_task", error="Boom")
    text = send.call_args.args[0]
    assert text.startswith("🚨")


async def test_notify_summary_includes_account(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with patch("telegram_bot.notifier.client.send_message", new=AsyncMock(return_value=True)) as send:
        await notifier.notify_summary(
            date_str="2026-05-12",
            trailing=None, copy=None, wheel=None,
            account={"equity": 100.0, "day_pct": 0.0, "buying_power": 50.0},
        )
    assert "Equity" in send.call_args.args[0]
