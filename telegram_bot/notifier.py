"""High-level fail-closed notification API. Every public function:
  - returns None
  - catches Exception
  - never raises into trading code
"""
from telegram_bot import client, formatter, config


async def _send(text: str) -> None:
    if not config.is_enabled():
        return
    try:
        await client.send_message(text)
    except Exception as e:
        print(f"[TELEGRAM] notify failed: {e}")


async def notify_trade(strategy, side, symbol, qty=None, notional=None, price=None, reason=""):
    try:
        text = formatter.format_trade(strategy=strategy, side=side, symbol=symbol,
                                       qty=qty, notional=notional, price=price, reason=reason)
    except Exception as e:
        print(f"[TELEGRAM] format_trade error: {e}")
        return
    await _send(text)


async def notify_state(strategy: str, event: str, details: dict) -> None:
    try:
        text = formatter.format_state(strategy, event, details)
    except Exception as e:
        print(f"[TELEGRAM] format_state error: {e}")
        return
    await _send(text)


async def notify_error(task: str, error: str) -> None:
    text = formatter.format_error(task=task, error=error)
    await _send(text)


async def notify_warn(scope: str, message: str) -> None:
    text = formatter.format_warn(scope=scope, message=message)
    await _send(text)


async def notify_summary(date_str, trailing, copy, wheel, account) -> None:
    try:
        text = formatter.format_daily_summary(date_str, trailing, copy, wheel, account)
    except Exception as e:
        print(f"[TELEGRAM] format_summary error: {e}")
        return
    await _send(text)
