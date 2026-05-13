"""Tests for backtest/portfolio.py — simulated portfolio."""
import pytest
from backtest import portfolio as bt_portfolio


def test_buy_deducts_cash_and_records_position():
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)

    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    assert p.cash == pytest.approx(9000.0)
    pos = p.positions["AAPL"]
    assert pos.qty == pytest.approx(10.0)
    assert pos.cost_basis == pytest.approx(100.0)
    assert pos.entry_date == "2020-11-10"


def test_buy_rejects_when_insufficient_cash():
    """Cannot buy more than cash on hand. Should clip or refuse."""
    p = bt_portfolio.SimulatedPortfolio(starting_cash=500.0)

    accepted = p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    assert accepted is False
    assert "AAPL" not in p.positions
    assert p.cash == 500.0


def test_buy_accumulates_into_existing_position():
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")
    p.buy("AAPL", notional=1100.0, fill_price=110.0, date_iso="2020-11-15")

    pos = p.positions["AAPL"]
    assert pos.qty == pytest.approx(20.0)
    # Cost basis is weighted avg: (10*100 + 10*110) / 20 = 105
    assert pos.cost_basis == pytest.approx(105.0)


def test_sell_realizes_pnl_and_credits_cash():
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    realized = p.sell_all("AAPL", fill_price=120.0, date_iso="2020-11-20")

    assert "AAPL" not in p.positions
    assert p.cash == pytest.approx(10200.0)  # 9000 + 10 shares × 120
    assert realized == pytest.approx(200.0)


def test_equity_marks_to_market():
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    eq = p.equity(prices={"AAPL": 110.0})
    assert eq == pytest.approx(10100.0)  # 9000 cash + 10 shares × 110


def test_equity_handles_missing_price_with_cost_basis_fallback():
    """If we have no current price for a position, value it at cost basis (no PnL)."""
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    eq = p.equity(prices={})
    assert eq == pytest.approx(10000.0)


def test_trades_log_records_every_fill():
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")
    p.sell_all("AAPL", fill_price=120.0, date_iso="2020-11-20")

    log = p.trades_log
    assert len(log) == 2
    assert log[0]["side"] == "buy" and log[0]["ticker"] == "AAPL"
    assert log[1]["side"] == "sell" and log[1]["realized_pnl"] == pytest.approx(200.0)
