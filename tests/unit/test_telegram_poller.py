import asyncio
from unittest.mock import patch

from telegram_bot import poller


def _msg(chat_id, text, update_id):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


async def test_dispatch_routes_to_handler(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    captured = []

    async def fake_handle(cmd, args, *, control_flags=None):
        return f"HANDLED:{cmd}"

    async def fake_send(text):
        captured.append(text)
        return True

    with patch("telegram_bot.poller.commands.handle", new=fake_handle), \
         patch("telegram_bot.poller.client.send_message", new=fake_send):
        await poller.dispatch(_msg(1, "/help", 5))

    assert captured == ["HANDLED:help"]


async def test_dispatch_ignores_wrong_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    with patch("telegram_bot.poller.client.send_message", new=fake_send):
        await poller.dispatch(_msg(999, "/help", 5))

    assert sent == []


async def test_dispatch_ignores_non_command(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    with patch("telegram_bot.poller.client.send_message", new=fake_send):
        await poller.dispatch(_msg(1, "hello there", 5))

    assert sent == []


async def test_run_poller_exits_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    await asyncio.wait_for(poller.run_poller(), timeout=1.0)
