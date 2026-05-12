import httpx
import pytest
from unittest.mock import patch

from telegram_bot import client


def _ok(data=None):
    return httpx.Response(200, json={"ok": True, "result": data or []})


async def test_send_message_calls_correct_endpoint(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "7")
    captured = {}

    async def fake_post(self, url, json):
        captured["url"] = url
        captured["json"] = json
        return _ok({"message_id": 1})

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.send_message("hello")

    assert ok is True
    assert captured["url"].endswith("/bot999:tok/sendMessage")
    assert captured["json"]["chat_id"] == 7
    assert captured["json"]["text"] == "hello"
    assert captured["json"]["parse_mode"] == "HTML"


async def test_send_message_retries_once_on_network_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    calls = {"n": 0}

    async def fake_post(self, url, json):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return _ok({"message_id": 1})

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.send_message("hi")

    assert ok is True
    assert calls["n"] == 2


async def test_send_message_gives_up_after_two_failures(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    async def fake_post(self, url, json):
        raise httpx.ConnectError("boom")

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.send_message("hi")

    assert ok is False


async def test_send_message_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    called = {"n": 0}

    async def fake_post(self, url, json):
        called["n"] += 1
        return _ok()

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.send_message("hi")

    assert ok is False
    assert called["n"] == 0


async def test_get_updates_returns_results(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    async def fake_get(self, url, params):
        return _ok([{"update_id": 1, "message": {"chat": {"id": 1}, "text": "/help"}}])

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        updates = await client.get_updates(offset=0)

    assert len(updates) == 1
    assert updates[0]["update_id"] == 1


async def test_send_message_includes_reply_markup_when_provided(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    captured = {}

    async def fake_post(self, url, json):
        captured["json"] = json
        return _ok({"message_id": 1})

    markup = {"keyboard": [[{"text": "/status"}]], "is_persistent": True}
    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.send_message("hi", reply_markup=markup)

    assert ok is True
    assert captured["json"]["reply_markup"] == markup


async def test_send_message_omits_reply_markup_when_not_provided(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    captured = {}

    async def fake_post(self, url, json):
        captured["json"] = json
        return _ok({"message_id": 1})

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        await client.send_message("hi")

    assert "reply_markup" not in captured["json"]


async def test_set_my_commands_posts_correct_payload(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    captured = {}

    async def fake_post(self, url, json):
        captured["url"] = url
        captured["json"] = json
        return _ok([])

    cmds = [{"command": "status", "description": "x"}]
    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.set_my_commands(cmds)

    assert ok is True
    assert captured["url"].endswith("/setMyCommands")
    assert captured["json"] == {"commands": cmds}


async def test_set_my_commands_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    called = {"n": 0}

    async def fake_post(self, url, json):
        called["n"] += 1
        return _ok([])

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        ok = await client.set_my_commands([{"command": "x", "description": "y"}])

    assert ok is False
    assert called["n"] == 0
