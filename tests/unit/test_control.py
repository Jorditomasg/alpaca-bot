import asyncio
import pytest
from shared.control import ControlFlags


def test_strategies_start_active():
    cf = ControlFlags()
    assert cf.is_paused("trailing") is False
    assert cf.is_paused("copy") is False
    assert cf.is_paused("wheel") is False


def test_pause_and_resume():
    cf = ControlFlags()
    cf.pause("wheel")
    assert cf.is_paused("wheel") is True
    cf.resume("wheel")
    assert cf.is_paused("wheel") is False


def test_pause_all_resume_all():
    cf = ControlFlags()
    cf.pause("all")
    assert cf.is_paused("trailing") and cf.is_paused("copy") and cf.is_paused("wheel")
    cf.resume("all")
    assert not cf.is_paused("trailing")
    assert not cf.is_paused("copy")
    assert not cf.is_paused("wheel")


def test_unknown_strategy_is_noop():
    cf = ControlFlags()
    cf.pause("nonsense")
    cf.resume("nonsense")
    assert cf.is_paused("nonsense") is False


async def test_wait_if_paused_returns_immediately_when_active():
    cf = ControlFlags()
    await asyncio.wait_for(cf.wait_if_paused("wheel"), timeout=0.1)


async def test_wait_if_paused_blocks_until_resume():
    cf = ControlFlags()
    cf.pause("wheel")

    async def resume_after():
        await asyncio.sleep(0.05)
        cf.resume("wheel")

    await asyncio.gather(cf.wait_if_paused("wheel"), resume_after())
