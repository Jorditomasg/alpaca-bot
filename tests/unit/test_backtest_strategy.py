"""Tests for backtest/strategy.py — strategy contract + baseline + improved."""
import pytest
from backtest import strategy as bt_strategy
from backtest import portfolio as bt_portfolio


# ── Baseline strategy: mirror politician trades, no exits except politician-sell ──


def test_baseline_buys_on_pub_date_for_followed_politician():
    """Baseline = current production logic: copy buys from the followed politician."""
    s = bt_strategy.BaselineStrategy(
        starting_cash=10000.0,
        notional_per_trade=1000.0,
    )

    s.set_following("Jane Doe")
    actions = s.on_pub_date(
        date="2020-12-10",
        new_filings=[
            {"id": "1", "politician": "Jane Doe", "ticker": "AAPL", "type": "buy",
             "amount_low": 15001, "amount_high": 50000, "amount_mid": 32500,
             "traded_date": "2020-11-10", "pub_date": "2020-12-10"},
            {"id": "2", "politician": "Other Person", "ticker": "MSFT", "type": "buy",
             "amount_low": 1001, "amount_high": 15000, "amount_mid": 8000,
             "traded_date": "2020-11-10", "pub_date": "2020-12-10"},
        ],
    )

    # Only Jane's trade gets copied
    assert len(actions) == 1
    assert actions[0].kind == "buy"
    assert actions[0].ticker == "AAPL"
    assert actions[0].notional == pytest.approx(1000.0)


def test_baseline_does_not_exit_on_drawdown():
    """Baseline never exits on PnL — only mirrors politician sells."""
    s = bt_strategy.BaselineStrategy(starting_cash=10000.0, notional_per_trade=1000.0)
    s.set_following("Jane Doe")

    # Open position
    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    # Massive drop — baseline does nothing
    exits = s.check_exits(
        date="2020-12-10",
        portfolio=p,
        current_prices={"AAPL": 50.0},
    )
    assert exits == []


def test_baseline_exits_when_politician_sells():
    s = bt_strategy.BaselineStrategy(starting_cash=10000.0, notional_per_trade=1000.0)
    s.set_following("Jane Doe")

    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    actions = s.on_pub_date(
        date="2020-12-15",
        new_filings=[
            {"id": "99", "politician": "Jane Doe", "ticker": "AAPL", "type": "sell",
             "amount_low": 1001, "amount_high": 15000, "amount_mid": 8000,
             "traded_date": "2020-11-15", "pub_date": "2020-12-15"},
        ],
    )

    sells = [a for a in actions if a.kind == "sell"]
    assert len(sells) == 1
    assert sells[0].ticker == "AAPL"


# ── Improved strategy: pub_date freshness + hybrid exits + amount weighting ──


def test_improved_skips_stale_filings():
    """Improved strategy: only act on filings whose pub_date is within freshness window."""
    s = bt_strategy.ImprovedStrategy(
        starting_cash=10000.0,
        notional_per_trade=1000.0,
        pub_freshness_days=7,
    )
    s.set_following("Jane Doe")

    actions = s.on_pub_date(
        date="2020-12-20",
        new_filings=[
            # Fresh filing (10 days behind today's date — within 7? no — but let's test stale)
            {"id": "1", "politician": "Jane Doe", "ticker": "AAPL", "type": "buy",
             "amount_low": 15001, "amount_high": 50000, "amount_mid": 32500,
             "traded_date": "2020-11-01", "pub_date": "2020-12-10"},  # 10d behind
            # Fresh (3d behind today)
            {"id": "2", "politician": "Jane Doe", "ticker": "MSFT", "type": "buy",
             "amount_low": 15001, "amount_high": 50000, "amount_mid": 32500,
             "traded_date": "2020-12-10", "pub_date": "2020-12-17"},
        ],
    )

    tickers = [a.ticker for a in actions]
    assert "MSFT" in tickers      # fresh → copied
    assert "AAPL" not in tickers  # stale → skipped


def test_improved_skips_small_dollar_trades():
    """Improved strategy: skip trades below $15k (noise — low conviction)."""
    s = bt_strategy.ImprovedStrategy(
        starting_cash=10000.0,
        notional_per_trade=1000.0,
        pub_freshness_days=30,
        min_amount=15000,
    )
    s.set_following("Jane Doe")

    actions = s.on_pub_date(
        date="2020-12-10",
        new_filings=[
            {"id": "1", "politician": "Jane Doe", "ticker": "AAPL", "type": "buy",
             "amount_low": 1001, "amount_high": 15000, "amount_mid": 8000,
             "traded_date": "2020-11-10", "pub_date": "2020-12-10"},
            {"id": "2", "politician": "Jane Doe", "ticker": "MSFT", "type": "buy",
             "amount_low": 50001, "amount_high": 100000, "amount_mid": 75000,
             "traded_date": "2020-11-10", "pub_date": "2020-12-10"},
        ],
    )

    tickers = [a.ticker for a in actions]
    assert tickers == ["MSFT"]


def test_improved_exits_on_hard_stop_loss():
    s = bt_strategy.ImprovedStrategy(
        starting_cash=10000.0,
        notional_per_trade=1000.0,
        stop_loss_pct=8.0,
    )

    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    # Price drops 10% — should trigger stop
    exits = s.check_exits(
        date="2020-11-15",
        portfolio=p,
        current_prices={"AAPL": 90.0},
    )
    assert len(exits) == 1
    assert exits[0].ticker == "AAPL"
    assert exits[0].reason == "stop_loss"


def test_improved_arms_trailing_stop_above_threshold():
    s = bt_strategy.ImprovedStrategy(
        starting_cash=10000.0,
        notional_per_trade=1000.0,
        stop_loss_pct=8.0,
        trail_arm_pct=8.0,
        trail_giveback_pct=5.0,
    )

    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-11-10")

    # Price runs up to 120 (HWM gets bumped). Then drops back to 113.
    # Trail-giveback floor = 120 * 0.95 = 114. So 113 < 114 → exit.
    s.check_exits(date="2020-11-15", portfolio=p, current_prices={"AAPL": 120.0})
    exits = s.check_exits(date="2020-11-20", portfolio=p, current_prices={"AAPL": 113.0})

    assert len(exits) == 1
    assert exits[0].reason == "trailing_stop"


def test_improved_exits_after_max_holding_days():
    s = bt_strategy.ImprovedStrategy(
        starting_cash=10000.0,
        notional_per_trade=1000.0,
        max_holding_days=90,
    )

    p = bt_portfolio.SimulatedPortfolio(starting_cash=10000.0)
    p.buy("AAPL", notional=1000.0, fill_price=100.0, date_iso="2020-08-01")

    # 91 days later, no triggers, but signal expired
    exits = s.check_exits(date="2020-10-31", portfolio=p, current_prices={"AAPL": 101.0})

    assert len(exits) == 1
    assert exits[0].reason == "signal_expired"
