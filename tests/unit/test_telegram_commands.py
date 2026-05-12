import pytest

from telegram_bot import commands
from shared.control import ControlFlags


def test_parse_help():
    cmd, args = commands.parse("/help")
    assert cmd == "help" and args == []


def test_parse_pause_wheel():
    cmd, args = commands.parse("/pause wheel")
    assert cmd == "pause" and args == ["wheel"]


def test_parse_pause_all():
    cmd, args = commands.parse("/pause all")
    assert args == ["all"]


def test_parse_strips_botname():
    cmd, args = commands.parse("/status@my_bot")
    assert cmd == "status"


def test_parse_unknown_returns_command_as_is():
    cmd, args = commands.parse("/garbage")
    assert cmd == "garbage"


def test_parse_non_command_returns_none():
    cmd, args = commands.parse("hello there")
    assert cmd is None


async def test_handle_help_returns_text():
    out = await commands.handle("help", [], control_flags=ControlFlags())
    assert "/status" in out and "/pause" in out


async def test_handle_pause_sets_flag():
    cf = ControlFlags()
    out = await commands.handle("pause", ["wheel"], control_flags=cf)
    assert "Paused" in out and "wheel" in out
    assert cf.is_paused("wheel") is True


async def test_handle_resume_clears_flag():
    cf = ControlFlags()
    cf.pause("wheel")
    out = await commands.handle("resume", ["wheel"], control_flags=cf)
    assert "Resumed" in out
    assert cf.is_paused("wheel") is False


async def test_handle_pause_unknown_strategy():
    cf = ControlFlags()
    out = await commands.handle("pause", ["foobar"], control_flags=cf)
    assert "Unknown" in out or "Invalid" in out


async def test_handle_unknown_command():
    out = await commands.handle("garbage", [], control_flags=ControlFlags())
    assert "Unknown command" in out
