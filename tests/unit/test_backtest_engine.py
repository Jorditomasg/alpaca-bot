"""Tests for backtest/engine.py — chronological replay."""
import pytest
from backtest import engine as bt_engine
from backtest import strategy as bt_strategy


class _StubFetcher:
    def __init__(self, data):
        self.data = data

    def get_close_on(self, ticker, date_iso):
        return self.data.get((ticker, date_iso))


def test_engine_replays_trades_chronologically_and_buys_on_pub_date():
    trades = [
        {"id": "1", "politician": "Jane Doe", "ticker": "AAPL", "type": "buy",
         "amount_low": 15001, "amount_high": 50000, "amount_mid": 32500,
         "traded_date": "2020-11-01", "pub_date": "2020-12-01"},
    ]
    prices = _StubFetcher({
        ("AAPL", "2020-12-01"): 100.0,
        ("AAPL", "2020-12-31"): 110.0,
    })
    strat = bt_strategy.BaselineStrategy(starting_cash=10000.0, notional_per_trade=1000.0)
    strat.set_following("Jane Doe")

    result = bt_engine.run(
        trades=trades,
        prices=prices,
        strategy=strat,
        start_date="2020-12-01",
        end_date="2020-12-31",
    )

    # Position opened on pub_date at $100
    assert len(result.portfolio.trades_log) == 1
    fill = result.portfolio.trades_log[0]
    assert fill["ticker"] == "AAPL"
    assert fill["price"] == 100.0


def test_engine_exits_on_strategy_signal():
    trades = [
        {"id": "1", "politician": "Jane Doe", "ticker": "AAPL", "type": "buy",
         "amount_low": 15001, "amount_high": 50000, "amount_mid": 32500,
         "traded_date": "2020-11-01", "pub_date": "2020-12-01"},
    ]
    prices = _StubFetcher({
        ("AAPL", "2020-12-01"): 100.0,
        ("AAPL", "2020-12-02"): 95.0,
        ("AAPL", "2020-12-03"): 91.0,  # drop > 8% from entry → stop_loss
    })
    strat = bt_strategy.ImprovedStrategy(starting_cash=10000.0, notional_per_trade=1000.0,
                                         stop_loss_pct=8.0, pub_freshness_days=30)
    strat.set_following("Jane Doe")

    result = bt_engine.run(
        trades=trades,
        prices=prices,
        strategy=strat,
        start_date="2020-12-01",
        end_date="2020-12-03",
    )

    log = result.portfolio.trades_log
    assert any(t["side"] == "sell" for t in log)


def test_engine_records_equity_curve_per_trading_day():
    trades = []
    prices = _StubFetcher({})
    strat = bt_strategy.BaselineStrategy(starting_cash=10000.0, notional_per_trade=1000.0)

    result = bt_engine.run(
        trades=trades,
        prices=prices,
        strategy=strat,
        start_date="2020-12-01",  # Tuesday
        end_date="2020-12-07",    # Monday — spans a weekend
    )

    # Tue, Wed, Thu, Fri, Mon = 5 business days
    assert len(result.equity_curve) == 5
    assert all(eq == 10000.0 for _, eq in result.equity_curve)
