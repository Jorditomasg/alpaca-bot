from unittest.mock import MagicMock

from telegram_bot import queries


async def test_format_status_with_all_strategies(monkeypatch):
    monkeypatch.setattr(
        "telegram_bot.queries.trailing_state.load",
        lambda: {"symbol": "TSLA", "entry_price": 245.0, "floor": 220.0,
                  "position_qty": 0.5, "trailing_active": False},
    )
    monkeypatch.setattr(
        "telegram_bot.queries.copy_state.load",
        lambda: {"following": "Pelosi", "positions": {"AAPL": {}, "MSFT": {}}, "seen_trade_ids": []},
    )
    monkeypatch.setattr(
        "telegram_bot.queries.wheel_state.load",
        lambda: {"symbol": "SOFI", "stage": "SPREAD_OPEN", "contract_expiry": "2026-05-20"},
    )
    out = await queries.format_status()
    assert "TSLA" in out and "Pelosi" in out and "SOFI" in out
    assert "SPREAD_OPEN" in out


async def test_format_status_when_no_state(monkeypatch):
    monkeypatch.setattr("telegram_bot.queries.trailing_state.load", lambda: None)
    monkeypatch.setattr("telegram_bot.queries.copy_state.load", lambda: None)
    monkeypatch.setattr("telegram_bot.queries.wheel_state.load", lambda: None)
    out = await queries.format_status()
    assert "no state" in out.lower() or "idle" in out.lower()


async def test_format_pnl_uses_alpaca_account(monkeypatch):
    fake_acct = MagicMock()
    fake_acct.equity = "10500.00"
    fake_acct.last_equity = "10000.00"
    fake_acct.buying_power = "4000.00"
    fake_trading = MagicMock()
    fake_trading.get_account.return_value = fake_acct
    monkeypatch.setattr("telegram_bot.queries.alpaca_client.trading", lambda: fake_trading)
    out = await queries.format_pnl()
    assert "10,500" in out or "10500" in out
    assert "5.0%" in out or "+5.0%" in out
